"""Prospective-only 正式模擬持倉 clock 的純契約與唯讀驗證器。

本模組只驗證 clock manifest，不建立 Portfolio transition、Rule snapshot、PIT
sidecar 或任何正式資料。它把 prospective simulation 與既有 full-history
``causal-portfolio-ledger.v1`` 隔離，並在 activation 前固定 model、training、
calibration 與 evaluation identities，避免以已消費的 Formal OOS 日期回頭改訓。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import hashlib
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo


PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION = (
    "prospective-formal-simulated-portfolio-clock.v1"
)
PROSPECTIVE_FORMAL_CLOCK_MODE = "prospective_formal_simulation"
PROSPECTIVE_FORMAL_CLOCK_STATUS = "planned"
CALENDAR_EVIDENCE_SCHEMA_VERSION = "official-trading-calendar-evidence.v1"
SAME_DAY_PREOPEN_OWNER_OVERRIDE_SCHEMA_VERSION = (
    "prospective-same-day-preopen-owner-override.v1"
)
SAME_DAY_PREOPEN_OWNER_OVERRIDE_REASON = (
    "owner_explicit_same_day_preopen_activation"
)
# 由既有 owner policy 與當日唯讀來源重新驗證出的 machine clock，不宣稱
# 有新的人工簽名；它只允許在 PIT cutoff 前建立 candidate clock，仍維持
# formal_oos／promotion／broker 全部關閉。
SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON = (
    "machine_revalidated_same_day_preopen_activation"
)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
SHA256_PREFIX = "sha256:"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_CLOCK_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "clock_id",
        "mode",
        "owner_decision_id",
        "owner_decision_timestamp",
        "activation_trading_day",
        "decision_timezone",
        "decision_time",
        "activation_calendar_evidence",
        "seed_state",
        "virtual_notional_minor_units",
        "strategy_version",
        "policy_version",
        "policy_hash",
        "universe_hash",
        "source_policy_hash",
        "candidate_model_hash",
        "candidate_feature_manifest_hash",
        "candidate_training_cutoff",
        "calibration_policy_hash",
        "evaluation_policy_hash",
        "real_money",
        "broker_execution",
        "historical_backfill_claimed",
        "manifest_hash",
    }
)
# A clock may expose a separate PIT boundary while retaining one owner-bound
# Rule/Portfolio decision time. Existing clocks omit this optional field and
# continue to inherit the Rule/Portfolio time for PIT capture.
_OPTIONAL_CLOCK_FIELDS = frozenset(
    {"pit_decision_time", "activation_timing_override"}
)
_SEED_FIELDS = frozenset({"kind", "cash_bp", "position_count", "state_hash"})
_CALENDAR_FIELDS = frozenset(
    {"schema_version", "date", "is_trading_day", "reason_code", "source", "source_hash"}
)
_ALLOWED_CALENDAR_REASONS = frozenset(
    {
        "twse_holiday_schedule_open",
        "twse_holiday_schedule_explicit_open",
        "twstock_db_market_indices_evidence",
    }
)
_ACTIVATION_TIMING_OVERRIDE_FIELDS = frozenset(
    {
        "schema_version",
        "owner_override_id",
        "owner_override_timestamp",
        "reason_code",
        "activation_trading_day",
        "historical_backfill_allowed",
        "same_day_preopen_only",
    }
)


class ProspectiveFormalClockError(ValueError):
    """Clock manifest 不符合 prospective-only 安全契約。"""


@dataclass(frozen=True)
class ProspectiveFormalClock:
    """通過 activation 前驗證的 immutable clock identity。"""

    clock_id: str
    activation_trading_day: date
    owner_decision_timestamp: datetime
    candidate_training_cutoff: datetime
    manifest_hash: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @property
    def mode(self) -> str:
        return str(self.payload["mode"])

    @property
    def candidate_model_hash(self) -> str:
        return str(self.payload["candidate_model_hash"])

    def custody_payload(self) -> dict[str, object]:
        """回傳不含 secret、可供 readiness/status 使用的 custody 摘要。"""

        result: dict[str, object] = {
            "schema_version": "prospective-formal-clock-custody.v1",
            "clock_id": self.clock_id,
            "mode": self.mode,
            "activation_trading_day": self.activation_trading_day.isoformat(),
            "owner_decision_timestamp": self.owner_decision_timestamp.isoformat(),
            "candidate_training_cutoff": self.candidate_training_cutoff.isoformat(),
            "candidate_model_hash": self.candidate_model_hash,
            "decision_time": str(self.payload["decision_time"]),
            "pit_decision_time": str(
                self.payload.get("pit_decision_time", self.payload["decision_time"])
            ),
            "calibration_policy_hash": self.payload["calibration_policy_hash"],
            "evaluation_policy_hash": self.payload["evaluation_policy_hash"],
            "historical_backfill_claimed": False,
            "real_money": False,
            "broker_execution": False,
            "manifest_hash": self.manifest_hash,
        }
        timing_override = self.payload.get("activation_timing_override")
        if isinstance(timing_override, Mapping):
            result["activation_timing_override"] = dict(timing_override)
        return result


def canonical_json(value: object) -> str:
    """以 repo 既有 custody 規則產生 deterministic JSON。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_hash(value: object) -> str:
    return SHA256_PREFIX + hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return SHA256_PREFIX + digest.hexdigest()


