"""建立下一個自然交易日的 Formal／Paper runtime candidate 設定。

這個 producer 是既有 9/9 候選設定之後的 rolling process boundary。它以
固定 cumulative portfolio clock 與官方 calendar anchor 為起點，從官方
bundle 的實際日期列選出下一個台北開市日，並以 date-scoped create-only JSON
保存 wrapper／consumer 的固定路徑。當 immutable bundle 已到 range 尾端時，
只會對明確的 successor link 執行版本化選取；沒有 successor 時，才以既有
官方 TWSE 年度／TPEx 月度 bounded capture 與 raw-custody persistence 建立
新的 candidate。它不掃描 latest、不修改舊 bundle、環境變數、scheduler、D
槽或任何 controlled path。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from data_module.formal_next_clock_preparation import _inspect_calendar_bundle
from data_module.formal_runtime_config import (
    FORMAL_RUNTIME_CONFIG_ENV,
    RUNTIME_CONFIG_ROOT_ENV,
    RUNTIME_ROLLING_SCHEMA_VERSION,
    load_runtime_environment_binding,
)
from data_module.prospective_formal_clock import (
    load_clock_manifest,
    load_clock_manifest_for_capture,
)


ROOT = Path(__file__).resolve().parents[1]
TAIPEI = ZoneInfo("Asia/Taipei")
SHA256_PREFIX = "sha256:"
RUNTIME_CONFIG_SCHEMA_VERSION = "formal-paper-9-9-candidate-runtime-config.v1"
ROLL_FORWARD_SCHEMA_VERSION = "formal-paper-runtime-roll-forward-producer.v1"
CALENDAR_BUNDLE_ENV = "FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE"
ROLL_FORWARD_ROOT_ENV = "FORMAL_DAILY_RUNTIME_ROLL_FORWARD_ROOT"
PUBLICATION_ROOT_ENV = "FORMAL_DAILY_PUBLICATION_ROOT"
MARKET_DB_ENV = "FORMAL_DAILY_MARKET_DB"
RULE_BASELINE_ENV = "FORMAL_DAILY_RULE_BASELINE_ROOT"
CALENDAR_CACHE_ENV = "FORMAL_DAILY_CALENDAR_CACHE_ROOT"
RULE_SOURCE_ROOT_ENV = "FORMAL_DAILY_RULE_SOURCE_ROOT"
PIT_ARCHIVE_ROOT_ENV = "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT"
PAPER_SNAPSHOT_ENV = "FORMAL_DAILY_PAPER_SNAPSHOT_DB"
PAPER_FILL_ENV = "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB"
PAPER_RECEIPT_ROOT_ENV = "FORMAL_DAILY_PAPER_RECEIPT_ROOT"
PORTFOLIO_CLOCK_ENV = "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST"
CALENDAR_SUCCESSOR_SCHEMA_VERSION = "official-calendar-bundle-successor.v1"
CALENDAR_RENEWAL_DAYS = 31
MAX_CALENDAR_SUCCESSOR_HOPS = 32
CALENDAR_CAPTURE_SCRIPT = ROOT / "scripts" / "capture_official_calendar_bundle.py"
CALENDAR_PERSIST_SCRIPT = ROOT / "scripts" / "persist_official_calendar_bundle.py"


class FormalRuntimeRollForwardError(ValueError):
    """rolling runtime 設定無法客觀建立。"""


def _payload_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return SHA256_PREFIX + hashlib.sha256(encoded).hexdigest()


def _bytes_hash(raw: bytes) -> str:
    return SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def _file_hash_and_size(path: Path) -> tuple[str, int]:
    """以 bounded chunks 計算 hash，並以同一個開啟的 file handle 綁 size。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        expected_size = os.fstat(stream.fileno()).st_size
        total = 0
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    if total != expected_size:
        raise FormalRuntimeRollForwardError(f"{path.name}_changed_during_read")
    return SHA256_PREFIX + digest.hexdigest(), total


def _file_hash(path: Path) -> str:
    return _file_hash_and_size(path)[0]


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalRuntimeRollForwardError(f"{field}_missing")
    return value.strip()


def _absolute_path(value: str | Path, field: str) -> Path:
    text = _required_text(str(value), field)
    return Path(text).expanduser().resolve()


def _environment_path(name: str, fallback: Path | None = None) -> Path | None:
    value = os.environ.get(name)
    if isinstance(value, str) and value.strip():
        return Path(value.strip()).expanduser().resolve()
    return fallback.resolve() if fallback is not None else None


def _file_record(path: Path, *, role: str, required: bool = True) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        if required:
            raise FormalRuntimeRollForwardError(f"{role}_missing:{resolved}")
        return {
            "path": str(resolved),
            "exists": False,
            "role": role,
            "read_only": True,
        }
    try:
        file_hash, size_bytes = _file_hash_and_size(resolved)
    except OSError as error:
        raise FormalRuntimeRollForwardError(
            f"{role}_unreadable:{type(error).__name__}"
        ) from error
    return {
        "path": str(resolved),
        "exists": True,
        "file_hash": file_hash,
        "size_bytes": size_bytes,
        "role": role,
        "read_only": True,
    }


