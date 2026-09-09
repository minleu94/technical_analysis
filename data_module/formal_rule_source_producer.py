"""當日 prospective Rule source 的機器重驗 producer。

此模組把既有已接受的 Rule policy 與當日可重驗的唯讀市場視窗接起來。
它只在 PIT cutoff 前建立當日 machine source bundle（包含供日內 Rule
producer 使用的 prepublished clock、universe identity 與 revalidation
receipt）；09:00--13:30 的 daily Rule capture 仍由既有
``prospective_rule_only_decision`` producer 執行，並只能綁定這份已預發布
的 Rule source。PIT cutoff 後本入口只允許重驗同一 deterministic bundle，
不會新建同日 clock。任何輸出都限制在 repo publication root，D 槽 market
database 只以 SQLite read-only 讀取。

machine acceptance 是既有 owner policy 的衍生證據，不是人工簽名，也不會
開啟 formal OOS、promotion、broker 或歷史回填。缺官方日曆、來源視窗、
完整 T-1 universe 或錯過 pre-open window 時，入口回傳具體 blocker 且不
建立新的當日 clock。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.formal_runtime_config import (
    FORMAL_RUNTIME_CONFIG_ENV,
    FormalRuntimeConfigError,
    load_optional_formal_runtime_config,
)
from data_module.prospective_formal_clock import (
    CALENDAR_EVIDENCE_SCHEMA_VERSION,
    PROSPECTIVE_FORMAL_CLOCK_MODE,
    PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION,
    PROSPECTIVE_FORMAL_CLOCK_STATUS,
    SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON,
    SAME_DAY_PREOPEN_OWNER_OVERRIDE_SCHEMA_VERSION,
    ProspectiveFormalClock,
    build_clock_manifest,
    canonical_json,
    file_sha256,
    load_clock_manifest_for_capture,
    payload_hash,
    write_immutable_clock_manifest,
)
from development_module.manual_rule_only_decision import (
    ReadOnlyDailyPriceWindow,
    _normalized_symbol,
    _require_date_key,
    _universe_hash,
    load_read_only_daily_price_window,
    rank_rule_only_candidates,
    sha256_identifier,
)
from development_module.prospective_rule_only_decision import (
    _load_owner_acceptance,
)


MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION = (
    "prospective-formal-rule-source-machine-revalidation.v3"
)
LEGACY_MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION = (
    "prospective-formal-rule-source-machine-revalidation.v2"
)
LEGACY_MACHINE_RULE_SOURCE_PRODUCER_VERSION = "machine-revalidated-rule-source.v2"
MACHINE_RULE_SOURCE_PRODUCER_VERSION = "machine-revalidated-rule-source.v3"
UNIVERSE_IDENTITY_SCHEMA_VERSION = "manual-rule-only-universe.v1"
RULE_SOURCE_BUNDLE_DIRECTORY_PREFIX = "clock-"
RULE_SOURCE_BUNDLE_VERSION = "machine-v2"
TAIWAN_PIT_CUTOFF = time(8, 30)
TAIWAN_RULE_SESSION_OPEN = time(9, 0)
TAIWAN_RULE_SESSION_CLOSE = time(13, 30)
MACHINE_REVIEW_IDENTITY = "formal-rule-source-revalidator.v1"
MACHINE_REVIEW_REASON = (
    "existing_owner_policy_revalidated_against_current_readonly_source_window"
)
_TAIPEI = ZoneInfo("Asia/Taipei")
_SHA256_PREFIX = "sha256:"
_SHA256_LENGTH = len("sha256:") + 64
SOURCE_WINDOW_SCHEMA_VERSION = "formal-rule-source-window.v1"
SOURCE_WINDOW_RELATIVE_PATH = "source/daily_price_window.json"
# The complete 60-session Taiwan universe is large (roughly 76 MiB in the
# canonical JSON observed on 2026-09-08).  Keep a hard cap while allowing a
# real full-window capture to be persisted; this is still bounded and avoids
# silently truncating rows or replacing them with a sampled fixture.
SOURCE_WINDOW_MAX_BYTES = 128 * 1024 * 1024


class FormalRuleSourceProducerError(ValueError):
    """當日 Rule source 無法以客觀證據建立時的 fail-closed 錯誤。"""


class FormalRuleSourceWaiting(FormalRuleSourceProducerError):
    """排程尚未到可建立或可捕捉的自然時窗。"""


def _source_phase(observed_taipei: datetime) -> str:
    """回報 machine source 階段，不把它誤標成日內 Rule decision。"""

    local_time = observed_taipei.timetz().replace(tzinfo=None)
    if local_time < TAIWAN_PIT_CUTOFF:
        return "preopen_machine_source_prepublication"
    if local_time < TAIWAN_RULE_SESSION_OPEN:
        return "preopen_window_missed"
    if local_time <= TAIWAN_RULE_SESSION_CLOSE:
        return "postopen_machine_source_reuse"
    return "postclose_machine_source_reuse"


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FormalRuleSourceProducerError(f"{name} requires timezone")
    return value


def _normalise_observed(value: datetime | None) -> tuple[datetime, datetime]:
    observed_utc = _require_aware(
        value if value is not None else datetime.now(timezone.utc),
        "observed_at",
    ).astimezone(timezone.utc)
    return observed_utc, observed_utc.astimezone(_TAIPEI)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and value.startswith(_SHA256_PREFIX)
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FormalRuleSourceProducerError(f"source_file_missing:{path}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalRuleSourceProducerError(
            f"source_file_unreadable:{path}:{type(error).__name__}"
        ) from error


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise FormalRuleSourceProducerError(f"{label}_must_be_object:{path}")
    return value


def _canonical_file_bytes(value: object, *, newline: bool = True) -> bytes:
    encoded = canonical_json(value).encode("utf-8")
    return encoded + (b"\n" if newline else b"")


def _bytes_hash(value: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _source_window_payload(window: Any, *, decision_session: date) -> dict[str, object]:
    """Build the exact hash input used by the read-only daily-price loader.

    The source window is persisted as a derived, bounded JSON artifact for new
    machine captures.  Its ``source_payload`` deliberately matches
    ``load_read_only_daily_price_window``'s hash input byte-for-byte after
    canonical JSON encoding; metadata such as the DB mtime is kept outside the
    decision identity.
    """

    records_value = getattr(window, "records", None)
    if not isinstance(records_value, (list, tuple)) or not records_value:
        raise FormalRuleSourceProducerError("rule_window_records_not_persistable")
    records: list[dict[str, object]] = []
    for record in records_value:
        if not isinstance(record, Mapping):
            raise FormalRuleSourceProducerError("rule_window_record_not_object")
        records.append({str(key): value for key, value in record.items()})
    session_dates_value = getattr(window, "session_dates", None)
    if not isinstance(session_dates_value, (list, tuple)) or not session_dates_value:
        raise FormalRuleSourceProducerError("rule_window_sessions_not_persistable")
    session_dates = [str(item) for item in session_dates_value]
    source_payload: dict[str, object] = {
        "schema_version": "manual-rule-only-daily-price-window.v1",
        "source_id": "daily_prices",
        "decision_session": decision_session.isoformat(),
        "session_dates": session_dates,
        "records": records,
    }
    supplied_hash = getattr(window, "source_hash", None)
    if supplied_hash != sha256_identifier(source_payload):
        raise FormalRuleSourceProducerError("rule_window_hash_not_persistable")
    return source_payload


def _captured_window_file_payload(
    window: Any,
    *,
    decision_session: date,
) -> dict[str, object]:
    """Return the immutable source-window envelope written by v3 captures."""

    source_payload = _source_window_payload(window, decision_session=decision_session)
    data_as_of = str(getattr(window, "data_as_of_date", ""))
    max_available = str(getattr(window, "max_available_timestamp", ""))
    if not data_as_of or not max_available:
        raise FormalRuleSourceProducerError("rule_window_metadata_not_persistable")
    return {
        "schema_version": SOURCE_WINDOW_SCHEMA_VERSION,
        "source_payload": source_payload,
        "source_window_hash": str(getattr(window, "source_hash")),
        "data_as_of_date": data_as_of,
        "max_available_timestamp": max_available,
        "capture_boundary": "daily_prices.date < decision_session",
    }


def _read_captured_window(
    root: Path,
    *,
    receipt: Mapping[str, object],
    decision_session: date,
    source_window_hash: str,
    receipt_observed: datetime,
) -> dict[str, object]:
    """Validate v3 immutable window bytes and return its source payload.

    The path is derived from the bundle root rather than trusted from receipt
    text.  This keeps the artifact inside the bundle and prevents a receipt
    from redirecting the consumer to an unrelated file.
    """

    path = root / SOURCE_WINDOW_RELATIVE_PATH
    expected_path = receipt.get("source_window_path")
    if expected_path != SOURCE_WINDOW_RELATIVE_PATH:
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_path_invalid")
    expected_hash = receipt.get("source_window_file_hash")
    if not _is_sha256(expected_hash):
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_file_hash_invalid")
    try:
        with path.open("rb") as stream:
            raw = stream.read(SOURCE_WINDOW_MAX_BYTES + 1)
    except (OSError, FileNotFoundError) as error:
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_missing") from error
    if len(raw) > SOURCE_WINDOW_MAX_BYTES:
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_too_large")
    if _bytes_hash(raw) != expected_hash:
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_file_hash_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_unreadable") from error
    if not isinstance(value, Mapping):
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_not_object")
    envelope = {str(key): item for key, item in value.items()}
    if raw != _canonical_file_bytes(envelope):
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_not_canonical")
    if envelope.get("schema_version") != SOURCE_WINDOW_SCHEMA_VERSION:
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_schema_invalid")
    if envelope.get("source_window_hash") != source_window_hash:
        raise FormalRuleSourceProducerError("machine_revalidation_source_window_hash_mismatch")
    source_payload = envelope.get("source_payload")
    if not isinstance(source_payload, Mapping):
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_missing")
    source_payload_dict = {str(key): item for key, item in source_payload.items()}
    if sha256_identifier(source_payload_dict) != source_window_hash:
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_hash_mismatch")
    if source_payload_dict.get("source_id") != "daily_prices":
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_id_invalid")
    if source_payload_dict.get("decision_session") != decision_session.isoformat():
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_session_mismatch")
    session_dates = source_payload_dict.get("session_dates")
    records = source_payload_dict.get("records")
    if not isinstance(session_dates, list) or not session_dates or not all(
        isinstance(item, str) for item in session_dates
    ):
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_sessions_invalid")
    if not isinstance(records, list) or not records:
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_records_invalid")
    try:
        parsed_sessions = [date.fromisoformat(item) for item in session_dates]
    except ValueError as error:
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_sessions_invalid") from error
    if [item.isoformat() for item in parsed_sessions] != session_dates or parsed_sessions != sorted(set(parsed_sessions)):
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_sessions_invalid")
    if envelope.get("data_as_of_date") != session_dates[-1]:
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_data_date_mismatch")
    max_available_raw = envelope.get("max_available_timestamp")
    if not isinstance(max_available_raw, str):
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_max_available_missing")
    try:
        max_available = _require_aware(
            datetime.fromisoformat(max_available_raw),
            "machine_revalidation.source_window.max_available_timestamp",
        ).astimezone(timezone.utc)
    except (TypeError, ValueError) as error:
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_max_available_invalid") from error
    if max_available > receipt_observed:
        raise FormalRuleSourceProducerError("machine_revalidation_source_payload_available_after_observation")
    session_set = set(session_dates)
    seen_keys: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_payload_record_not_object"
            )
        try:
            record_date = _require_date_key(record.get("日期"))
            symbol = _normalized_symbol(record.get("證券代號"))
        except Exception as error:  # noqa: BLE001 - source boundary is fail closed
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_payload_record_identity_invalid"
            ) from error
        if record_date not in session_set or record_date >= decision_session.isoformat():
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_payload_record_outside_t1_window"
            )
        key = (symbol, record_date)
        if key in seen_keys:
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_payload_duplicate_symbol_date"
            )
        seen_keys.add(key)
    return envelope


def _captured_window_to_read_only(
    envelope: Mapping[str, object],
) -> ReadOnlyDailyPriceWindow:
    """把已驗證的 v3 envelope 還原成正式 ranker 使用的 window。"""

    source_payload = envelope.get("source_payload")
    if not isinstance(source_payload, Mapping):  # pragma: no cover - guarded reader
        raise FormalRuleSourceProducerError(
            "machine_revalidation_source_payload_missing"
        )
    records_value = source_payload.get("records")
    sessions_value = source_payload.get("session_dates")
    data_as_of = envelope.get("data_as_of_date")
    max_available = envelope.get("max_available_timestamp")
    source_hash = envelope.get("source_window_hash")
    if (
        not isinstance(records_value, list)
        or not isinstance(sessions_value, list)
        or not isinstance(data_as_of, str)
        or not isinstance(max_available, str)
        or not isinstance(source_hash, str)
    ):  # pragma: no cover - guarded reader
        raise FormalRuleSourceProducerError(
            "machine_revalidation_source_payload_invalid"
        )
    records: list[dict[str, object]] = []
    for record in records_value:
        if not isinstance(record, Mapping):  # pragma: no cover - guarded reader
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_payload_record_not_object"
            )
        records.append({str(key): item for key, item in record.items()})
    sessions = tuple(str(item) for item in sessions_value)
    return ReadOnlyDailyPriceWindow(
        records=tuple(records),
        session_dates=sessions,
        data_as_of_date=data_as_of,
        source_hash=source_hash,
        max_available_timestamp=max_available,
    )


def _write_create_only_json(path: Path, value: object) -> str:
    """以 create-only + fsync 寫入一個 bundle 子證據。"""

    if not path.parent.exists():
        raise FormalRuleSourceProducerError(
            f"bundle_parent_must_exist:{path.parent}"
        )
    encoded = _canonical_file_bytes(value)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise FormalRuleSourceProducerError(
            f"immutable_bundle_file_already_exists:{path}"
        ) from error
    return file_sha256(path)


def _write_json_create_or_match(path: Path, value: object, label: str) -> str:
    """恢復中斷 bundle 時只接受 byte-identical child，不覆寫既有檔。"""

    expected = _bytes_hash(_canonical_file_bytes(value))
    if path.exists():
        if path.is_file() and file_sha256(path) == expected:
            return expected
        raise FormalRuleSourceProducerError(
            f"immutable_bundle_file_hash_mismatch:{label}"
        )
    return _write_create_only_json(path, value)


def _validated_repo_output_root(output_root: Path, repo_root: Path) -> Path:
    """限制正式 CLI 的寫入目標在 repo output，拒絕 junction/D 槽逃逸。"""

    resolved = output_root.expanduser().resolve()
    allowed = (repo_root / "output").resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as error:
        raise FormalRuleSourceProducerError(
            "rule_source_output_root_must_be_under_repository_output"
        ) from error
    if resolved == allowed:
        raise FormalRuleSourceProducerError(
            "rule_source_output_root_must_be_dedicated_subdirectory"
        )
    return resolved


def _find_baseline_bundle(
    baseline_root: Path,
    *,
    observed_utc: datetime,
    target_day: date,
) -> tuple[Path, Path, Path, ProspectiveFormalClock, dict[str, object], tuple[str, ...]]:
    """從歷史 bundle 只讀取已接受 policy 與 symbols 作為重驗基線。"""

    resolved_root = baseline_root.expanduser().resolve()
    if not resolved_root.is_dir():
        raise FormalRuleSourceProducerError(
            f"rule_baseline_root_missing:{resolved_root}"
        )
    candidates: list[
        tuple[
            date,
            Path,
            Path,
            Path,
            ProspectiveFormalClock,
            dict[str, object],
            tuple[str, ...],
        ]
    ] = []
    for clock_path in sorted(resolved_root.glob("clock-*/clock/manifest.json")):
        bundle_root = clock_path.parent.parent
        owner_path = bundle_root / "metadata" / "owner_acceptance.json"
        symbols_path = bundle_root / "metadata" / "universe_symbols.json"
        try:
            raw_clock = _read_json_object(clock_path, "baseline_clock")
            activation_raw = raw_clock.get("activation_trading_day")
            if not isinstance(activation_raw, str):
                raise FormalRuleSourceProducerError(
                    "baseline_clock_activation_date_missing"
                )
            activation_day = date.fromisoformat(activation_raw)
            if activation_day > target_day:
                continue
            clock = load_clock_manifest_for_capture(
                clock_path,
                now=observed_utc,
            )
            if clock.payload.get("real_money") is not False or clock.payload.get(
                "broker_execution"
            ) is not False:
                raise FormalRuleSourceProducerError(
                    "baseline_clock_has_live_execution_flag"
                )
            if clock.payload.get("historical_backfill_claimed") is not False:
                raise FormalRuleSourceProducerError(
                    "baseline_clock_claims_historical_backfill"
                )
            owner_payload, _ = _load_owner_acceptance(owner_path, clock)
            symbols_value = _read_json(symbols_path)
            if not isinstance(symbols_value, list) or not symbols_value:
                raise FormalRuleSourceProducerError(
                    "baseline_universe_symbols_invalid"
                )
            if any(
                not isinstance(item, str) or not item.strip()
                for item in symbols_value
            ):
                raise FormalRuleSourceProducerError(
                    "baseline_universe_symbols_invalid"
                )
            symbols = tuple(str(item).strip() for item in symbols_value)
            if symbols != tuple(sorted(set(symbols))):
                raise FormalRuleSourceProducerError(
                    "baseline_universe_symbols_not_sorted_unique"
                )
            candidates.append(
                (
                    activation_day,
                    clock_path,
                    owner_path,
                    symbols_path,
                    clock,
                    owner_payload,
                    symbols,
                )
            )
        except (OSError, TypeError, ValueError, KeyError) as error:
            # 壞的較新基線不能遮蔽仍可驗證的較舊 policy；所有候選都壞時
            # 由具體 blocker 告知呼叫端。
            continue
    if not candidates:
        raise FormalRuleSourceProducerError(
            "rule_baseline_bundle_not_verified"
        )
    selected = max(candidates, key=lambda item: (item[0], str(item[1])))
    _, clock_path, owner_path, symbols_path, clock, owner_payload, symbols = selected
    return clock_path, owner_path, symbols_path, clock, owner_payload, symbols


def _official_calendar_evidence(
    *,
    market_db: Path,
    calendar_cache_root: Path,
    target_day: date,
) -> dict[str, object]:
    """要求 hash-bound TWSE annual cache；不以 weekday 或行情猜開市。"""

    calendar = OfficialTradingCalendar(
        db_path=market_db,
        calendar_cache_path=calendar_cache_root,
        temporary_closure_path=calendar_cache_root,
    )
    is_trading_day, reason = calendar.is_official_trading_day(
        target_day,
        allow_online_probe=False,
    )
    evidence = calendar.evidence_for(target_day)
    if is_trading_day is not True:
        raise FormalRuleSourceProducerError(
            "official_calendar_not_proven:"
            f"{reason}:{evidence.get('mode', 'unknown')}"
        )
    if evidence.get("mode") != "hash_bound_official_calendar_cache":
        raise FormalRuleSourceProducerError(
            "official_calendar_cache_not_hash_bound"
        )
    if evidence.get("is_trading_day") is not True:
        raise FormalRuleSourceProducerError(
            "official_calendar_evidence_not_open"
        )
    source_hash = evidence.get("source_hash")
    if not _is_sha256(source_hash):
        raise FormalRuleSourceProducerError(
            "official_calendar_source_hash_missing_or_invalid"
        )
    coverage = evidence.get("coverage")
    if not isinstance(coverage, Mapping) or coverage.get("complete_year") is not True:
        raise FormalRuleSourceProducerError(
            "official_calendar_cache_not_complete_year"
        )
    # clock v1 的 reason code 只允許官方年度表語意；cache mode 仍保留在
    # source 字串與 hash，這裡把同一個已驗證 open 結果映射到 v1 名稱。
    reason_code = str(evidence.get("reason_code", reason))
    if reason_code in {
        "twse_holiday_schedule_cache_open",
        "twse_holiday_schedule_open",
    }:
        clock_reason = "twse_holiday_schedule_open"
    elif reason_code in {
        "twse_holiday_schedule_cache_explicit_open",
        "twse_holiday_schedule_explicit_open",
    }:
        clock_reason = "twse_holiday_schedule_explicit_open"
    else:
        raise FormalRuleSourceProducerError(
            f"official_calendar_open_reason_not_supported:{reason_code}"
        )
    source = evidence.get("source")
    if isinstance(source, Mapping):
        endpoint = source.get("endpoint")
    else:
        endpoint = None
    return {
        "schema_version": CALENDAR_EVIDENCE_SCHEMA_VERSION,
        "date": target_day.isoformat(),
        "is_trading_day": True,
        "reason_code": clock_reason,
        "source": (
            "TWSE official holidaySchedule hash-bound cache"
            + (f" ({endpoint})" if isinstance(endpoint, str) else "")
        ),
        "source_hash": source_hash,
    }


def _read_current_rule_window(
    market_db: Path,
    *,
    target_day: date,
    observed_utc: datetime,
    symbols: Sequence[str],
) -> tuple[Any, str]:
    """讀取當日 T-1 視窗並重新計算完整 frozen universe hash。"""

    resolved = market_db.expanduser().resolve()
    if not resolved.is_file():
        raise FormalRuleSourceProducerError(
            f"rule_market_db_source_file_missing:{resolved}"
        )
    window = load_read_only_daily_price_window(
        resolved,
        decision_session=target_day,
    )
    max_available = datetime.fromisoformat(window.max_available_timestamp)
    if max_available.tzinfo is None or max_available.utcoffset() is None:
        raise FormalRuleSourceProducerError(
            "rule_market_window_availability_missing_timezone"
        )
    if max_available.astimezone(timezone.utc) > observed_utc:
        raise FormalRuleSourceProducerError(
            "market_db_timestamp_later_than_decision_time"
        )
    if not _is_sha256(window.source_hash):
        raise FormalRuleSourceProducerError(
            "rule_market_window_source_hash_invalid"
        )
    candidates = rank_rule_only_candidates(window, eligible_symbols=symbols)
    if len(candidates) != len(symbols):
        raise FormalRuleSourceProducerError(
            "clock_bound_rule_universe_incomplete_t1_history"
        )
    universe_hash = _universe_hash(candidates)
    if not _is_sha256(universe_hash):
        raise FormalRuleSourceProducerError("rule_universe_hash_invalid")
    return window, universe_hash


def _build_machine_acceptance(
    parent: Mapping[str, object],
    *,
    universe_hash: str,
    observed_utc: datetime,
    window: Any,
    producer_version: str = MACHINE_RULE_SOURCE_PRODUCER_VERSION,
    parent_owner_hash: str,
    parent_clock_hash: str,
    parent_symbols_hash: str,
    market_db_hash: str,
) -> dict[str, object]:
    """產生可重驗的 machine derived acceptance，不改 parent owner 檔。"""

    result = dict(parent)
    result.update(
        {
            "universe_hash": universe_hash,
            "acceptance_source": "machine_revalidated_existing_owner_policy",
            "machine_review_identity": MACHINE_REVIEW_IDENTITY,
            "machine_review_version": producer_version,
            "machine_review_reason": MACHINE_REVIEW_REASON,
            "machine_reviewed_at": observed_utc.isoformat(
                timespec="microseconds"
            ),
            "parent_owner_acceptance_file_hash": parent_owner_hash,
            "parent_clock_manifest_file_hash": parent_clock_hash,
            "parent_universe_symbols_file_hash": parent_symbols_hash,
            "revalidated_source_window_hash": str(window.source_hash),
            "revalidated_data_as_of_date": str(window.data_as_of_date),
            "revalidated_decision_session": observed_utc.astimezone(
                _TAIPEI
            ).date().isoformat(),
            "revalidated_market_db_file_hash": market_db_hash,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "promotion_eligible": False,
            "broker_order_allowed": False,
        }
    )
    return result


def _build_machine_clock(
    parent: ProspectiveFormalClock,
    *,
    target_day: date,
    observed_utc: datetime,
    calendar_evidence: Mapping[str, object],
    universe_hash: str,
) -> dict[str, object]:
    """沿 parent policy 建立當日 machine-revalidated candidate clock。"""

    payload = dict(parent.payload)
    payload.pop("manifest_hash", None)
    payload.update(
        {
            "schema_version": PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION,
            "status": PROSPECTIVE_FORMAL_CLOCK_STATUS,
            "mode": PROSPECTIVE_FORMAL_CLOCK_MODE,
            "clock_id": (
                f"clock:prospective:{target_day.strftime('%Y%m%d')}:"
                "machine-revalidated-v1"
            ),
            "activation_trading_day": target_day.isoformat(),
            "activation_calendar_evidence": dict(calendar_evidence),
            "universe_hash": universe_hash,
            "activation_timing_override": {
                "schema_version": SAME_DAY_PREOPEN_OWNER_OVERRIDE_SCHEMA_VERSION,
                "owner_override_id": (
                    f"machine-rule-source:{target_day.strftime('%Y%m%d')}:v1"
                ),
                "owner_override_timestamp": observed_utc.isoformat(
                    timespec="microseconds"
                ),
                "reason_code": SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON,
                "activation_trading_day": target_day.isoformat(),
                "historical_backfill_allowed": False,
                "same_day_preopen_only": True,
            },
            "real_money": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
        }
    )
    return build_clock_manifest(payload)


def _bundle_paths(output_root: Path, *, target_day: date, source_hash: str, parent_clock_hash: str) -> dict[str, Path]:
    source_part = source_hash.split(":", 1)[1][:12]
    parent_part = parent_clock_hash.split(":", 1)[1][:12]
    bundle = output_root / (
        f"clock-{target_day.strftime('%Y%m%d')}-{RULE_SOURCE_BUNDLE_VERSION}-"
        f"{source_part}-{parent_part}"
    )
    return {
        "bundle": bundle,
        "clock": bundle / "clock" / "manifest.json",
        "owner": bundle / "metadata" / "owner_acceptance.json",
        "symbols": bundle / "metadata" / "universe_symbols.json",
        "identity": bundle / "metadata" / "universe_identity.json",
        "receipt": bundle / "metadata" / "machine_revalidation_receipt.json",
        "source_window": bundle / SOURCE_WINDOW_RELATIVE_PATH,
    }


def _verify_existing_bundle(
    paths: Mapping[str, Path],
    *,
    observed_utc: datetime,
    target_day: date,
    source_window_hash: str,
) -> dict[str, object] | None:
    """確認 deterministic bundle 完整且未被替換；不以目錄存在當成成功。"""

    bundle = paths["bundle"]
    if not bundle.exists():
        return None
    if not bundle.is_dir():
        raise FormalRuleSourceProducerError(
            f"rule_source_bundle_path_not_directory:{bundle}"
        )
    required = [
        paths[name]
        for name in ("clock", "owner", "symbols", "identity", "receipt")
    ]
    if not all(path.is_file() for path in required):
        # 允許一次中斷後在同一 deterministic path 補完；呼叫端會逐檔
        # create-only 寫入，不把不完整 bundle 暴露給 resolver（clock 最後寫）。
        return None
    receipt = _read_json_object(paths["receipt"], "machine_revalidation_receipt")
    if receipt.get("schema_version") != MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION:
        if receipt.get("schema_version") != LEGACY_MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION:
            raise FormalRuleSourceProducerError("machine_revalidation_receipt_schema_invalid")
    if receipt.get("schema_version") == MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION and not paths[
        "source_window"
    ].is_file():
        return None
    if receipt.get("source_window_hash") != source_window_hash:
        raise FormalRuleSourceProducerError("existing_bundle_source_window_changed")
    if receipt.get("activation_trading_day") != target_day.isoformat():
        raise FormalRuleSourceProducerError("existing_bundle_activation_day_changed")
    files = receipt.get("files")
    if not isinstance(files, Mapping):
        raise FormalRuleSourceProducerError("machine_revalidation_receipt_files_missing")
    # receipt 自己不能把自己的 hash 放進內容；其 integrity 由 canonical
    # JSON 可解析性及其中綁定的四個 child hashes 驗證。
    names = {
        "clock": paths["clock"],
        "owner": paths["owner"],
        "symbols": paths["symbols"],
        "identity": paths["identity"],
    }
    for name, path in names.items():
        expected = files.get(name)
        if not isinstance(expected, str) or file_sha256(path) != expected:
            raise FormalRuleSourceProducerError(
                f"existing_bundle_file_hash_mismatch:{name}"
            )
    load_clock_manifest_for_capture(paths["clock"], now=observed_utc)
    return {
        "status": "rule_source_bundle_reused",
        "rule_source_phase": _source_phase(observed_utc.astimezone(_TAIPEI)),
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "bundle_root": str(bundle.resolve()),
        "clock_manifest": str(paths["clock"].resolve()),
        "universe_symbols": str(paths["symbols"].resolve()),
        "owner_acceptance": str(paths["owner"].resolve()),
        "universe_identity": str(paths["identity"].resolve()),
        "machine_revalidation_receipt": str(paths["receipt"].resolve()),
        "source_window": (
            str(paths["source_window"].resolve())
            if paths["source_window"].is_file()
            else None
        ),
        "clock_manifest_hash": receipt.get("clock_manifest_hash"),
        "source_window_hash": source_window_hash,
        "observed_at": observed_utc.isoformat(timespec="microseconds"),
        "write_performed": False,
    }


def validate_machine_revalidation_bundle(
    bundle_root: str | Path,
    *,
    market_db: str | Path,
    observed: datetime | None = None,
) -> dict[str, object]:
    """驗證 machine bundle 的 receipt、子檔案、parent policy 與時序。

    這是正式 Rule resolver 的 consumer 邊界。resolver 不能只看 clock、
    owner、symbols 三個檔案存在；machine acceptance 必須有同一 bundle 的
    receipt，且 receipt 綁定當前 market DB bytes、source window、clock/owner
    parent 與每一個 child content hash。此函式只讀取輸入，不建立或修改檔案。
    """

    observed_utc, _ = _normalise_observed(observed)
    root = Path(bundle_root).expanduser().resolve()
    receipt_path = root / "metadata" / "machine_revalidation_receipt.json"
    clock_path = root / "clock" / "manifest.json"
    owner_path = root / "metadata" / "owner_acceptance.json"
    symbols_path = root / "metadata" / "universe_symbols.json"
    identity_path = root / "metadata" / "universe_identity.json"
    if not receipt_path.is_file():
        raise FormalRuleSourceProducerError("machine_revalidation_receipt_missing")
    receipt = _read_json_object(receipt_path, "machine_revalidation_receipt")
    receipt_schema = receipt.get("schema_version")
    if receipt_schema not in {
        MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION,
        LEGACY_MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION,
    }:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_schema_invalid"
        )
    if receipt.get("producer") != "data_module.formal_rule_source_producer":
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_producer_invalid"
        )
    expected_producer_version = (
        MACHINE_RULE_SOURCE_PRODUCER_VERSION
        if receipt_schema == MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION
        else LEGACY_MACHINE_RULE_SOURCE_PRODUCER_VERSION
    )
    if receipt.get("producer_version") != expected_producer_version:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_version_invalid"
        )
    has_persisted_source_window = receipt_schema == MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION
    if receipt.get("status") != "machine_revalidated_candidate_only":
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_status_invalid"
        )
    if receipt.get("machine_review_identity") != MACHINE_REVIEW_IDENTITY:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_identity_invalid"
        )
    if receipt.get("machine_review_reason") != MACHINE_REVIEW_REASON:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_reason_invalid"
        )
    if receipt.get("market_db_read_mode") != "sqlite_mode_ro_query_only":
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_market_db_mode_invalid"
        )
    observed_at_raw = receipt.get("observed_at")
    if not isinstance(observed_at_raw, str):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_observed_at_missing"
        )
    try:
        receipt_observed = _require_aware(
            datetime.fromisoformat(observed_at_raw),
            "machine_revalidation_receipt.observed_at",
        ).astimezone(timezone.utc)
    except (TypeError, ValueError) as error:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_observed_at_invalid"
        ) from error
    if receipt_observed > observed_utc:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_observed_at_in_future"
        )
    activation_day_raw = receipt.get("activation_trading_day")
    decision_session_raw = receipt.get("decision_session")
    if not isinstance(activation_day_raw, str) or not isinstance(
        decision_session_raw, str
    ):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_dates_missing"
        )
    try:
        activation_day = date.fromisoformat(activation_day_raw)
        decision_session = date.fromisoformat(decision_session_raw)
    except ValueError as error:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_dates_invalid"
        ) from error
    receipt_observed_taipei = receipt_observed.astimezone(_TAIPEI)
    # The machine bundle is a prepublished dependency for the regular-session
    # Rule producer.  A downstream consumer must enforce the same custody
    # boundary as the writer; otherwise a hand-built receipt could make a
    # post-cutoff clock look like an on-time preopen source.
    if (
        receipt_observed_taipei.date() != activation_day
        or receipt_observed_taipei.timetz().replace(tzinfo=None)
        >= TAIWAN_PIT_CUTOFF
    ):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_observed_after_preopen_cutoff"
        )
    if activation_day != decision_session:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_activation_session_mismatch"
        )
    source_window_hash = receipt.get("source_window_hash")
    if not _is_sha256(source_window_hash):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_source_window_hash_invalid"
        )
    source_window_hash_text = str(source_window_hash)
    captured_window: dict[str, object] | None = None
    if has_persisted_source_window:
        captured_window = _read_captured_window(
            root,
            receipt=receipt,
            decision_session=decision_session,
            source_window_hash=source_window_hash_text,
            receipt_observed=receipt_observed,
        )
    try:
        identity = _read_json_object(identity_path, "universe_identity")
        owner = _read_json_object(owner_path, "owner_acceptance")
        clock_payload = _read_json_object(clock_path, "clock_manifest")
        symbols = _read_json(symbols_path)
    except FormalRuleSourceProducerError:
        raise
    if not isinstance(symbols, list) or not symbols:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_symbols_invalid"
        )
    if any(not isinstance(item, str) or not item.strip() for item in symbols):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_symbols_invalid"
        )
    if symbols != sorted(set(symbols)):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_symbols_not_sorted_unique"
        )
    if identity.get("schema_version") != UNIVERSE_IDENTITY_SCHEMA_VERSION:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_schema_invalid"
        )
    if identity.get("source_id") != "daily_prices":
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_source_id_invalid"
        )
    if identity.get("candidate_count") != len(symbols):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_candidate_count_invalid"
        )
    identity_hash = identity.get("identity_hash")
    identity_body = dict(identity)
    identity_body.pop("identity_hash", None)
    if not isinstance(identity_hash, str) or payload_hash(identity_body) != identity_hash:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_hash_mismatch"
        )
    if identity.get("symbols") != symbols:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_symbols_mismatch"
        )
    if identity.get("source_window_hash") != source_window_hash:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_source_window_mismatch"
        )
    if identity.get("source_window_persisted", False) is not has_persisted_source_window:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_source_window_persistence_flag_mismatch"
        )
    if has_persisted_source_window:
        if captured_window is None:  # pragma: no cover - guarded above
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_window_missing"
            )
        captured_payload = captured_window.get("source_payload")
        if not isinstance(captured_payload, Mapping):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_payload_missing"
            )
        captured_sessions = captured_payload.get("session_dates")
        if (
            captured_window.get("data_as_of_date") != identity.get("data_as_of_date")
            or captured_window.get("max_available_timestamp")
            != identity.get("max_available_timestamp")
            or captured_sessions != identity.get("session_dates")
            or captured_sessions != receipt.get("source_session_dates")
        ):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_window_metadata_mismatch"
            )
        if identity.get("source_window_file_hash") != receipt.get(
            "source_window_file_hash"
        ):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_window_identity_hash_mismatch"
            )
    if receipt.get("data_as_of_date") != identity.get("data_as_of_date"):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_data_as_of_mismatch"
        )
    if identity.get("decision_session") != decision_session_raw:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_decision_session_mismatch"
        )
    if identity.get("data_as_of_date") == decision_session_raw:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_data_is_not_t_minus_one"
        )
    if identity.get("machine_review_identity") != MACHINE_REVIEW_IDENTITY:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_machine_id_invalid"
        )
    if identity.get("machine_review_reason") != MACHINE_REVIEW_REASON:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_reason_invalid"
        )
    if any(
        identity.get(field) is not expected
        for field, expected in (
            ("formal_oos_allowed", False),
            ("historical_backfill_claimed", False),
            ("production_blend_alpha_bp", 0),
            ("promotion_eligible", False),
            ("broker_order_allowed", False),
        )
    ):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_safety_flags_invalid"
        )
    receipt_safety = receipt.get("safety")
    if not isinstance(receipt_safety, Mapping):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_safety_missing"
        )
    for field, expected in (
        ("read_only_market_source", True),
        ("market_database_written", False),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
        ("historical_backfill_claimed", False),
        ("training_started", False),
    ):
        if receipt_safety.get(field) is not expected:
            raise FormalRuleSourceProducerError(
                "machine_revalidation_receipt_safety_flags_invalid"
            )
    try:
        clock = load_clock_manifest_for_capture(clock_path, now=observed_utc)
    except Exception as error:  # noqa: BLE001 - consumer 只輸出單一 blocker
        raise FormalRuleSourceProducerError(
            f"machine_revalidation_clock_invalid:{type(error).__name__}:{error}"
        ) from error
    if clock.activation_trading_day != activation_day:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_clock_activation_day_mismatch"
        )
    if clock.payload.get("universe_hash") != identity.get("universe_hash"):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_clock_universe_mismatch"
        )
    if has_persisted_source_window:
        if captured_window is None:  # pragma: no cover - guarded above
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_window_missing"
            )
        captured_payload = captured_window.get("source_payload")
        if not isinstance(captured_payload, Mapping):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_source_payload_missing"
            )
        captured_window_value = _captured_window_to_read_only(captured_window)
        try:
            captured_candidates = rank_rule_only_candidates(
                captured_window_value,
                eligible_symbols=symbols,
            )
        except Exception as error:  # noqa: BLE001 - consumer emits one blocker
            raise FormalRuleSourceProducerError(
                "machine_revalidation_captured_source_unrankable:"
                f"{type(error).__name__}:{error}"
            ) from error
        captured_universe_hash = _universe_hash(captured_candidates)
        if captured_universe_hash != identity.get("universe_hash"):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_captured_source_universe_mismatch"
            )
    if clock.payload.get("activation_calendar_evidence") != identity.get(
        "calendar_evidence"
    ) or clock.payload.get("activation_calendar_evidence") != receipt.get(
        "calendar_evidence"
    ):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_calendar_evidence_mismatch"
        )
    if receipt.get("clock_id") != clock.clock_id:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_clock_id_mismatch"
        )
    if receipt.get("owner_decision_id") != clock.payload.get("owner_decision_id"):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_owner_decision_mismatch"
        )
    if receipt.get("clock_manifest_hash") != clock.manifest_hash:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_clock_manifest_hash_mismatch"
        )
    expected_owner = {
        "decision_id": clock.payload.get("owner_decision_id"),
        "accepted_strategy_version": clock.payload.get("strategy_version"),
        "accepted_policy_version": clock.payload.get("policy_version"),
        "policy_hash": clock.payload.get("policy_hash"),
        "universe_hash": clock.payload.get("universe_hash"),
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }
    if any(owner.get(field) != expected for field, expected in expected_owner.items()):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_owner_clock_binding_invalid"
        )
    if owner.get("acceptance_source") != "machine_revalidated_existing_owner_policy":
        raise FormalRuleSourceProducerError(
            "machine_revalidation_owner_machine_source_invalid"
        )
    for field, expected_field_value in (
        ("machine_review_identity", MACHINE_REVIEW_IDENTITY),
        ("machine_review_version", expected_producer_version),
        ("machine_review_reason", MACHINE_REVIEW_REASON),
        ("revalidated_source_window_hash", source_window_hash),
        ("revalidated_decision_session", decision_session_raw),
    ):
        if owner.get(field) != expected_field_value:
            raise FormalRuleSourceProducerError(
                f"machine_revalidation_owner_{field}_invalid"
            )
    if (
        identity.get("source_db_file_hash") != receipt.get("market_db_file_hash")
        or owner.get("revalidated_market_db_file_hash")
        != receipt.get("market_db_file_hash")
    ):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_capture_db_hash_binding_invalid"
        )
    market_path = Path(market_db).expanduser().resolve()
    # The SQLite file is an append-only operational source.  Its whole-file
    # hash is retained as capture-time evidence, but it must not be used as
    # the decision identity: normal post-capture insertion of a future market
    # session changes that hash while leaving the strict T-1 window unchanged.
    # The window hash and frozen universe below remain mandatory and reject any
    # edit to rows that can affect this decision.
    try:
        market_hash = file_sha256(market_path)
    except OSError as error:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_market_db_unreadable"
        ) from error
    max_available_raw = receipt.get("max_available_timestamp")
    if not isinstance(max_available_raw, str):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_max_available_timestamp_missing"
        )
    try:
        max_available = _require_aware(
            datetime.fromisoformat(max_available_raw),
            "machine_revalidation.max_available_timestamp",
        ).astimezone(timezone.utc)
    except (TypeError, ValueError) as error:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_max_available_timestamp_invalid"
        ) from error
    if max_available > receipt_observed:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_source_available_after_observation"
        )
    if identity.get("max_available_timestamp") != max_available_raw:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_max_available_mismatch"
        )
    # v3 has an immutable source-window file and therefore replays that file
    # as the decision input.  The live SQLite query below is diagnostic only:
    # an append or a later correction must never silently replace captured
    # rows.  Legacy v2 has no persisted rows, so it keeps the strict live
    # revalidation path and rejects any T-1 mutation.
    current_market_hash = file_sha256(market_path)
    source_file_hash_matches_capture = current_market_hash == receipt.get(
        "market_db_file_hash"
    )
    current_source_hash: str | None = None
    live_source_window_matches_capture: bool | None = None
    live_source_window_status = (
        "immutable_capture_authoritative"
        if has_persisted_source_window
        else "legacy_live_revalidation_required"
    )
    if has_persisted_source_window:
        try:
            live_window = load_read_only_daily_price_window(
                market_path,
                decision_session=decision_session,
            )
            current_source_hash = str(live_window.source_hash)
            identity_sessions = identity.get("session_dates")
            live_source_window_matches_capture = (
                current_source_hash == source_window_hash
                and str(live_window.data_as_of_date)
                == str(identity.get("data_as_of_date"))
                and isinstance(identity_sessions, list)
                and list(live_window.session_dates)
                == [str(item) for item in identity_sessions]
            )
            live_source_window_status = (
                "live_t1_matches_capture"
                if live_source_window_matches_capture
                else "live_t1_differs_capture_diagnostic_only"
            )
        except Exception as error:  # noqa: BLE001 - captured source remains authoritative
            live_source_window_status = (
                "live_t1_unavailable_capture_replay_only:"
                f"{type(error).__name__}"
            )
    else:
        try:
            current_window = load_read_only_daily_price_window(
                market_path,
                decision_session=decision_session,
            )
        except Exception as error:  # noqa: BLE001 - consumer 只輸出單一 blocker
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_source_window_unavailable:"
                f"{type(error).__name__}:{error}"
            ) from error
        current_source_hash = str(current_window.source_hash)
        if current_source_hash != source_window_hash:
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_source_window_hash_mismatch"
            )
        current_data_as_of = str(current_window.data_as_of_date)
        if (
            current_data_as_of != str(identity.get("data_as_of_date"))
            or current_data_as_of >= decision_session_raw
        ):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_source_data_date_mismatch"
            )
        expected_sessions = identity.get("session_dates")
        receipt_sessions = receipt.get("source_session_dates")
        current_sessions = [str(item) for item in current_window.session_dates]
        if (
            not isinstance(expected_sessions, list)
            or not isinstance(receipt_sessions, list)
            or current_sessions != expected_sessions
            or current_sessions != receipt_sessions
        ):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_source_sessions_mismatch"
            )
        try:
            current_max_available = _require_aware(
                datetime.fromisoformat(str(current_window.max_available_timestamp)),
                "machine_revalidation.current_window.max_available_timestamp",
            ).astimezone(timezone.utc)
        except (TypeError, ValueError) as error:
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_source_max_available_invalid"
            ) from error
        if current_max_available > observed_utc:
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_source_available_after_observation"
            )
        try:
            current_candidates = rank_rule_only_candidates(
                current_window,
                eligible_symbols=symbols,
            )
        except Exception as error:  # noqa: BLE001 - consumer 只輸出單一 blocker
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_universe_unavailable:"
                f"{type(error).__name__}:{error}"
            ) from error
        if len(current_candidates) != len(symbols):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_universe_incomplete"
            )
        current_universe_hash = _universe_hash(current_candidates)
        if (
            current_universe_hash != identity.get("universe_hash")
            or current_universe_hash != clock_payload.get("universe_hash")
        ):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_current_universe_hash_mismatch"
            )
        # legacy v2 沒有 immutable row snapshot。來源檔在 capture 後變動時，
        # 在第一次完整驗證後再讀一次 T-1 window；只要 bounded window identity
        # 保持相同，未來 session append 可以接受；並行修改 T-1 時必須 fail
        # closed，不能發布混合讀取結果。
        if current_market_hash != market_hash:
            try:
                stable_window = load_read_only_daily_price_window(
                    market_path,
                    decision_session=decision_session,
                )
            except Exception as error:  # noqa: BLE001 - fail closed for legacy source
                raise FormalRuleSourceProducerError(
                    "machine_revalidation_legacy_source_window_reread_unavailable:"
                    f"{type(error).__name__}:{error}"
                ) from error
            stable_sessions = [str(item) for item in stable_window.session_dates]
            if (
                str(stable_window.source_hash) != current_source_hash
                or str(stable_window.data_as_of_date)
                != str(current_window.data_as_of_date)
                or stable_sessions != current_sessions
            ):
                raise FormalRuleSourceProducerError(
                    "machine_revalidation_legacy_source_window_changed_during_read"
                )
        live_source_window_matches_capture = True
        live_source_window_status = "legacy_live_t1_verified"
    files = receipt.get("files")
    if not isinstance(files, Mapping):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_receipt_files_missing"
        )
    child_paths = {
        "clock": clock_path,
        "owner": owner_path,
        "symbols": symbols_path,
        "identity": identity_path,
    }
    for name, path in child_paths.items():
        expected_file_hash = files.get(name)
        if (
            not isinstance(expected_file_hash, str)
            or file_sha256(path) != expected_file_hash
        ):
            raise FormalRuleSourceProducerError(
                f"machine_revalidation_child_hash_mismatch:{name}"
            )
    if files.get("identity") != _bytes_hash(_canonical_file_bytes(identity)):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_identity_file_hash_mismatch"
        )
    if receipt.get("owner_acceptance_hash") != files.get("owner"):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_owner_file_hash_mismatch"
        )
    parent = receipt.get("parent_policy")
    if not isinstance(parent, Mapping):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_parent_policy_missing"
        )
    for field, owner_field in (
        ("clock_manifest_file_hash", "parent_clock_manifest_file_hash"),
        ("owner_acceptance_file_hash", "parent_owner_acceptance_file_hash"),
        ("universe_symbols_file_hash", "parent_universe_symbols_file_hash"),
    ):
        if parent.get(field) != owner.get(owner_field) or parent.get(field) != identity.get(
            owner_field
        ):
            raise FormalRuleSourceProducerError(
                f"machine_revalidation_parent_{field}_mismatch"
            )
    parent_paths = {
        "clock_manifest": parent.get("clock_manifest_path"),
        "owner_acceptance": parent.get("owner_acceptance_path"),
        "universe_symbols": parent.get("universe_symbols_path"),
    }
    for label, raw_path in parent_paths.items():
        if not isinstance(raw_path, str):
            raise FormalRuleSourceProducerError(
                f"machine_revalidation_parent_{label}_path_missing"
            )
        parent_path = Path(raw_path).expanduser().resolve()
        if not parent_path.is_file():
            raise FormalRuleSourceProducerError(
                f"machine_revalidation_parent_{label}_missing"
            )
        expected_hash = parent.get(
            {
                "clock_manifest": "clock_manifest_file_hash",
                "owner_acceptance": "owner_acceptance_file_hash",
                "universe_symbols": "universe_symbols_file_hash",
            }[label]
        )
        if file_sha256(parent_path) != expected_hash:
            raise FormalRuleSourceProducerError(
                f"machine_revalidation_parent_{label}_hash_mismatch"
            )
    return {
        "status": "machine_revalidation_verified",
        "bundle_root": str(root),
        "clock_manifest_hash": clock.manifest_hash,
        "source_window_hash": source_window_hash,
        "source_window_persisted": has_persisted_source_window,
        "source_window_path": (
            str((root / SOURCE_WINDOW_RELATIVE_PATH).resolve())
            if has_persisted_source_window
            else None
        ),
        "captured_market_db_file_hash": receipt.get("market_db_file_hash"),
        "current_market_db_file_hash": current_market_hash,
        "market_db_file_hash_matches_capture": source_file_hash_matches_capture,
        "source_replay_mode": (
            "immutable_captured_window"
            if has_persisted_source_window
            else "legacy_live_t1_revalidation"
        ),
        "live_source_window_hash": current_source_hash,
        "live_source_window_matches_capture": live_source_window_matches_capture,
        "live_source_window_status": live_source_window_status,
        "market_db_hash_semantics": (
            "capture_time_diagnostic_only; T-1 source_window_hash is decision identity"
        ),
        "activation_trading_day": activation_day.isoformat(),
        "decision_session": decision_session_raw,
        "machine_review_identity": MACHINE_REVIEW_IDENTITY,
        "receipt_observed_at": receipt_observed.isoformat(),
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }


def load_verified_rule_source_window(
    bundle_root: str | Path,
    *,
    market_db: str | Path,
    observed: datetime | None = None,
) -> ReadOnlyDailyPriceWindow:
    """載入 machine bundle 驗證後真正要交給 Rule ranker 的 T-1 window。

    v3 bundle 的 persisted rows 是唯一決策輸入；live SQLite 只保留在
    validator 的診斷欄位。沒有 snapshot 的 v2 則在 validator 通過後重新讀
    live T-1 window，且 hash 改變時由 validator fail closed。這個 helper
    讓正式 daily producer 與 validator 共用同一條 exact bundle 路徑，避免
    驗證 A、決策時又自行掃描 B。
    """

    observed_utc, _ = _normalise_observed(observed)
    root = Path(bundle_root).expanduser().resolve()
    validation = validate_machine_revalidation_bundle(
        root,
        market_db=market_db,
        observed=observed_utc,
    )
    decision_session_raw = validation.get("decision_session")
    source_window_hash = validation.get("source_window_hash")
    if not isinstance(decision_session_raw, str) or not isinstance(
        source_window_hash, str
    ):
        raise FormalRuleSourceProducerError(
            "machine_revalidation_verified_window_identity_missing"
        )
    try:
        decision_session = date.fromisoformat(decision_session_raw)
    except ValueError as error:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_verified_window_session_invalid"
        ) from error
    if validation.get("source_window_persisted") is True:
        receipt_path = root / "metadata" / "machine_revalidation_receipt.json"
        receipt = _read_json_object(
            receipt_path,
            "machine_revalidation_receipt",
        )
        observed_at_raw = receipt.get("observed_at")
        if not isinstance(observed_at_raw, str):
            raise FormalRuleSourceProducerError(
                "machine_revalidation_receipt_observed_at_missing"
            )
        try:
            receipt_observed = _require_aware(
                datetime.fromisoformat(observed_at_raw),
                "machine_revalidation_receipt.observed_at",
            ).astimezone(timezone.utc)
        except (TypeError, ValueError) as error:
            raise FormalRuleSourceProducerError(
                "machine_revalidation_receipt_observed_at_invalid"
            ) from error
        envelope = _read_captured_window(
            root,
            receipt=receipt,
            decision_session=decision_session,
            source_window_hash=source_window_hash,
            receipt_observed=receipt_observed,
        )
        return _captured_window_to_read_only(envelope)

    # v2 has no source bytes to replay.  The validator has just checked the
    # live source hash; a second read is still checked against that result so
    # a concurrent updater cannot change the exact decision between validation
    # and ranking.
    window = load_read_only_daily_price_window(
        Path(market_db).expanduser().resolve(),
        decision_session=decision_session,
    )
    if str(window.source_hash) != source_window_hash:
        raise FormalRuleSourceProducerError(
            "machine_revalidation_legacy_source_window_changed_after_validation"
        )
    return window


def _persist_bundle(
    paths: Mapping[str, Path],
    *,
    clock_manifest: Mapping[str, object],
    owner_acceptance: Mapping[str, object],
    symbols: Sequence[str],
    identity: Mapping[str, object],
    receipt: Mapping[str, object],
    source_window: Mapping[str, object] | None = None,
) -> dict[str, object]:
    bundle = paths["bundle"]
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "clock").mkdir(parents=True, exist_ok=True)
    (bundle / "metadata").mkdir(parents=True, exist_ok=True)
    if source_window is not None:
        (bundle / "source").mkdir(parents=True, exist_ok=True)
    # clock 最後寫入；resolver 只有看見 clock 時才會嘗試整個 bundle。
    source_window_file_hash: str | None = None
    if source_window is not None:
        source_window_file_hash = _write_json_create_or_match(
            paths["source_window"], source_window, "source_window"
        )
        expected_source_window_hash = receipt.get("source_window_file_hash")
        if source_window_file_hash != expected_source_window_hash:
            raise FormalRuleSourceProducerError(
                "source_window_file_hash_unexpected"
            )
    symbols_hash = _write_json_create_or_match(
        paths["symbols"], list(symbols), "symbols"
    )
    identity_hash = _write_json_create_or_match(
        paths["identity"], identity, "identity"
    )
    owner_hash = _write_json_create_or_match(
        paths["owner"], owner_acceptance, "owner"
    )
    receipt_files = receipt.get("files")
    expected_files = (
        dict(receipt_files) if isinstance(receipt_files, Mapping) else {}
    )
    expected_files.update(
        {"symbols": symbols_hash, "identity": identity_hash, "owner": owner_hash}
    )
    receipt_with_files = dict(receipt)
    receipt_with_files["files"] = expected_files
    _write_json_create_or_match(
        paths["receipt"], receipt_with_files, "receipt"
    )
    clock_hash = write_immutable_clock_manifest(paths["clock"], clock_manifest)
    if clock_hash != expected_files.get("clock"):
        raise FormalRuleSourceProducerError("clock_file_hash_unexpected")
    return {
        "status": "rule_source_bundle_created",
        "rule_source_phase": "preopen_machine_source_prepublication",
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "bundle_root": str(bundle.resolve()),
        "clock_manifest": str(paths["clock"].resolve()),
        "universe_symbols": str(paths["symbols"].resolve()),
        "owner_acceptance": str(paths["owner"].resolve()),
        "universe_identity": str(paths["identity"].resolve()),
        "machine_revalidation_receipt": str(paths["receipt"].resolve()),
        "clock_manifest_hash": clock_manifest.get("manifest_hash"),
        "source_window_hash": receipt_with_files.get("source_window_hash"),
        "source_window": (
            str(paths["source_window"].resolve())
            if source_window_file_hash is not None
            else None
        ),
        "source_window_file_hash": source_window_file_hash,
        "observed_at": receipt_with_files.get("observed_at"),
        "write_performed": True,
    }


def produce_current_rule_source_bundle(
    *,
    output_root: str | Path,
    market_db: str | Path,
    baseline_root: str | Path,
    calendar_cache_root: str | Path,
    now: datetime | None = None,
) -> dict[str, object]:
    """建立或重驗一個當日 machine Rule source bundle。

    ``now`` 僅供隔離測試注入；公開 CLI 不提供時間覆寫。首次 bundle
    必須在台北 08:30 前完成，因為其中的 machine clock 是 prepublished
    source。08:30--09:00 代表已錯過 pre-open window；09:00--13:30
    只可重驗已存在的 bundle，讓 daily Rule producer 使用相同的 source
    identity。任何 cutoff 後的新建嘗試都保持 blocked，避免用事後時間
    冒充 pre-open clock。
    """

    observed_utc, observed_taipei = _normalise_observed(now)
    target_day = observed_taipei.date()
    rule_local_time = observed_taipei.timetz().replace(tzinfo=None)
    # 08:30--09:00 是 PIT 已截止、Rule 尚未開盤的明確缺窗。PIT
    # pre-open task 在 07:00--08:30 會呼叫本 producer，這是唯一可以
    # 首次建立當日 machine bundle 的階段；不可把 guard 移到 09:00 後
    # 才讓同日 clock 首次出現。
    if TAIWAN_PIT_CUTOFF <= rule_local_time < TAIWAN_RULE_SESSION_OPEN:
        raise FormalRuleSourceWaiting("same_day_rule_source_preopen_window_missed")
    past_cutoff = rule_local_time >= TAIWAN_PIT_CUTOFF
    late_rule_window = rule_local_time > TAIWAN_RULE_SESSION_CLOSE

    market_path = Path(market_db).expanduser().resolve()
    cache_root = Path(calendar_cache_root).expanduser().resolve()
    output_path = Path(output_root).expanduser().resolve()
    (
        parent_clock_path,
        parent_owner_path,
        parent_symbols_path,
        parent_clock,
        parent_owner,
        symbols,
    ) = _find_baseline_bundle(
        Path(baseline_root),
        observed_utc=observed_utc,
        target_day=target_day,
    )
    calendar_evidence = _official_calendar_evidence(
        market_db=market_path,
        calendar_cache_root=cache_root,
        target_day=target_day,
    )
    window, universe_hash = _read_current_rule_window(
        market_path,
        target_day=target_day,
        observed_utc=observed_utc,
        symbols=symbols,
    )
    source_window_hash = str(window.source_hash)
    # Real loader results carry the complete T-1 records, so new captures
    # persist an immutable bounded replay source.  Focused legacy callers may
    # provide only a hash-shaped test double; those remain v2 and are never
    # advertised as persisted snapshots.
    source_window: dict[str, object] | None = None
    if isinstance(getattr(window, "records", None), (list, tuple)):
        source_window = _captured_window_file_payload(
            window,
            decision_session=target_day,
        )
        source_window_bytes = _canonical_file_bytes(source_window)
        if len(source_window_bytes) > SOURCE_WINDOW_MAX_BYTES:
            raise FormalRuleSourceProducerError(
                "rule_window_source_artifact_too_large"
            )
    receipt_schema = (
        MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION
        if source_window is not None
        else LEGACY_MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION
    )
    receipt_producer_version = (
        MACHINE_RULE_SOURCE_PRODUCER_VERSION
        if source_window is not None
        else LEGACY_MACHINE_RULE_SOURCE_PRODUCER_VERSION
    )
    parent_clock_hash = file_sha256(parent_clock_path)
    parent_owner_hash = file_sha256(parent_owner_path)
    parent_symbols_hash = file_sha256(parent_symbols_path)
    market_db_hash = file_sha256(market_path)
    paths = _bundle_paths(
        output_path,
        target_day=target_day,
        source_hash=source_window_hash,
        parent_clock_hash=parent_clock_hash,
    )
    existing = _verify_existing_bundle(
        paths,
        observed_utc=observed_utc,
        target_day=target_day,
        source_window_hash=source_window_hash,
    )
    if existing is not None:
        # deterministic retry 也必須走同一個 consumer validator；receipt
        # 自己被竄改時不能因「目錄存在」而直接回 reused。
        existing["consumer_validation"] = validate_machine_revalidation_bundle(
            paths["bundle"],
            market_db=market_path,
            observed=observed_utc,
        )
        return existing
    if past_cutoff or late_rule_window:
        raise FormalRuleSourceWaiting(
            "same_day_rule_source_window_missed"
        )

    machine_acceptance = _build_machine_acceptance(
        parent_owner,
        universe_hash=universe_hash,
        observed_utc=observed_utc,
        window=window,
        producer_version=receipt_producer_version,
        parent_owner_hash=parent_owner_hash,
        parent_clock_hash=parent_clock_hash,
        parent_symbols_hash=parent_symbols_hash,
        market_db_hash=market_db_hash,
    )
    clock_manifest = _build_machine_clock(
        parent_clock,
        target_day=target_day,
        observed_utc=observed_utc,
        calendar_evidence=calendar_evidence,
        universe_hash=universe_hash,
    )
    # 避免產生第二套 clock 語意：先驗證精確的 canonical payload，再寫入
    # bundle；正式 consumer 讀 immutable 檔案時也會使用同一個 validator。
    from data_module.prospective_formal_clock import validate_clock_manifest

    validate_clock_manifest(
        clock_manifest,
        now=observed_utc,
        calendar_evidence=calendar_evidence,
    )
    identity_without_hash: dict[str, object] = {
        "schema_version": UNIVERSE_IDENTITY_SCHEMA_VERSION,
        "universe_hash": universe_hash,
        "symbols": list(symbols),
        "data_as_of_date": str(window.data_as_of_date),
        "decision_session": target_day.isoformat(),
        "session_dates": list(window.session_dates),
        "source_window_hash": source_window_hash,
        "source_window_persisted": source_window is not None,
        "source_id": "daily_prices",
        "candidate_count": len(symbols),
        "source_db_file_hash": market_db_hash,
        "source_db_path": str(market_path),
        "max_available_timestamp": str(window.max_available_timestamp),
        "calendar_evidence": dict(calendar_evidence),
        "machine_review_identity": MACHINE_REVIEW_IDENTITY,
        "machine_review_version": receipt_producer_version,
        "machine_review_reason": MACHINE_REVIEW_REASON,
        "parent_clock_manifest_file_hash": parent_clock_hash,
        "parent_owner_acceptance_file_hash": parent_owner_hash,
        "parent_universe_symbols_file_hash": parent_symbols_hash,
        "formal_oos_allowed": False,
        "historical_backfill_claimed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }


    if source_window is not None:
        identity_without_hash.update(
            {
                "source_window_file_hash": _bytes_hash(
                    _canonical_file_bytes(source_window)
                ),
                "source_window_path": SOURCE_WINDOW_RELATIVE_PATH,
                "source_window_custody": "immutable_bounded_json_records",
            }
        )
    identity = dict(identity_without_hash)
    identity["identity_hash"] = payload_hash(identity_without_hash)
    clock_file_bytes = canonical_json(clock_manifest).encode("utf-8")
    receipt: dict[str, object] = {
        "schema_version": receipt_schema,
        "producer": "data_module.formal_rule_source_producer",
        "producer_version": receipt_producer_version,
        "status": "machine_revalidated_candidate_only",
        "machine_review_identity": MACHINE_REVIEW_IDENTITY,
        "machine_review_reason": MACHINE_REVIEW_REASON,
        "observed_at": observed_utc.isoformat(timespec="microseconds"),
        "activation_trading_day": target_day.isoformat(),
        "clock_id": clock_manifest.get("clock_id"),
        "clock_manifest_hash": clock_manifest.get("manifest_hash"),
        "owner_decision_id": clock_manifest.get("owner_decision_id"),
        "owner_acceptance_hash": _bytes_hash(
            _canonical_file_bytes(machine_acceptance)
        ),
        "source_window_hash": source_window_hash,
        "data_as_of_date": str(window.data_as_of_date),
        "decision_session": target_day.isoformat(),
        "max_available_timestamp": str(window.max_available_timestamp),
        "source_session_dates": list(window.session_dates),
        "market_db_file_hash": market_db_hash,
        "market_db_file_hash_semantics": (
            "capture_time_diagnostic_only; T-1 source_window_hash is decision identity"
        ),
        "market_db_read_mode": "sqlite_mode_ro_query_only",
        "calendar_evidence": dict(calendar_evidence),
        "parent_policy": {
            "clock_manifest_file_hash": parent_clock_hash,
            "clock_manifest_path": str(parent_clock_path),
            "owner_acceptance_file_hash": parent_owner_hash,
            "owner_acceptance_path": str(parent_owner_path),
            "universe_symbols_file_hash": parent_symbols_hash,
            "universe_symbols_path": str(parent_symbols_path),
            "decision_id": parent_owner.get("decision_id"),
            "policy_hash": parent_owner.get("policy_hash"),
            "score_configuration_hash": parent_owner.get(
                "score_configuration_hash"
            ),
            "previous_universe_hash": parent_owner.get("universe_hash"),
        },
        "safety": {
            "read_only_market_source": True,
            "market_database_written": False,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "historical_backfill_claimed": False,
            "training_started": False,
        },
        "files": {
            "clock": _bytes_hash(clock_file_bytes),
            "owner": _bytes_hash(_canonical_file_bytes(machine_acceptance)),
            "symbols": _bytes_hash(_canonical_file_bytes(list(symbols))),
            "identity": _bytes_hash(_canonical_file_bytes(identity)),
        },
    }
    if source_window is not None:
        receipt.update(
            {
                "source_window_schema_version": SOURCE_WINDOW_SCHEMA_VERSION,
                "source_window_path": SOURCE_WINDOW_RELATIVE_PATH,
                "source_window_file_hash": _bytes_hash(
                    _canonical_file_bytes(source_window)
                ),
                "source_window_max_bytes": SOURCE_WINDOW_MAX_BYTES,
            }
        )
    result = _persist_bundle(
        paths,
        clock_manifest=clock_manifest,
        owner_acceptance=machine_acceptance,
        symbols=symbols,
        identity=identity,
        receipt=receipt,
        source_window=source_window,
    )
    return result


def _status_path(output_root: Path) -> Path:
    return output_root / "scheduler" / "rule_source_latest_status.json"


def _write_status(path: Path, status: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (canonical_json(dict(status)) + "\n").encode("utf-8")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)


def run_from_environment() -> tuple[dict[str, object], int]:
    """公開排程入口；時間只能取目前系統 clock。"""

    # 本模組由 ``python -m`` 執行；data_module 的上一層就是 repository。
    repo_root = Path(__file__).resolve().parent.parent
    observed_utc, observed_taipei = _normalise_observed(None)
    runtime_config: dict[str, object] | None = None
    runtime_config_error: str | None = None
    try:
        runtime_config = load_optional_formal_runtime_config(
            role="rule_source_wrapper",
            observed=observed_utc,
        )
    except FormalRuntimeConfigError as error:
        runtime_config_error = str(error)
    output_root = Path(
        os.environ.get(
            "FORMAL_DAILY_RULE_SOURCE_ROOT",
            str(repo_root / "output" / "formal_daily_publications" / "rule_source"),
        )
    )
    market_db = Path(
        os.environ.get(
            "FORMAL_DAILY_MARKET_DB",
            r"D:\Min\Python\Project\FA_Data\sqlite\twstock.db",
        )
    )
    baseline_root = Path(
        os.environ.get(
            "FORMAL_DAILY_RULE_BASELINE_ROOT",
            r"D:\Min\Python\Project\FA_Data\output\formal_prospective",
        )
    )
    calendar_root = Path(
        os.environ.get(
            "FORMAL_DAILY_CALENDAR_CACHE_ROOT",
            str(repo_root / "output" / "paper_execution_eod_replay" / "calendar_cache"),
        )
    )
    status_path = _status_path(output_root.expanduser().resolve())
    base: dict[str, object] = {
        "schema_version": MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION,
        "producer": "data_module.formal_rule_source_producer",
        "producer_version": MACHINE_RULE_SOURCE_PRODUCER_VERSION,
        "observed_at": observed_utc.isoformat(timespec="microseconds"),
        "decision_timezone": "Asia/Taipei",
        "taipei_date": observed_taipei.date().isoformat(),
        "taipei_time": observed_taipei.timetz().replace(tzinfo=None).isoformat(),
        "rule_source_phase": _source_phase(observed_taipei),
        "output_root": str(output_root.expanduser().resolve()),
        "market_db": str(market_db.expanduser().resolve()),
        "market_db_read_mode": "sqlite_mode_ro_query_only",
        "baseline_root": str(baseline_root.expanduser().resolve()),
        "calendar_cache_root": str(calendar_root.expanduser().resolve()),
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_market_database": False,
        "writes_formal_controlled_paths": False,
        "historical_backfill_claimed": False,
        "runtime_config": runtime_config
        if runtime_config is not None
        else {
            "status": "absent" if runtime_config_error is None else "invalid",
            "environment_variable": FORMAL_RUNTIME_CONFIG_ENV,
            "error": runtime_config_error,
        },
    }
    try:
        if runtime_config_error is not None:
            raise FormalRuntimeConfigError(runtime_config_error)
        if (
            runtime_config is not None
            and runtime_config.get("activation_status") != "active"
        ):
            activation_day = runtime_config.get("activation_trading_day")
            raise FormalRuleSourceWaiting(
                "runtime_config_waiting_for_activation:"
                f"{activation_day}"
            )
        safe_output = _validated_repo_output_root(output_root, repo_root)
        result = produce_current_rule_source_bundle(
            output_root=safe_output,
            market_db=market_db,
            baseline_root=baseline_root,
            calendar_cache_root=calendar_root,
# 這裡刻意傳入上方取得的真實觀測時間；CLI 沒有呼叫端可控制的時間參數。
            now=observed_utc,
        )
        status = {**base, **result, "status": result.get("status", "blocked")}
        exit_code = 0
    except FormalRuleSourceWaiting as error:
        status = {
            **base,
            "status": "blocked",
            "blockers": [f"waiting:{error}"],
        }
        exit_code = 2
    except Exception as error:  # noqa: BLE001 - scheduler 只輸出有界 blocker
        status = {
            **base,
            "status": "blocked",
            "blockers": [
                f"rule_source_producer_failed:{type(error).__name__}:"
                f"{str(error).splitlines()[0][:240]}"
            ],
        }
        exit_code = 2
    status["exit_code"] = exit_code
    status["status_path"] = str(status_path)
    _write_status(status_path, status)
    print(canonical_json(status))
    return status, exit_code


def main(argv: Sequence[str] | None = None) -> int:
    # 保留 argparse 入口以便錯誤參數立即失敗；刻意不提供 --now、--date
    # 或 fixture 選項，避免 operational wrapper 產生回填 clock。
    parser = argparse.ArgumentParser(
        description="以目前自然時間重驗並準備當日 prospective Rule source。"
    )
    parser.parse_args(argv)
    _, exit_code = run_from_environment()
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI integration boundary
    raise SystemExit(main())