def validate_clock_manifest(
    manifest: Mapping[str, object],
    *,
    now: datetime,
    calendar_evidence: Mapping[str, object] | None = None,
    allow_elapsed_activation: bool = False,
) -> ProspectiveFormalClock:
    """驗證尚未啟動的 clock，所有時間與 calendar 證據都由呼叫端注入。

    ``now`` 必須是帶 timezone 的 datetime。預設只接受 activation 嚴格晚於
    Taipei 的當日；唯一例外是具名、同日且早於 PIT 邊界的 owner override。
    這個方法不接受已經過去的 active clock，避免 inspector 被誤用成
    retroactive credit 工具。
    """

    if not isinstance(manifest, Mapping):
        raise ProspectiveFormalClockError("clock manifest must be an object")
    unknown = set(manifest) - (_CLOCK_FIELDS | _OPTIONAL_CLOCK_FIELDS)
    missing = _CLOCK_FIELDS - set(manifest)
    if unknown:
        raise ProspectiveFormalClockError(
            "clock manifest contains unknown fields: " + ", ".join(sorted(unknown))
        )
    if missing:
        raise ProspectiveFormalClockError(
            "clock manifest missing fields: " + ", ".join(sorted(missing))
        )

    if manifest.get("schema_version") != PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION:
        raise ProspectiveFormalClockError("clock schema_version is invalid")
    if manifest.get("status") != PROSPECTIVE_FORMAL_CLOCK_STATUS:
        raise ProspectiveFormalClockError("clock status must be planned before activation")
    if manifest.get("mode") != PROSPECTIVE_FORMAL_CLOCK_MODE:
        raise ProspectiveFormalClockError("clock mode must be prospective_formal_simulation")
    if manifest.get("real_money") is not False:
        raise ProspectiveFormalClockError("real_money must be false")
    if manifest.get("broker_execution") is not False:
        raise ProspectiveFormalClockError("broker_execution must be false")
    if manifest.get("historical_backfill_claimed") is not False:
        raise ProspectiveFormalClockError("historical_backfill_claimed must be false")

    clock_id = _required_text(manifest.get("clock_id"), "clock_id")
    _required_text(manifest.get("owner_decision_id"), "owner_decision_id")
    _required_text(manifest.get("strategy_version"), "strategy_version")
    _required_text(manifest.get("policy_version"), "policy_version")
    if manifest.get("decision_timezone") != "Asia/Taipei":
        raise ProspectiveFormalClockError("decision_timezone must be Asia/Taipei")
    decision_time = _parse_local_time(manifest.get("decision_time"), "decision_time")
    if decision_time.tzinfo is not None:
        raise ProspectiveFormalClockError("decision_time must not contain a timezone")
    pit_decision_time = _parse_local_time(
        manifest.get("pit_decision_time", decision_time.isoformat(timespec="seconds")),
        "pit_decision_time",
    )
    if pit_decision_time > decision_time:
        raise ProspectiveFormalClockError(
            "pit_decision_time cannot be after decision_time"
        )

    owner_decision_timestamp = _parse_aware_datetime(
        manifest.get("owner_decision_timestamp"), "owner_decision_timestamp"
    )
    candidate_training_cutoff = _parse_aware_datetime(
        manifest.get("candidate_training_cutoff"), "candidate_training_cutoff"
    )
    now_aware = _parse_now(now)
    activation_day = _parse_date(
        manifest.get("activation_trading_day"), "activation_trading_day"
    )
    now_taipei_day = now_aware.astimezone(TAIPEI_TIMEZONE).date()
    timing_override = manifest.get("activation_timing_override")
    if timing_override is not None:
        _validate_activation_timing_override(
            timing_override,
            activation_day=activation_day,
            pit_decision_time=pit_decision_time,
            now=now_aware,
            allow_elapsed_activation=allow_elapsed_activation,
        )
    if allow_elapsed_activation:
        if activation_day > now_taipei_day:
            raise ProspectiveFormalClockError(
                "capture clock activation_trading_day cannot be in the future"
            )
    elif activation_day < now_taipei_day:
        raise ProspectiveFormalClockError(
            "activation_trading_day must be strictly after the current Taipei date"
        )
    elif activation_day == now_taipei_day:
        if timing_override is None:
            raise ProspectiveFormalClockError(
                "activation_trading_day must be strictly after the current Taipei date "
                "unless an explicit same-day pre-open owner override is present"
            )
        now_taipei = now_aware.astimezone(TAIPEI_TIMEZONE)
        if now_taipei.timetz().replace(tzinfo=None) >= pit_decision_time:
            raise ProspectiveFormalClockError(
                "same-day pre-open owner override must be published before "
                "pit_decision_time"
            )
    if activation_day <= owner_decision_timestamp.astimezone(TAIPEI_TIMEZONE).date():
        raise ProspectiveFormalClockError(
            "activation_trading_day must be after owner decision date"
        )
    if candidate_training_cutoff.astimezone(TAIPEI_TIMEZONE).date() >= activation_day:
        raise ProspectiveFormalClockError(
            "candidate_training_cutoff must be before activation_trading_day"
        )
    if owner_decision_timestamp > now_aware:
        raise ProspectiveFormalClockError(
            "owner_decision_timestamp cannot be in the future"
        )

    _validate_seed_state(manifest.get("seed_state"))
    _required_positive_int(
        manifest.get("virtual_notional_minor_units"),
        "virtual_notional_minor_units",
    )
    for field_name in (
        "policy_hash",
        "universe_hash",
        "source_policy_hash",
        "candidate_model_hash",
        "candidate_feature_manifest_hash",
        "calibration_policy_hash",
        "evaluation_policy_hash",
    ):
        _required_hash(manifest.get(field_name), field_name)

    embedded_calendar_evidence = manifest.get("activation_calendar_evidence")
    if calendar_evidence is not None:
        if canonical_json(calendar_evidence) != canonical_json(embedded_calendar_evidence):
            raise ProspectiveFormalClockError(
                "supplied calendar evidence does not match manifest evidence"
            )
    _validate_calendar_evidence(embedded_calendar_evidence, activation_day)

    supplied_manifest_hash = _required_hash(
        manifest.get("manifest_hash"), "manifest_hash"
    )
    identity = dict(manifest)
    identity.pop("manifest_hash", None)
    if payload_hash(identity) != supplied_manifest_hash:
        raise ProspectiveFormalClockError("clock manifest hash mismatch")

    return ProspectiveFormalClock(
        clock_id=clock_id,
        activation_trading_day=activation_day,
        owner_decision_timestamp=owner_decision_timestamp,
        candidate_training_cutoff=candidate_training_cutoff,
        manifest_hash=supplied_manifest_hash,
        payload=manifest,
    )