def _read_object(path: Path, field: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormalRuntimeRollForwardError(
            f"{field}_unreadable:{type(error).__name__}"
        ) from error
    if not isinstance(value, Mapping):
        raise FormalRuntimeRollForwardError(f"{field}_must_be_object")
    return {str(key): item for key, item in value.items()}


def _parse_calendar_payload(payload: Mapping[str, object]) -> list[date]:
    if payload.get("schema_version") != "official-trading-calendar-bundle.v1":
        raise FormalRuntimeRollForwardError("official_calendar_bundle_schema_invalid")
    supplied_hash = payload.get("bundle_hash")
    body = dict(payload)
    body.pop("bundle_hash", None)
    if supplied_hash != _payload_hash(body):
        raise FormalRuntimeRollForwardError("official_calendar_bundle_hash_invalid")
    raw_days = payload.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        raise FormalRuntimeRollForwardError("official_calendar_bundle_days_missing")
    values: list[date] = []
    for row in raw_days:
        if not isinstance(row, Mapping):
            raise FormalRuntimeRollForwardError("official_calendar_bundle_day_invalid")
        raw_date = row.get("date")
        if not isinstance(raw_date, str):
            raise FormalRuntimeRollForwardError("official_calendar_bundle_day_date_missing")
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError as error:
            raise FormalRuntimeRollForwardError(
                "official_calendar_bundle_day_date_invalid"
            ) from error
        if parsed.isoformat() != raw_date:
            raise FormalRuntimeRollForwardError(
                "official_calendar_bundle_day_date_invalid"
            )
        values.append(parsed)
    if values != sorted(set(values)):
        raise FormalRuntimeRollForwardError("official_calendar_bundle_days_not_sorted_unique")
    return values


def _parse_calendar_dates(path: Path) -> list[date]:
    return _parse_calendar_payload(_read_object(path, "official_calendar_bundle"))


def _hash_token(value: object, field: str) -> str:
    text = _required_text(value, field)
    if len(text) != len(SHA256_PREFIX) + 64 or not text.startswith(SHA256_PREFIX):
        raise FormalRuntimeRollForwardError(f"{field}_invalid_sha256")
    try:
        int(text[len(SHA256_PREFIX) :], 16)
    except ValueError as error:
        raise FormalRuntimeRollForwardError(f"{field}_invalid_sha256") from error
    return text[len(SHA256_PREFIX) :]


def _calendar_bundle_identity(path: Path) -> dict[str, object]:
    """以同一份 bundle bytes 驗證 hash、日期範圍與來源 identity。"""

    resolved = _absolute_path(path, "official_calendar_bundle")
    try:
        raw = resolved.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormalRuntimeRollForwardError(
            f"official_calendar_bundle_unreadable:{type(error).__name__}"
        ) from error
    if not isinstance(value, Mapping):
        raise FormalRuntimeRollForwardError("official_calendar_bundle_must_be_object")
    payload = {str(key): item for key, item in value.items()}
    supplied_hash = payload.get("bundle_hash")
    body = dict(payload)
    body.pop("bundle_hash", None)
    if supplied_hash != _payload_hash(body):
        raise FormalRuntimeRollForwardError("official_calendar_bundle_hash_invalid")
    dates = _parse_calendar_payload(payload)
    raw_range = payload.get("range")
    if not isinstance(raw_range, Mapping):
        raise FormalRuntimeRollForwardError("official_calendar_bundle_range_missing")
    start_text = _required_text(raw_range.get("start_date"), "official_calendar_bundle.range.start_date")
    end_text = _required_text(raw_range.get("end_date"), "official_calendar_bundle.range.end_date")
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
    except ValueError as error:
        raise FormalRuntimeRollForwardError("official_calendar_bundle_range_invalid") from error
    if start.isoformat() != start_text or end.isoformat() != end_text or end < start:
        raise FormalRuntimeRollForwardError("official_calendar_bundle_range_invalid")
    if dates[0] != start or dates[-1] != end or len(dates) != (end - start).days + 1:
        raise FormalRuntimeRollForwardError("official_calendar_bundle_range_does_not_cover_days")
    return {
        "path": str(resolved),
        "file_hash": _bytes_hash(raw),
        "bundle_hash": str(supplied_hash),
        "payload": payload,
        "range_start": start,
        "range_end": end,
    }


def _calendar_identity_summary(identity: Mapping[str, object]) -> dict[str, object]:
    """Convert internal date objects to a compact JSON-safe custody summary."""

    start = identity.get("range_start")
    end = identity.get("range_end")
    if not isinstance(start, date) or not isinstance(end, date):
        raise FormalRuntimeRollForwardError("calendar_bundle_identity_range_invalid")
    return {
        "path": str(identity.get("path", "")),
        "file_hash": identity.get("file_hash"),
        "bundle_hash": identity.get("bundle_hash"),
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
    }


def _calendar_rotation_root(publication_root: Path) -> Path:
    """Return the fixed repository output root for exact successor links."""

    output_root = (ROOT / "output").resolve()
    resolved_publication = _absolute_path(publication_root, "publication_root")
    try:
        resolved_publication.relative_to(output_root)
    except ValueError as error:
        raise FormalRuntimeRollForwardError(
            "calendar_successor_publication_root_outside_repository_output"
        ) from error
    rotation_root = (resolved_publication / "calendar_candidate_archive" / "rotations").resolve()
    try:
        rotation_root.relative_to(output_root)
    except ValueError as error:
        raise FormalRuntimeRollForwardError(
            "calendar_successor_rotation_root_outside_repository_output"
        ) from error
    return rotation_root


def _calendar_successor_link_path(
    publication_root: Path,
    source_bundle_hash: object,
) -> Path:
    token = _hash_token(source_bundle_hash, "source_bundle_hash")
    return _calendar_rotation_root(publication_root) / f"{token}.json"


def _create_only_bytes(
    path: Path,
    encoded: bytes,
    *,
    mismatch_error: str,
) -> tuple[str, str]:
    """以 fsync + hard-link 建立 immutable successor metadata。"""

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise FormalRuntimeRollForwardError(
                f"{mismatch_error}:existing_unreadable:{type(error).__name__}"
            ) from error
        if existing == encoded:
            return "reused", _bytes_hash(existing)
        raise FormalRuntimeRollForwardError(mismatch_error)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = path.read_bytes()
            if existing == encoded:
                return "reused", _bytes_hash(existing)
            raise FormalRuntimeRollForwardError(mismatch_error)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return "created", _bytes_hash(encoded)


def _write_calendar_successor_link(
    *,
    publication_root: Path,
    source: Mapping[str, object],
    successor: Mapping[str, object],
    requested_start: date,
    requested_end: date,
    observed: datetime,
    capture_evidence: Mapping[str, object],
) -> tuple[Path, str, str]:
    source_start = source.get("range_start")
    source_end = source.get("range_end")
    successor_start = successor.get("range_start")
    successor_end = successor.get("range_end")
    if not isinstance(source_start, date) or not isinstance(source_end, date):
        raise FormalRuntimeRollForwardError("calendar_successor_link_source_range_invalid")
    if not isinstance(successor_start, date) or not isinstance(successor_end, date):
        raise FormalRuntimeRollForwardError("calendar_successor_link_range_invalid")
    link_path = _calendar_successor_link_path(publication_root, source.get("bundle_hash"))
    body: dict[str, object] = {
        "schema_version": CALENDAR_SUCCESSOR_SCHEMA_VERSION,
        "source_bundle": {
            "path": str(source["path"]),
            "file_hash": source["file_hash"],
            "bundle_hash": source["bundle_hash"],
            "range_start": source_start.isoformat(),
            "range_end": source_end.isoformat(),
        },
        "successor_bundle": {
            "path": str(successor["path"]),
            "file_hash": successor["file_hash"],
            "bundle_hash": successor["bundle_hash"],
            "range_start": successor_start.isoformat(),
            "range_end": successor_end.isoformat(),
        },
        "renewal_request": {
            "requested_start": requested_start.isoformat(),
            "requested_end": requested_end.isoformat(),
            "capture": "official TWSE annual + TPEx monthly bounded network responses",
            "capture_script": str(CALENDAR_CAPTURE_SCRIPT.resolve()),
            "persist_script": str(CALENDAR_PERSIST_SCRIPT.resolve()),
            "capture_status": dict(capture_evidence),
        },
        "observed_at": observed.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        "candidate_only": True,
        "formal_clock_created": False,
        "safety": {
            "read_only_sources": True,
            "writes_market_database": False,
            "writes_formal_controlled_paths": False,
            "writes_scheduler": False,
            "broker_order_allowed": False,
            "historical_backfill_claimed": False,
            "secret_values_emitted": False,
        },
    }
    payload = {**body, "link_hash": _payload_hash(body)}
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    status, file_hash = _create_only_bytes(
        link_path,
        encoded,
        mismatch_error="calendar_successor_link_existing_bytes_mismatch",
    )
    return link_path, status, file_hash


def _mapping_field(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise FormalRuntimeRollForwardError(f"{field}_must_be_object")
    return {str(key): item for key, item in value.items()}


def _read_calendar_successor_link(
    *,
    publication_root: Path,
    source: Mapping[str, object],
    link_path: Path,
) -> tuple[Path, dict[str, object]]:
    """Read one exact source-hash keyed link and verify both bundle files."""

    rotation_root = _calendar_rotation_root(publication_root)
    resolved_link = link_path.expanduser().resolve()
    try:
        resolved_link.relative_to(rotation_root)
    except ValueError as error:
        raise FormalRuntimeRollForwardError(
            "calendar_successor_link_outside_rotation_root"
        ) from error
    if link_path.is_symlink() or not link_path.is_file():
        raise FormalRuntimeRollForwardError(
            "calendar_successor_link_must_be_regular_file"
        )
    try:
        raw = resolved_link.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormalRuntimeRollForwardError(
            f"calendar_successor_link_unreadable:{type(error).__name__}"
        ) from error
    if not isinstance(value, Mapping):
        raise FormalRuntimeRollForwardError("calendar_successor_link_must_be_object")
    payload = {str(key): item for key, item in value.items()}
    if payload.get("schema_version") != CALENDAR_SUCCESSOR_SCHEMA_VERSION:
        raise FormalRuntimeRollForwardError("calendar_successor_link_schema_invalid")
    supplied_link_hash = payload.get("link_hash")
    body = dict(payload)
    body.pop("link_hash", None)
    if supplied_link_hash != _payload_hash(body):
        raise FormalRuntimeRollForwardError("calendar_successor_link_hash_invalid")
    if payload.get("candidate_only") is not True or payload.get("formal_clock_created") is not False:
        raise FormalRuntimeRollForwardError("calendar_successor_link_safety_invalid")
    source_record = _mapping_field(payload.get("source_bundle"), "calendar_successor_link.source_bundle")
    expected_source_path = str(source["path"])
    if source_record.get("path") != expected_source_path:
        raise FormalRuntimeRollForwardError("calendar_successor_link_source_path_mismatch")
    source_start = source.get("range_start")
    source_end = source.get("range_end")
    if not isinstance(source_start, date) or not isinstance(source_end, date):
        raise FormalRuntimeRollForwardError("calendar_successor_link_source_range_invalid")
    for field in ("file_hash", "bundle_hash", "range_start", "range_end"):
        if source_record.get(field) != source.get(field) and field not in {"range_start", "range_end"}:
            raise FormalRuntimeRollForwardError(f"calendar_successor_link_source_{field}_mismatch")
    if source_record.get("range_start") != source_start.isoformat():
        raise FormalRuntimeRollForwardError("calendar_successor_link_source_range_start_mismatch")
    if source_record.get("range_end") != source_end.isoformat():
        raise FormalRuntimeRollForwardError("calendar_successor_link_source_range_end_mismatch")
    successor_record = _mapping_field(
        payload.get("successor_bundle"),
        "calendar_successor_link.successor_bundle",
    )
    successor_raw_path = successor_record.get("path")
    if not isinstance(successor_raw_path, str) or not successor_raw_path.strip():
        raise FormalRuntimeRollForwardError("calendar_successor_link.successor_path_missing")
    successor_path = _absolute_path(
        successor_raw_path,
        "calendar_successor_link.successor_path",
    )
    publication = _absolute_path(publication_root, "publication_root")
    try:
        successor_path.relative_to(publication)
    except ValueError as error:
        raise FormalRuntimeRollForwardError(
            "calendar_successor_link_successor_outside_publication_root"
        ) from error
    successor = _calendar_bundle_identity(successor_path)
    for field in ("path", "file_hash", "bundle_hash"):
        if successor.get(field) != successor_record.get(field):
            raise FormalRuntimeRollForwardError(
                f"calendar_successor_link_successor_{field}_mismatch"
            )
    successor_start = successor.get("range_start")
    successor_end = successor.get("range_end")
    if not isinstance(successor_start, date) or not isinstance(successor_end, date):
        raise FormalRuntimeRollForwardError("calendar_successor_link_successor_range_invalid")
    if successor_start != source_end + timedelta(days=1):
        raise FormalRuntimeRollForwardError("calendar_successor_link_ranges_not_contiguous")
    if successor_record.get("range_start") != successor_start.isoformat():
        raise FormalRuntimeRollForwardError("calendar_successor_link_successor_range_start_mismatch")
    if successor_record.get("range_end") != successor_end.isoformat():
        raise FormalRuntimeRollForwardError("calendar_successor_link_successor_range_end_mismatch")
    return successor_path, {
        "status": "successor_link_reused",
        "link_path": str(resolved_link),
        "link_file_hash": _bytes_hash(raw),
        "link_hash": str(supplied_link_hash),
        "source_bundle": dict(source_record),
        "successor_bundle": dict(successor_record),
    }


def _last_json_object(value: str) -> dict[str, object] | None:
    for line in reversed(value.splitlines()):
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, Mapping):
            return {str(key): item for key, item in parsed.items()}
    return None


def _calendar_archive_root(
    publication_root: Path,
    *,
    activation_day: date,
    bundle_hash: object,
    raw_manifest_hash: object,
) -> Path:
    publication = _absolute_path(publication_root, "publication_root")
    bundle_token = _hash_token(bundle_hash, "successor_bundle_hash")
    manifest_token = _hash_token(raw_manifest_hash, "successor_raw_manifest_hash")
    archive_root = (
        publication
        / "calendar_candidate_archive"
        / activation_day.isoformat()
        / f"{bundle_token[:16]}-{manifest_token[:16]}"
    ).resolve()
    try:
        archive_root.relative_to(publication)
    except ValueError as error:
        raise FormalRuntimeRollForwardError(
            "calendar_successor_archive_outside_publication_root"
        ) from error
    return archive_root


def _renew_calendar_successor(
    source_path: Path,
    *,
    publication_root: Path,
    observed: datetime,
) -> tuple[Path, dict[str, object]]:
    """以既有官方雙來源 capture/persist CLI 建立一個 contiguous successor。"""

    source = _calendar_bundle_identity(source_path)
    source_end = source.get("range_end")
    if not isinstance(source_end, date):
        raise FormalRuntimeRollForwardError("calendar_successor_range_invalid")
    requested_start = source_end + timedelta(days=1)
    requested_end = requested_start + timedelta(days=CALENDAR_RENEWAL_DAYS - 1)
    if not observed.tzinfo or observed.utcoffset() is None:
        raise FormalRuntimeRollForwardError("observed_requires_timezone")

    temporary_root = Path(tempfile.mkdtemp(prefix="formal_calendar_renewal_"))
    candidate_path = temporary_root / (
        f"calendar_{requested_start.isoformat()}_{requested_end.isoformat()}.json"
    )
    raw_output = temporary_root / "raw"
    try:
        capture_command = [
            sys.executable,
            str(CALENDAR_CAPTURE_SCRIPT),
            "--start-date",
            requested_start.isoformat(),
            "--end-date",
            requested_end.isoformat(),
            "--confirm-network",
            "--output",
            str(candidate_path),
            "--raw-output-dir",
            str(raw_output),
        ]
        try:
            capture = subprocess.run(
                capture_command,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise FormalRuntimeRollForwardError("calendar_successor_capture_timeout") from error
        capture_payload = _last_json_object(capture.stdout or "")
        if capture.returncode != 0 or not isinstance(capture_payload, Mapping):
            raise FormalRuntimeRollForwardError(
                "calendar_successor_capture_failed:"
                f"{capture.returncode}:{(capture.stderr or '')[-240:]}"
            )
        if capture_payload.get("status") != "candidate_captured":
            raise FormalRuntimeRollForwardError("calendar_successor_capture_contract_invalid")
        if not candidate_path.is_file():
            raise FormalRuntimeRollForwardError("calendar_successor_capture_output_missing")

        candidate = _calendar_bundle_identity(candidate_path)
        selected_day, selected_evidence = select_next_official_trading_day(
            candidate_path,
            observed=observed,
        )
        if selected_day <= source_end:
            raise FormalRuntimeRollForwardError("calendar_successor_selected_day_not_after_source")
        candidate_payload = candidate["payload"]
        if not isinstance(candidate_payload, Mapping):
            raise FormalRuntimeRollForwardError("calendar_successor_payload_invalid")
        raw_evidence = _mapping_field(
            candidate_payload.get("raw_evidence"),
            "calendar_successor.raw_evidence",
        )
        raw_manifest_hash = _required_text(
            raw_evidence.get("manifest_hash"),
            "calendar_successor.raw_evidence.manifest_hash",
        )
        archive_root = _calendar_archive_root(
            publication_root,
            activation_day=selected_day,
            bundle_hash=candidate["bundle_hash"],
            raw_manifest_hash=raw_manifest_hash,
        )
        durable_bundle = archive_root / candidate_path.name
        persistence_status = "reused"
        if archive_root.exists():
            if not durable_bundle.is_file() or not (archive_root / "archive_manifest.json").is_file():
                raise FormalRuntimeRollForwardError("calendar_successor_archive_incomplete")
            durable = _calendar_bundle_identity(durable_bundle)
            if durable["file_hash"] != candidate["file_hash"] or durable["bundle_hash"] != candidate["bundle_hash"]:
                raise FormalRuntimeRollForwardError("calendar_successor_archive_bytes_mismatch")
        else:
            qa_output = (
                _calendar_rotation_root(publication_root)
                / "renewal_receipts"
                / f"{_hash_token(candidate['bundle_hash'], 'successor_bundle_hash')}.json"
            )
            persist_command = [
                sys.executable,
                str(CALENDAR_PERSIST_SCRIPT),
                "--bundle",
                str(candidate_path),
                "--activation-date",
                selected_day.isoformat(),
                "--publication-root",
                str(_absolute_path(publication_root, "publication_root")),
                "--qa-output",
                str(qa_output),
            ]
            try:
                persisted = subprocess.run(
                    persist_command,
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise FormalRuntimeRollForwardError("calendar_successor_persist_timeout") from error
            persist_payload = _last_json_object(persisted.stdout or "")
            if persisted.returncode != 0 or not isinstance(persist_payload, Mapping):
                raise FormalRuntimeRollForwardError(
                    "calendar_successor_persist_failed:"
                    f"{persisted.returncode}:{(persisted.stderr or '')[-240:]}"
                )
            if persist_payload.get("status") != "candidate_persisted":
                raise FormalRuntimeRollForwardError("calendar_successor_persist_contract_invalid")
            if not durable_bundle.is_file():
                raise FormalRuntimeRollForwardError("calendar_successor_durable_bundle_missing")
            durable = _calendar_bundle_identity(durable_bundle)
            if durable["file_hash"] != candidate["file_hash"] or durable["bundle_hash"] != candidate["bundle_hash"]:
                raise FormalRuntimeRollForwardError("calendar_successor_archive_bytes_mismatch")
            persistence_status = "created"

        durable_selected_day, durable_evidence = select_next_official_trading_day(
            durable_bundle,
            observed=observed,
        )
        if durable_selected_day != selected_day:
            raise FormalRuntimeRollForwardError("calendar_successor_durable_selection_mismatch")
        successor = _calendar_bundle_identity(durable_bundle)
        link_path, link_status, link_file_hash = _write_calendar_successor_link(
            publication_root=publication_root,
            source=source,
            successor=successor,
            requested_start=requested_start,
            requested_end=requested_end,
            observed=observed,
            capture_evidence={
                "status": "official_dual_source_candidate_persisted",
                "capture_returncode": int(capture.returncode),
                "capture_stdout_sha256": _bytes_hash((capture.stdout or "").encode("utf-8")),
                "persistence_status": persistence_status,
                "selected_day": selected_day.isoformat(),
                "candidate_bundle_hash": candidate["bundle_hash"],
                "candidate_file_hash": candidate["file_hash"],
                "selected_calendar_bundle": selected_evidence,
                "durable_calendar_bundle": durable_evidence,
            },
        )
        return durable_bundle, {
            "status": "successor_created" if link_status == "created" else "successor_reused",
            "link_path": str(link_path.resolve()),
            "link_file_hash": link_file_hash,
            "source_bundle": _calendar_identity_summary(source),
            "successor_bundle": _calendar_identity_summary(successor),
            "requested_start": requested_start.isoformat(),
            "requested_end": requested_end.isoformat(),
            "persistence_status": persistence_status,
            "capture_mode": "official_dual_source_bounded_network",
            "candidate_only": True,
            "formal_clock_created": False,
        }
    finally:
        # Candidate/raw bytes are copied into the durable archive before this
        # cleanup; no TEMP path is ever used as the runtime source.
        for child in sorted(temporary_root.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                try:
                    child.unlink()
                except FileNotFoundError:
                    pass
            elif child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        try:
            temporary_root.rmdir()
        except OSError:
            pass


def _resolve_calendar_bundle_for_observed(
    calendar_anchor: Path,
    *,
    publication_root: Path,
    observed: datetime,
) -> tuple[Path, dict[str, object]]:
    """Follow exact hash-keyed successors, renewing only at a range boundary."""

    current_path = _absolute_path(calendar_anchor, "calendar_anchor")
    chain: list[dict[str, object]] = []
    seen: set[str] = set()
    for _ in range(MAX_CALENDAR_SUCCESSOR_HOPS):
        current = _calendar_bundle_identity(current_path)
        bundle_hash = str(current["bundle_hash"])
        if bundle_hash in seen:
            raise FormalRuntimeRollForwardError("calendar_successor_cycle_detected")
        seen.add(bundle_hash)
        try:
            select_next_official_trading_day(current_path, observed=observed)
            return current_path, {
                "status": "anchor_or_successor_selected",
                "anchor_path": str(_absolute_path(calendar_anchor, "calendar_anchor")),
                "selected_path": str(current_path),
                "chain": chain,
                "renewed": bool(chain and chain[-1].get("status") == "successor_created"),
            }
        except FormalRuntimeRollForwardError as error:
            if not str(error).startswith("no_next_official_trading_day_in_calendar_bundle"):
                raise
        link_path = _calendar_successor_link_path(publication_root, bundle_hash)
        if link_path.exists():
            successor_path, link_evidence = _read_calendar_successor_link(
                publication_root=publication_root,
                source=current,
                link_path=link_path,
            )
            chain.append(link_evidence)
            current_path = successor_path
            continue
        successor_path, renewal_evidence = _renew_calendar_successor(
            current_path,
            publication_root=publication_root,
            observed=observed,
        )
        chain.append(renewal_evidence)
        current_path = successor_path
    raise FormalRuntimeRollForwardError("calendar_successor_hop_limit_exceeded")


def select_next_official_trading_day(
    calendar_bundle: Path,
    *,
    observed: datetime,
) -> tuple[date, dict[str, object]]:
    """從已驗證 bundle 選嚴格晚於當日的第一個 TWSE/TPEx 開市日。"""

    if observed.tzinfo is None or observed.utcoffset() is None:
        raise FormalRuntimeRollForwardError("observed_requires_timezone")
    observed_utc = observed.astimezone(timezone.utc)
    observed_taipei = observed_utc.astimezone(TAIPEI)
    path = _absolute_path(calendar_bundle, "official_calendar_bundle")
    dates = _parse_calendar_dates(path)
    failures: list[str] = []
    explicit_closed_day_blockers = {
        "official_calendar_bundle_twse_activation_day_not_open",
        "official_calendar_bundle_tpex_activation_day_not_open",
    }
    for candidate in dates:
        if candidate <= observed_taipei.date():
            continue
        projection, blockers = _inspect_calendar_bundle(
            path,
            activation_date=candidate,
        )
        if blockers:
            unknown_blockers = [
                blocker
                for blocker in blockers
                if blocker not in explicit_closed_day_blockers
            ]
            if unknown_blockers:
                raise FormalRuntimeRollForwardError(
                    "official_calendar_candidate_invalid:"
                    f"{candidate.isoformat()}:{','.join(unknown_blockers[:3])}"
                )
            failures.append(f"{candidate.isoformat()}:{','.join(blockers[:3])}")
            continue
        if projection.get("twse_open") is True and projection.get("tpex_open") is True:
            return candidate, {
                "bundle": _file_record(path, role="official calendar bundle"),
                "bundle_hash": projection.get("bundle_hash"),
                "activation_trading_day": candidate.isoformat(),
                "twse_open": True,
                "tpex_open": True,
                "raw_custody": projection.get("raw_custody"),
                "selection_rule": "first official TWSE and TPEx open date strictly after observed Taipei date",
            }
    detail = ";".join(failures[:3])
    raise FormalRuntimeRollForwardError(
        "no_next_official_trading_day_in_calendar_bundle"
        + (f":{detail}" if detail else "")
    )


def _load_fixed_portfolio_clock(path: Path, *, observed: datetime) -> Any:
    resolved = _absolute_path(path, "portfolio_clock_manifest")
    if not resolved.is_file():
        raise FormalRuntimeRollForwardError(
            f"portfolio_clock_manifest_missing:{resolved}"
        )
    try:
        try:
            clock = load_clock_manifest_for_capture(resolved, now=observed)
        except Exception:
            clock = load_clock_manifest(resolved, now=observed)
    except Exception as error:  # noqa: BLE001 - one bounded producer blocker
        raise FormalRuntimeRollForwardError(
            f"portfolio_clock_manifest_invalid:{type(error).__name__}:{error}"
        ) from error
    for field in ("real_money", "broker_execution", "historical_backfill_claimed"):
        if clock.payload.get(field) is not False:
            raise FormalRuntimeRollForwardError(
                f"portfolio_clock_{field}_must_be_false"
            )
    return clock


def _preflight_rule_dependencies(
    *,
    baseline_root: Path,
    market_db: Path,
    calendar_cache_root: Path,
    target_day: date,
    observed: datetime,
) -> dict[str, object]:
    """沿用現有 Rule producer 的 finder 驗證真正的 parent／calendar 來源。"""

    if not baseline_root.is_dir():
        raise FormalRuntimeRollForwardError(
            f"rule_baseline_root_missing:{baseline_root}"
        )
    if not market_db.is_file():
        raise FormalRuntimeRollForwardError(f"market_db_missing:{market_db}")
    if not calendar_cache_root.is_dir():
        raise FormalRuntimeRollForwardError(
            f"calendar_cache_root_missing:{calendar_cache_root}"
        )
    try:
        # This is the same source resolver the daily Rule producer invokes;
        # recording its selected children prevents a config from claiming a
        # generic baseline root without proving an eligible parent exists.
        from data_module.formal_rule_source_producer import (
            _find_baseline_bundle,
            _official_calendar_evidence,
        )

        (
            parent_clock_path,
            parent_owner_path,
            parent_symbols_path,
            parent_clock,
            _parent_owner,
            parent_symbols,
        ) = _find_baseline_bundle(
            baseline_root,
            observed_utc=observed,
            target_day=target_day,
        )
        calendar_evidence = _official_calendar_evidence(
            market_db=market_db,
            calendar_cache_root=calendar_cache_root,
            target_day=target_day,
        )
    except Exception as error:  # noqa: BLE001 - producer dependency is fail closed
        raise FormalRuntimeRollForwardError(
            "rule_dependency_preflight_failed:"
            f"{type(error).__name__}:{str(error).splitlines()[0][:220]}"
        ) from error
    return {
        "status": "verified",
        "resolver": "data_module.formal_rule_source_producer._find_baseline_bundle",
        "calendar_resolver": "data_module.formal_rule_source_producer._official_calendar_evidence",
        "parent_clock": {
            **_file_record(parent_clock_path, role="verified Rule parent clock"),
            "clock_id": parent_clock.clock_id,
            "manifest_hash": parent_clock.manifest_hash,
            "activation_trading_day": parent_clock.activation_trading_day.isoformat(),
        },
        "parent_owner_acceptance": _file_record(
            parent_owner_path,
            role="verified Rule parent owner acceptance",
        ),
        "parent_universe_symbols": {
            **_file_record(parent_symbols_path, role="verified Rule parent universe symbols"),
            "symbol_count": len(parent_symbols),
        },
        "market_db": _file_record(market_db, role="Rule dependency market source"),
        "calendar_cache_root": {
            "path": str(calendar_cache_root),
            "exists": True,
            "read_only": True,
        },
        "calendar_evidence": calendar_evidence,
        "target_day": target_day.isoformat(),
    }


def _command(path: Path) -> str:
    return f'cmd.exe /d /c "{path.resolve()}"'


def _wrapper_contract(
    *,
    config_path: Path,
    calendar_bundle: Path,
    roll_forward_root: Path,
    portfolio_clock_manifest: Path,
    market_db: Path,
    baseline_root: Path,
    calendar_cache: Path,
    publication_root: Path,
    rule_source_root: Path,
    pit_archive_root: Path,
    paper_snapshot: Path,
    paper_fill: Path,
) -> dict[str, object]:
    """建立現有 wrappers 真正讀取的 exact environment contract。"""

    scripts = ROOT / "scripts" / "scheduled"
    runtime = str(config_path.resolve())
    base = {
        "BALDR_PYTHON": str((ROOT / ".venv" / "Scripts" / "python.exe").resolve()),
        "DATA_ROOT": str(Path(os.environ.get("DATA_ROOT", r"D:\Min\Python\Project\FA_Data")).expanduser().resolve()),
        "FORMAL_DAILY_RUNTIME_CONFIG": runtime,
        RUNTIME_CONFIG_ROOT_ENV: str(roll_forward_root.resolve()),
        CALENDAR_BUNDLE_ENV: str(calendar_bundle.resolve()),
        ROLL_FORWARD_ROOT_ENV: str(roll_forward_root.resolve()),
        "FORMAL_DAILY_MARKET_DB": str(market_db.resolve()),
        "FORMAL_DAILY_RULE_BASELINE_ROOT": str(baseline_root.resolve()),
        "FORMAL_DAILY_CALENDAR_CACHE_ROOT": str(calendar_cache.resolve()),
        "FORMAL_DAILY_PUBLICATION_ROOT": str(publication_root.resolve()),
        "FORMAL_DAILY_RULE_SOURCE_ROOT": str(rule_source_root.resolve()),
        "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT": str(pit_archive_root.resolve()),
        "FORMAL_DAILY_PAPER_SNAPSHOT_DB": str(paper_snapshot.resolve()),
        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB": str(paper_fill.resolve()),
        "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST": str(
            portfolio_clock_manifest.resolve()
        ),
    }
    return {
        "rule_source_wrapper": {
            "entrypoint": str((scripts / "run_formal_rule_source_preopen.cmd").resolve()),
            "command": _command(scripts / "run_formal_rule_source_preopen.cmd"),
            "environment": {
                key: base[key]
                for key in (
                    "BALDR_PYTHON",
                    "DATA_ROOT",
                    "FORMAL_DAILY_RUNTIME_CONFIG",
                    RUNTIME_CONFIG_ROOT_ENV,
                    "FORMAL_DAILY_MARKET_DB",
                    "FORMAL_DAILY_RULE_BASELINE_ROOT",
                    "FORMAL_DAILY_CALENDAR_CACHE_ROOT",
                    "FORMAL_DAILY_RULE_SOURCE_ROOT",
                )
            },
            "required_environment": [
                "FORMAL_DAILY_RUNTIME_CONFIG",
                RUNTIME_CONFIG_ROOT_ENV,
                "FORMAL_DAILY_MARKET_DB",
                "FORMAL_DAILY_RULE_BASELINE_ROOT",
                "FORMAL_DAILY_CALENDAR_CACHE_ROOT",
                "FORMAL_DAILY_RULE_SOURCE_ROOT",
            ],
            "source_resolution": {
                "mode": "explicit_date_scoped_runtime_and_exact_predecessor_status",
                "output_root": str(rule_source_root.resolve()),
                "status_path": str(
                    (rule_source_root / "scheduler" / "rule_source_latest_status.json").resolve()
                ),
                "explicit_date_or_now_override": False,
                "fixture_mode": False,
            },
        },
        "pit_preopen_wrapper": {
            "entrypoint": str((scripts / "run_pit_sector_membership_preopen_capture.cmd").resolve()),
            "command": _command(scripts / "run_pit_sector_membership_preopen_capture.cmd"),
            "scheduler_task": "baldr-pit-sector-membership-preopen-capture-daily",
            "scheduler_owner": "v4_schedule_ops",
            "environment": {
                key: base[key]
                for key in (
                    "BALDR_PYTHON",
                    "FORMAL_DAILY_RUNTIME_CONFIG",
                    RUNTIME_CONFIG_ROOT_ENV,
                    "FORMAL_DAILY_PUBLICATION_ROOT",
                )
            },
            "required_environment": [
                "FORMAL_DAILY_RUNTIME_CONFIG",
                RUNTIME_CONFIG_ROOT_ENV,
                "FORMAL_DAILY_PUBLICATION_ROOT",
            ],
            "natural_window_taipei": "07:00-08:30",
            "calls_rule_wrapper_first": True,
        },
        "pit_sidecar_wrapper": {
            "entrypoint": str((scripts / "run_formal_pit_sidecar_postcutoff.cmd").resolve()),
            "command": _command(scripts / "run_formal_pit_sidecar_postcutoff.cmd"),
            "scheduler_task": "baldr-formal-pit-sidecar-postcutoff-daily",
            "scheduler_owner": "v4_schedule_ops",
            "environment": {
                key: base[key]
                for key in (
                    "BALDR_PYTHON",
                    "FORMAL_DAILY_RUNTIME_CONFIG",
                    RUNTIME_CONFIG_ROOT_ENV,
                    "FORMAL_DAILY_PUBLICATION_ROOT",
                    "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT",
                )
            },
            "required_environment": [
                "FORMAL_DAILY_RUNTIME_CONFIG",
                RUNTIME_CONFIG_ROOT_ENV,
                "FORMAL_DAILY_PUBLICATION_ROOT",
                "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT",
            ],
            "natural_window_taipei": "09:00 or later; archive read only",
        },
        "formal_input_wrapper": {
            "entrypoint": str((scripts / "run_formal_input_producer_daily.cmd").resolve()),
            "command": _command(scripts / "run_formal_input_producer_daily.cmd"),
            "scheduler_task": "baldr-formal-input-producer-daily",
            "scheduler_owner": "v4_schedule_ops",
            "configured_local_time": "21:25",
            "configured_timezone": "America/Los_Angeles",
            "taipei_mapping": "12:25 PDT / 13:25 PST",
            "environment": dict(base),
            "required_environment": [
                "FORMAL_DAILY_RUNTIME_CONFIG",
                RUNTIME_CONFIG_ROOT_ENV,
                "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
                "DATA_ROOT",
                "FORMAL_DAILY_MARKET_DB",
                "FORMAL_DAILY_PUBLICATION_ROOT",
                "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT",
                "FORMAL_DAILY_RULE_SOURCE_ROOT",
                "FORMAL_DAILY_PAPER_SNAPSHOT_DB",
                "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
            ],
            "required_rule_source_environment": {
                "FORMAL_DAILY_CLOCK_MANIFEST": "omitted; exact predecessor status binds it",
                "FORMAL_DAILY_UNIVERSE_SYMBOLS": "omitted; exact predecessor status binds it",
                "FORMAL_DAILY_OWNER_ACCEPTANCE": "omitted; exact predecessor status binds it",
            },
            "legacy_BALDR_ML_paths": "omitted when FORMAL_DAILY_RULE_SOURCE_ROOT is configured",
            "status_path": str((publication_root / "scheduler" / "latest_status.json").resolve()),
            "rule_source_predecessor": {
                "task": "baldr-pit-sector-membership-preopen-capture-daily",
                "source_root": str(rule_source_root.resolve()),
                "required_status_path": str(
                    (rule_source_root / "scheduler" / "rule_source_latest_status.json").resolve()
                ),
                "same_taipei_natural_day": True,
                "prepublish_window_taipei": "07:00-08:30",
                "daily_rule_producer_window_taipei": "09:00-13:30",
                "scheduler_owner": "v4_schedule_ops",
                "required_exit_code": 0,
                "accepted_statuses": [
                    "rule_source_bundle_created",
                    "rule_source_bundle_reused",
                ],
                "prepublish_role": "machine source/clock prepublication only; no Rule decision or Formal credit",
                "postopen_requires_existing_bundle": True,
                "new_same_day_clock_after_pit_cutoff": False,
                "daily_rule_binding": "formal_daily_input_producer consumes exact predecessor bundle source rows; daily lineage remains separate from fixed cumulative portfolio clock",
            },
        },
        "paper_eod_wrapper": {
            "entrypoint": str((scripts / "run_paper_execution_daily_isolated.cmd").resolve()),
            "command": _command(scripts / "run_paper_execution_daily_isolated.cmd"),
            "scheduler_task": "baldr-paper-execution-eod-replay-daily",
            "scheduler_owner": "v4_schedule_ops",
            "configured_local_time": "06:00",
            "configured_timezone": "America/Los_Angeles",
            "taipei_mapping": "21:00 PDT / 22:00 PST",
            "environment": {
                FORMAL_RUNTIME_CONFIG_ENV: runtime,
                RUNTIME_CONFIG_ROOT_ENV: base[RUNTIME_CONFIG_ROOT_ENV],
                CALENDAR_BUNDLE_ENV: base[CALENDAR_BUNDLE_ENV],
                PORTFOLIO_CLOCK_ENV: base[PORTFOLIO_CLOCK_ENV],
                ROLL_FORWARD_ROOT_ENV: base[ROLL_FORWARD_ROOT_ENV],
            },
            "required_environment": [
                FORMAL_RUNTIME_CONFIG_ENV,
                RUNTIME_CONFIG_ROOT_ENV,
                CALENDAR_BUNDLE_ENV,
                PORTFOLIO_CLOCK_ENV,
                ROLL_FORWARD_ROOT_ENV,
            ],
            "runtime_roll_forward": {
                "entrypoint": str(
                    (scripts / "run_formal_runtime_roll_forward.py").resolve()
                ),
                "source_pins": [CALENDAR_BUNDLE_ENV, PORTFOLIO_CLOCK_ENV],
                "output_root_environment": ROLL_FORWARD_ROOT_ENV,
                "invoked_by": "paper_execution_retry_runner after EOD retry boundary",
                "candidate_only": True,
            },
            "source_guard": [
                "frozen pending decision identity",
                "same natural data date and version",
                "real fill receipt required",
                "no snapshot-derived or synthetic fill",
            ],
        },
    }


def _rolling_contract(
    *,
    output_root: Path,
    publication_root: Path,
    rule_source_root: Path,
    portfolio_clock: Path,
    paper_receipt_root: Path,
) -> dict[str, object]:
    day = "<YYYY-MM-DD>"
    publication = str(publication_root.resolve())
    return {
        "schema_version": RUNTIME_ROLLING_SCHEMA_VERSION,
        "natural_date_timezone": "Asia/Taipei",
        "activation_date_source": "observed Taipei date plus exact official calendar bundle or hash-keyed successor link; no weekday inference and no --date override",
        "same_candidate_reuse_prohibited": True,
        "requires_date_scoped_config": True,
        "config_path_pattern": str((output_root / f"{day}.json").resolve()),
        "date_scoped_fields": [
            "activation_trading_day",
            "source_evidence",
            "publication_paths",
            "wrapper_contract",
            "runtime_config_binding",
        ],
        "path_patterns": {
            "runtime_config": str((output_root / f"{day}.json").resolve()),
            "pit_archive_manifest": publication + f"/pit_candidate_archive/{day}/<capture_hash>-<receipt_hash>/archive_manifest.json",
            "rule_source_bundle_manifest": publication + "/rule_source/clock-<YYYYMMDD>-machine-v2-or-v3-<source_window_hash_12>-<parent_clock_hash_12>/clock/manifest.json",
            "rule_history_manifest": publication + f"/rule_history/{day}/manifest.json",
            "portfolio_clock_manifest": str(portfolio_clock.resolve()),
            "formal_pit_sidecar": publication + f"/pit_sector_membership_formal/{day}/sidecar.json",
            "paper_eod_receipt_root": str((paper_receipt_root / day).resolve()),
            "causal_ledger_manifest": publication + f"/causal_ledger/{day}-<snapshot_hash_12>-<fill_hash_12>/manifest.json",
        },
        "consumer_sequence": [
            "official_calendar -> fixed portfolio clock validation",
            "PIT preopen capture -> machine Rule source prepublication",
            "formal PIT sidecar reads exact preopen archive",
            "Paper EOD replay reads frozen pending queue and real fill receipt",
            "daily Rule producer consumes exact captured source window",
            "formal input consumes exact Rule/PIT/Paper paths",
            "causal ledger closes only [snapshot_date, next_snapshot_date) intervals",
        ],
        "late_replay_policy": {
            "preserve_recorded_at": True,
            "historical_credit": False,
            "no_elapsed_credit": True,
            "same_day_pending_retry": "only identical decision/source identity and same Taipei natural date",
            "missed_session": "explicit pending_execution_session_missed; do not replace with next recommendation",
        },
    }


def build_rolling_runtime_config(
    *,
    observed: datetime,
    activation_trading_day: date,
    calendar_bundle: Path,
    portfolio_clock_manifest: Path,
    output_path: Path,
    publication_root: Path,
    market_db: Path,
    rule_baseline_root: Path,
    calendar_cache_root: Path,
    rule_source_root: Path,
    pit_archive_root: Path,
    paper_snapshot_db: Path,
    paper_fill_db: Path,
    paper_receipt_root: Path,
    calendar_environment_bundle: Path | None = None,
    calendar_resolution: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """建立一份 date-scoped config；所有來源路徑由 caller 明確傳入。"""

    if observed.tzinfo is None or observed.utcoffset() is None:
        raise FormalRuntimeRollForwardError("observed_requires_timezone")
    observed_utc = observed.astimezone(timezone.utc)
    observed_taipei = observed_utc.astimezone(TAIPEI)
    if activation_trading_day <= observed_taipei.date():
        raise FormalRuntimeRollForwardError("activation_trading_day_must_be_after_observed_date")
    selected_day, calendar_evidence = select_next_official_trading_day(
        calendar_bundle,
        observed=observed_utc,
    )
    if selected_day != activation_trading_day:
        raise FormalRuntimeRollForwardError(
            "activation_trading_day_does_not_match_calendar_selection"
        )
    clock_path = _absolute_path(
        portfolio_clock_manifest,
        "portfolio_clock_manifest",
    )
    clock = _load_fixed_portfolio_clock(clock_path, observed=observed_utc)
    if clock.activation_trading_day > activation_trading_day:
        raise FormalRuntimeRollForwardError("portfolio_clock_starts_after_activation_day")
    output = _absolute_path(output_path, "runtime_config_output")
    publication = _absolute_path(publication_root, "publication_root")
    market = _absolute_path(market_db, "market_db")
    baseline = _absolute_path(rule_baseline_root, "rule_baseline_root")
    if not baseline.is_dir():
        raise FormalRuntimeRollForwardError(
            f"rule_baseline_root_missing:{baseline}"
        )
    calendar_cache = _absolute_path(calendar_cache_root, "calendar_cache_root")
    rule_root = _absolute_path(rule_source_root, "rule_source_root")
    pit_root = _absolute_path(pit_archive_root, "pit_archive_root")
    snapshot = _absolute_path(paper_snapshot_db, "paper_snapshot_db")
    fill = _absolute_path(paper_fill_db, "paper_fill_db")
    receipt_root = _absolute_path(paper_receipt_root, "paper_receipt_root")
    rule_dependency_preflight = _preflight_rule_dependencies(
        baseline_root=baseline,
        market_db=market,
        calendar_cache_root=calendar_cache,
        target_day=activation_trading_day,
        observed=observed_utc,
    )
    date_text = activation_trading_day.isoformat()
    date_token = activation_trading_day.strftime("%Y%m%d")
    publication_paths = {
        "portfolio_clock_manifest": str(clock_path),
        "rule_source_root": str(rule_root),
        "rule_source_status": str(rule_root / "scheduler" / "rule_source_latest_status.json"),
        "rule_history_manifest": str(publication / "rule_history" / date_text / "manifest.json"),
        "pit_archive_root": str(pit_root),
        "pit_sidecar": str(publication / "pit_sector_membership_formal" / date_text / "sidecar.json"),
        "pit_receipt": str(publication / "pit_sector_membership_formal" / date_text / "receipt.json"),
        "paper_snapshot": str(snapshot),
        "paper_fill_ledger": str(fill),
        "paper_eod_receipt_root": str(receipt_root / date_text),
        "causal_ledger_run_pattern": str(publication / "causal_ledger" / f"{date_text}-<snapshot_hash_12>-<fill_hash_12>"),
        "common_identity_manifest": str(ROOT / "output" / "v4_next_formal" / f"formal_identity_{date_token}.json"),
        "calendar_bundle": str(_absolute_path(calendar_bundle, "official_calendar_bundle")),
    }
    source_evidence: dict[str, object] = {
        "official_calendar": calendar_evidence,
        "market_db": _file_record(market, role="D market source"),
        "fixed_portfolio_clock": {
            **_file_record(clock_path, role="fixed cumulative portfolio clock"),
            "clock_id": clock.clock_id,
            "manifest_hash": clock.manifest_hash,
            "activation_trading_day": clock.activation_trading_day.isoformat(),
            "scope": "cumulative_paper_portfolio_state",
            "reset_on_each_natural_day": False,
            "daily_rule_clock_is_separate": True,
        },
        "rule_dependency_preflight": rule_dependency_preflight,
        "paper_snapshot": _file_record(snapshot, role="Paper snapshot source", required=False),
        "paper_fill": _file_record(fill, role="Paper fill source", required=False),
    }
    if calendar_resolution is not None:
        source_evidence["calendar_resolution"] = {
            str(key): value for key, value in calendar_resolution.items()
        }
    config_output = output
    wrapper_contract = _wrapper_contract(
        config_path=config_output,
        calendar_bundle=_absolute_path(
            calendar_environment_bundle or calendar_bundle,
            "calendar_environment_bundle",
        ),
        roll_forward_root=output.parent,
        portfolio_clock_manifest=clock_path,
        market_db=market,
        baseline_root=baseline,
        calendar_cache=calendar_cache,
        publication_root=publication,
        rule_source_root=rule_root,
        pit_archive_root=pit_root,
        paper_snapshot=snapshot,
        paper_fill=fill,
    )
    body: dict[str, object] = {
        "schema_version": RUNTIME_CONFIG_SCHEMA_VERSION,
        "status": "candidate_ready_for_root_review",
        "generated_at": observed_utc.isoformat(timespec="microseconds"),
        "activation_trading_day": date_text,
        "rolling_producer": {
            "schema_version": ROLL_FORWARD_SCHEMA_VERSION,
            "observed_taipei_date": observed_taipei.date().isoformat(),
            "selected_by": "official_calendar_bundle",
            "selected_calendar_day": date_text,
            "date_scoped_output": str(config_output),
        },
        "runtime_trigger": {
            "task_name": "baldr-paper-execution-eod-replay-daily",
            "scheduler_owner": "v4_schedule_ops",
            "configured_local_time": "06:00 plus bounded Paper retry",
            "configured_timezone": "America/Los_Angeles",
            "taipei_mapping": "21:00 PDT / 22:00 PST; roll-forward runs after bounded retry",
            "action": str(
                (ROOT / "scripts" / "scheduled" / "run_paper_execution_daily_isolated.cmd")
                .resolve()
            ),
            "roll_forward_entrypoint": str(
                (ROOT / "scripts" / "scheduled" / "run_formal_runtime_roll_forward.py")
                .resolve()
            ),
            "trigger_mode": "existing_paper_execution_retry_runner_after_retry_boundary",
            "purpose": "create the next date-scoped candidate after the Paper EOD window; do not apply it",
            "requires_exact_calendar_and_portfolio_clock_environment": True,
            "does_not_wait_for_paper_fill": True,
        },
        "ownership": {
            "formal_paper_owner": [
                "formal_rule_source_producer and captured source-window consumer",
                "formal_daily_input_producer and common identity handoff",
                "Paper/fill/causal ledger consumer",
            ],
            "scheduler_owner": "v4_schedule_ops",
            "ml_owner": "separate ML lane; this Rule-only config never certifies ML identity",
        },
        "runtime_attestation": {
            "source": "rolling producer runtime plus exact file hashes",
            "python_path": str(Path(sys.executable).expanduser().resolve()),
            "python_file_hash": _file_record(
                Path(sys.executable), role="python runtime"
            ).get("file_hash"),
            "observed_clock_is_runtime_only": True,
            "secret_values_emitted": False,
        },
        "source_evidence": source_evidence,
        "runtime_config_binding": {
            "environment_variable": FORMAL_RUNTIME_CONFIG_ENV,
            "date_scoped_root_environment_variable": RUNTIME_CONFIG_ROOT_ENV,
            "path": str(config_output),
            "file_hash_semantics": "computed from exact bytes at wrapper load; omitted here to avoid self-hash recursion",
            "automatic_date_binding": "one-time root pin plus exact Asia/Taipei YYYY-MM-DD filename; no latest scan",
            "calendar_binding": "one-time exact anchor path; range exhaustion follows only its full-hash successor link, never a latest scan or daily environment edit",
        },
        "safety": {
            "read_only_sources": True,
            "candidate_only": True,
            "writes_market_database": False,
            "writes_formal_controlled_paths": False,
            "writes_scheduler": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
        },
        "wrapper_contract": wrapper_contract,
        "rolling_contract": _rolling_contract(
            output_root=output.parent,
            publication_root=publication,
            rule_source_root=rule_root,
            portfolio_clock=clock_path,
            paper_receipt_root=receipt_root,
        ),
        "publication_paths": publication_paths,
        "natural_execution_order": [
            {
                "step": 1,
                "window_taipei": "07:00-08:30",
                "owner": "formal_paper + v4_schedule_ops",
                "consumer": "formal_rule_source_producer",
                "output": str(rule_root / "clock-<YYYYMMDD>-machine-v2-or-v3-<source_window_hash_12>-<parent_clock_hash_12>"),
                "guard": "first same-day capture before 08:30; after cutoff only deterministic reuse",
            },
            {
                "step": 2,
                "window_taipei": "09:00-13:30",
                "owner": "formal_paper",
                "consumer": "formal_daily_input_producer",
                "output": publication_paths["rule_history_manifest"],
                "guard": "consume exact predecessor source-window bundle; do not query live DB as a replacement for v3",
            },
            {
                "step": 3,
                "window_taipei": "21:00/22:00 after Paper EOD source",
                "owner": "formal_paper + v4_schedule_ops",
                "consumer": "formal input / causal ledger",
                "output": publication_paths["causal_ledger_run_pattern"],
                "guard": "real fill receipt and closed [start,end) interval required; missing fill remains final gate",
            },
        ],
        "gates": {
            "candidate_only": True,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "writes_scheduler": False,
            "writes_market_database": False,
            "historical_backfill_claimed": False,
            "fixed_portfolio_clock": True,
            "daily_rule_source_is_versioned_separately": True,
            "source_window_v3_replay_is_immutable": True,
            "legacy_v2_requires_live_t1_revalidation": True,
            "paper_fill_is_final_release_gate": True,
        },
        "rollback": {
            "old_runtime_config_remains_unchanged": True,
            "new_config_is_not_applied_by_producer": True,
            "switch_requires_root_review_and_scheduler_owner_environment_update": True,
            "on_mismatch": "leave new date-scoped candidate unused; retain its evidence; restore prior exact runtime path atomically",
        },
    }
    body["config_hash"] = _payload_hash(body)
    return body


def write_immutable_rolling_runtime_config(
    output_path: Path,
    config: Mapping[str, object],
) -> tuple[str, str]:
    """create-only 寫入 config；已存在時只接受 byte-identical retry。"""

    payload = {str(key): item for key, item in config.items()}
    supplied_hash = payload.get("config_hash")
    body = dict(payload)
    body.pop("config_hash", None)
    if supplied_hash != _payload_hash(body):
        raise FormalRuntimeRollForwardError("runtime_config_config_hash_invalid")
    path = _absolute_path(output_path, "runtime_config_output")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    expected_file_hash = _bytes_hash(encoded)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise FormalRuntimeRollForwardError(
                f"runtime_config_existing_unreadable:{type(error).__name__}"
            ) from error
        if existing != encoded:
            raise FormalRuntimeRollForwardError("runtime_config_existing_bytes_mismatch")
        return "reused", expected_file_hash
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise FormalRuntimeRollForwardError(
            "runtime_config_created_concurrently"
        ) from error
    return "created", expected_file_hash


def _default_paths() -> dict[str, Path]:
    data_root = Path(os.environ.get("DATA_ROOT", r"D:\Min\Python\Project\FA_Data")).expanduser().resolve()
    publication_root = _environment_path(
        PUBLICATION_ROOT_ENV,
        ROOT / "output" / "formal_daily_publications",
    )
    if publication_root is None:  # pragma: no cover - fallback is always supplied
        raise FormalRuntimeRollForwardError("publication_root_missing")
    rule_root = _environment_path(RULE_SOURCE_ROOT_ENV, publication_root / "rule_source")
    pit_root = _environment_path(PIT_ARCHIVE_ROOT_ENV, publication_root / "pit_candidate_archive")
    return {
        "publication_root": publication_root,
        "market_db": _environment_path(MARKET_DB_ENV, data_root / "sqlite" / "twstock.db")
        or data_root / "sqlite" / "twstock.db",
        "rule_baseline_root": _environment_path(
            RULE_BASELINE_ENV,
            data_root / "output" / "formal_prospective",
        )
        or data_root / "output" / "formal_prospective",
        "calendar_cache_root": _environment_path(
            CALENDAR_CACHE_ENV,
            ROOT / "output" / "paper_execution_eod_replay" / "calendar_cache",
        )
        or ROOT / "output" / "paper_execution_eod_replay" / "calendar_cache",
        "rule_source_root": rule_root or publication_root / "rule_source",
        "pit_archive_root": pit_root or publication_root / "pit_candidate_archive",
        "paper_snapshot_db": _environment_path(
            PAPER_SNAPSHOT_ENV,
            ROOT / "output" / "paper_execution_eod_replay" / "paper_portfolio" / "paper_portfolio.sqlite",
        )
        or ROOT / "output" / "paper_execution_eod_replay" / "paper_portfolio.sqlite",
        "paper_fill_db": _environment_path(
            PAPER_FILL_ENV,
            ROOT / "output" / "paper_execution_eod_replay" / "paper_trade_ledger.sqlite",
        )
        or ROOT / "output" / "paper_execution_eod_replay" / "paper_trade_ledger.sqlite",
        "paper_receipt_root": _environment_path(
            PAPER_RECEIPT_ROOT_ENV,
            ROOT / "output" / "paper_execution_eod_replay" / "receipts",
        )
        or ROOT / "output" / "paper_execution_eod_replay" / "receipts",
    }


def _status_path(output_root: Path) -> Path:
    return output_root.parent / "runtime_roll_forward_status" / "latest.json"


def _write_status(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)


def run_from_environment(*, emit: bool = True) -> tuple[dict[str, object], int]:
    """使用目前 process clock 建立下一自然日設定；不接受日期參數。"""

    load_runtime_environment_binding()
    observed = datetime.now(timezone.utc)
    output_root = _environment_path(
        ROLL_FORWARD_ROOT_ENV,
        ROOT / "output" / "v4_next_formal" / "formal_daily_runtime_config",
    )
    if output_root is None:  # pragma: no cover - fallback is always supplied
        output_root = ROOT / "output" / "v4_next_formal" / "formal_daily_runtime_config"
    status_path = _status_path(output_root)
    base: dict[str, object] = {
        "schema_version": ROLL_FORWARD_SCHEMA_VERSION,
        "producer": "data_module.formal_runtime_roll_forward",
        "producer_version": "formal-runtime-roll-forward.v1",
        "observed_at": observed.isoformat(timespec="microseconds"),
        "observed_taipei_date": observed.astimezone(TAIPEI).date().isoformat(),
        "output_root": str(output_root.resolve()),
        "writes_scheduler": False,
        "writes_market_database": False,
        "writes_formal_controlled_paths": False,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "historical_backfill_claimed": False,
    }
    try:
        calendar_value = os.environ.get(CALENDAR_BUNDLE_ENV)
        if not isinstance(calendar_value, str) or not calendar_value.strip():
            raise FormalRuntimeRollForwardError(
                f"{CALENDAR_BUNDLE_ENV}_missing"
            )
        portfolio_value = os.environ.get(PORTFOLIO_CLOCK_ENV)
        if not isinstance(portfolio_value, str) or not portfolio_value.strip():
            raise FormalRuntimeRollForwardError(f"{PORTFOLIO_CLOCK_ENV}_missing")
        paths = _default_paths()
        calendar_anchor = _absolute_path(calendar_value, "calendar_anchor")
        calendar_bundle, calendar_resolution = _resolve_calendar_bundle_for_observed(
            calendar_anchor,
            publication_root=paths["publication_root"],
            observed=observed,
        )
        activation_day, _calendar_evidence = select_next_official_trading_day(
            calendar_bundle,
            observed=observed,
        )
        output_path = output_root / f"{activation_day.isoformat()}.json"
        config = build_rolling_runtime_config(
            observed=observed,
            activation_trading_day=activation_day,
            calendar_bundle=calendar_bundle,
            calendar_environment_bundle=calendar_anchor,
            calendar_resolution=calendar_resolution,
            portfolio_clock_manifest=Path(portfolio_value),
            output_path=output_path,
            publication_root=paths["publication_root"],
            market_db=paths["market_db"],
            rule_baseline_root=paths["rule_baseline_root"],
            calendar_cache_root=paths["calendar_cache_root"],
            rule_source_root=paths["rule_source_root"],
            pit_archive_root=paths["pit_archive_root"],
            paper_snapshot_db=paths["paper_snapshot_db"],
            paper_fill_db=paths["paper_fill_db"],
            paper_receipt_root=paths["paper_receipt_root"],
        )
        write_status, file_hash = write_immutable_rolling_runtime_config(
            output_path,
            config,
        )
        status = {
            **base,
            "status": "runtime_config_created" if write_status == "created" else "runtime_config_reused",
            "activation_trading_day": activation_day.isoformat(),
            "runtime_config_path": str(output_path.resolve()),
            "runtime_config_file_hash": file_hash,
            "portfolio_clock_manifest": str(Path(portfolio_value).expanduser().resolve()),
            "calendar_bundle": str(calendar_bundle.resolve()),
            "calendar_bundle_anchor": str(calendar_anchor),
            "calendar_resolution": calendar_resolution,
            "runtime_trigger": config.get("runtime_trigger"),
            "next_step": "root_review_then scheduler owner binds exact runtime config root and source pins once; loader date-binds each natural day",
            "config": config,
            "exit_code": 0,
            "status_path": str(status_path.resolve()),
        }
        _write_status(status_path, status)
        if emit:
            print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return status, 0
    except Exception as error:  # noqa: BLE001 - bounded status boundary
        status = {
            **base,
            "status": "blocked",
            "blockers": [
                f"runtime_roll_forward_failed:{type(error).__name__}:{str(error).splitlines()[0][:240]}"
            ],
            "exit_code": 2,
            "status_path": str(status_path.resolve()),
        }
        _write_status(status_path, status)
        if emit:
            print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return status, 2


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        raise FormalRuntimeRollForwardError(
            "runtime roll-forward does not accept date or source override arguments"
        )
    _, exit_code = run_from_environment()
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())


__all__ = [
    "CALENDAR_BUNDLE_ENV",
    "FORMAL_RUNTIME_CONFIG_ENV",
    "FormalRuntimeRollForwardError",
    "ROLL_FORWARD_SCHEMA_VERSION",
    "build_rolling_runtime_config",
    "select_next_official_trading_day",
    "write_immutable_rolling_runtime_config",
    "run_from_environment",
]