def load_clock_manifest(
    path: Path,
    *,
    now: datetime,
    calendar_evidence: Mapping[str, object] | None = None,
) -> ProspectiveFormalClock:
    """唯讀載入並驗證 JSON manifest；不建立 parent、不寫檔。"""

    resolved = path.expanduser().resolve()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProspectiveFormalClockError("clock manifest is missing") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProspectiveFormalClockError("clock manifest is unreadable") from exc
    if not isinstance(raw, dict):
        raise ProspectiveFormalClockError("clock manifest root must be an object")
    return validate_clock_manifest(
        raw,
        now=now,
        calendar_evidence=calendar_evidence,
    )


def load_clock_manifest_for_capture(
    path: Path,
    *,
    now: datetime,
    calendar_evidence: Mapping[str, object] | None = None,
) -> ProspectiveFormalClock:
    """唯讀載入已到 activation 邊界的 immutable clock。

    Activation 前的 ``load_clock_manifest`` 仍嚴格拒絕過去日期與未具名授權的
    同日日期；daily capture 必須使用這個明確入口，讓 clock 經過相同 hash、
    seed、calendar 與 simulation-only 驗證，只放寬「現在已經到達預先綁定的
    activation day」這一個時間邊界。它不改寫 clock status，也不建立 artifact。
    """

    resolved = path.expanduser().resolve()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProspectiveFormalClockError("clock manifest is missing") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProspectiveFormalClockError("clock manifest is unreadable") from exc
    if not isinstance(raw, dict):
        raise ProspectiveFormalClockError("clock manifest root must be an object")
    return validate_clock_manifest(
        raw,
        now=now,
        calendar_evidence=calendar_evidence,
        allow_elapsed_activation=True,
    )


def build_clock_manifest(
    payload_without_hash: Mapping[str, object],
) -> dict[str, object]:
    """只補 canonical manifest hash，不繞過 validator 或改變欄位。"""

    payload = dict(payload_without_hash)
    if "manifest_hash" in payload:
        raise ProspectiveFormalClockError(
            "build_clock_manifest expects payload without manifest_hash"
        )
    payload["manifest_hash"] = payload_hash(payload)
    return payload


def write_immutable_clock_manifest(
    output_path: Path,
    manifest: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存已驗證的 planned clock manifest。"""

    supplied = _required_hash(manifest.get("manifest_hash"), "manifest_hash")
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if payload_hash(body) != supplied:
        raise ProspectiveFormalClockError("clock manifest hash mismatch")
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveFormalClockError(
            "clock manifest output parent directory must already exist"
        )
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(manifest)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveFormalClockError(
            "clock manifest output already exists"
        ) from error
    return file_sha256(output)


def inspect_clock_manifest(
    path: Path,
    *,
    now: datetime,
    calendar_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """建立唯讀 readiness payload；任何錯誤皆轉成 blocked，不拋出給 CLI。"""

    resolved = path.expanduser().resolve()
    report: dict[str, object] = {
        "schema_version": "prospective-formal-clock-readiness.v1",
        "manifest_path": str(resolved),
        "status": "blocked",
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "read_only": True,
        "secret_values_emitted": False,
        "blockers": [],
    }
    blockers = report["blockers"]
    if not isinstance(blockers, list):  # pragma: no cover - local literal guard
        raise AssertionError("blockers must be a list")
    try:
        clock = load_clock_manifest(
            resolved,
            now=now,
            calendar_evidence=calendar_evidence,
        )
    except ProspectiveFormalClockError as exc:
        blockers.append(str(exc))
        if resolved.is_file():
            try:
                report["manifest_file_hash"] = file_sha256(resolved)
            except OSError:
                blockers.append("manifest_file_hash_unreadable")
        return report

    report.update(
        {
            "status": "ready_for_activation",
            "clock": clock.custody_payload(),
            "logical_manifest_hash": clock.manifest_hash,
            "manifest_file_hash": file_sha256(resolved),
        }
    )
    return report


def _validate_seed_state(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ProspectiveFormalClockError("seed_state must be an object")
    unknown = set(value) - _SEED_FIELDS
    missing = _SEED_FIELDS - set(value)
    if unknown:
        raise ProspectiveFormalClockError(
            "seed_state contains unknown fields: " + ", ".join(sorted(unknown))
        )
    if missing:
        raise ProspectiveFormalClockError(
            "seed_state missing fields: " + ", ".join(sorted(missing))
        )
    if value.get("kind") != "cash":
        raise ProspectiveFormalClockError("seed_state.kind must be cash")
    if value.get("cash_bp") != 10_000:
        raise ProspectiveFormalClockError("seed_state.cash_bp must be 10000")
    if value.get("position_count") != 0:
        raise ProspectiveFormalClockError("seed_state.position_count must be 0")
    expected = payload_hash(
        {
            "cash_bp": 10_000,
            "kind": "cash",
            "position_count": 0,
        }
    )
    if value.get("state_hash") != expected:
        raise ProspectiveFormalClockError("seed_state.state_hash mismatch")


def _validate_calendar_evidence(value: object, activation_day: date) -> None:
    if not isinstance(value, Mapping):
        raise ProspectiveFormalClockError(
            "activation calendar evidence is required"
        )
    unknown = set(value) - _CALENDAR_FIELDS
    missing = _CALENDAR_FIELDS - set(value)
    if unknown:
        raise ProspectiveFormalClockError(
            "calendar evidence contains unknown fields: "
            + ", ".join(sorted(unknown))
        )
    if missing:
        raise ProspectiveFormalClockError(
            "calendar evidence missing fields: " + ", ".join(sorted(missing))
        )
    if value.get("schema_version") != CALENDAR_EVIDENCE_SCHEMA_VERSION:
        raise ProspectiveFormalClockError("calendar evidence schema_version is invalid")
    if _parse_date(value.get("date"), "calendar evidence date") != activation_day:
        raise ProspectiveFormalClockError("calendar evidence date mismatch")
    if value.get("is_trading_day") is not True:
        raise ProspectiveFormalClockError("activation date is not an official trading day")
    reason = _required_text(value.get("reason_code"), "calendar evidence reason_code")
    if reason not in _ALLOWED_CALENDAR_REASONS:
        raise ProspectiveFormalClockError("calendar evidence reason_code is not official")
    _required_text(value.get("source"), "calendar evidence source")
    _required_hash(value.get("source_hash"), "calendar evidence source_hash")


def _validate_activation_timing_override(
    value: object,
    *,
    activation_day: date,
    pit_decision_time: time,
    now: datetime,
    allow_elapsed_activation: bool,
) -> None:
    if not isinstance(value, Mapping):
        raise ProspectiveFormalClockError(
            "activation_timing_override must be an object"
        )
    unknown = set(value) - _ACTIVATION_TIMING_OVERRIDE_FIELDS
    missing = _ACTIVATION_TIMING_OVERRIDE_FIELDS - set(value)
    if unknown:
        raise ProspectiveFormalClockError(
            "activation_timing_override contains unknown fields: "
            + ", ".join(sorted(unknown))
        )
    if missing:
        raise ProspectiveFormalClockError(
            "activation_timing_override missing fields: "
            + ", ".join(sorted(missing))
        )
    if value.get("schema_version") != SAME_DAY_PREOPEN_OWNER_OVERRIDE_SCHEMA_VERSION:
        raise ProspectiveFormalClockError(
            "activation_timing_override schema_version is invalid"
        )
    override_id = _required_text(value.get("owner_override_id"), "owner_override_id")
    reason_code = value.get("reason_code")
    if reason_code not in {
        SAME_DAY_PREOPEN_OWNER_OVERRIDE_REASON,
        SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON,
    }:
        raise ProspectiveFormalClockError(
            "activation_timing_override reason_code is invalid"
        )
    if reason_code == SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON and not override_id.startswith(
        "machine-rule-source:"
    ):
        raise ProspectiveFormalClockError(
            "machine activation timing override identity is invalid"
        )
    if (
        _parse_date(
            value.get("activation_trading_day"),
            "activation_timing_override activation_trading_day",
        )
        != activation_day
    ):
        raise ProspectiveFormalClockError(
            "activation_timing_override activation_trading_day mismatch"
        )
    if value.get("historical_backfill_allowed") is not False:
        raise ProspectiveFormalClockError(
            "activation_timing_override historical_backfill_allowed must be false"
        )
    if value.get("same_day_preopen_only") is not True:
        raise ProspectiveFormalClockError(
            "activation_timing_override same_day_preopen_only must be true"
        )
    override_timestamp = _parse_aware_datetime(
        value.get("owner_override_timestamp"), "owner_override_timestamp"
    )
    override_taipei = override_timestamp.astimezone(TAIPEI_TIMEZONE)
    if override_taipei.date() != activation_day:
        raise ProspectiveFormalClockError(
            "owner_override_timestamp must be on activation_trading_day"
        )
    if override_taipei.timetz().replace(tzinfo=None) >= pit_decision_time:
        raise ProspectiveFormalClockError(
            "owner_override_timestamp must be before pit_decision_time"
        )
    if override_timestamp > now:
        raise ProspectiveFormalClockError(
            "owner_override_timestamp cannot be in the future"
        )
    if not allow_elapsed_activation and now.astimezone(TAIPEI_TIMEZONE).date() != activation_day:
        raise ProspectiveFormalClockError(
            "same-day pre-open owner override is valid only on activation_trading_day"
        )


def _parse_now(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ProspectiveFormalClockError("now must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveFormalClockError("now must include timezone")
    return value


def _parse_aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveFormalClockError(f"{field_name} must be timezone-aware ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProspectiveFormalClockError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveFormalClockError(f"{field_name} must include timezone")
    return parsed


def _parse_local_time(value: object, field_name: str) -> time:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveFormalClockError(f"{field_name} must be HH:MM:SS")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ProspectiveFormalClockError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is not None or parsed.microsecond != 0:
        raise ProspectiveFormalClockError(f"{field_name} must be a local second-resolution time")
    if parsed.isoformat(timespec="seconds") != value:
        raise ProspectiveFormalClockError(f"{field_name} must use HH:MM:SS")
    return parsed


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveFormalClockError(f"{field_name} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProspectiveFormalClockError(f"{field_name} is invalid") from exc


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveFormalClockError(f"{field_name} must be non-empty text")
    return value.strip()


def _required_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProspectiveFormalClockError(f"{field_name} must be a positive integer")
    return value


def _required_hash(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ProspectiveFormalClockError(f"{field_name} must be sha256: plus 64 lowercase hex")
    return value
