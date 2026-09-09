"""Prepare one bounded, natural-date ML forward shadow run.

This is an unregistered scheduler preparation wrapper.  It wakes from the
Pacific 16:15 hook, waits for the real Asia/Taipei 08:30 decision clock, and
then invokes the derived shadow CLI with one explicitly frozen PIT source.
The operational publication and durable archive branches are mutually
exclusive.  A late start, missing config, source hash change, child failure,
or missing post-inference completion gate is recorded as blocked; the wrapper
never turns the existing 05:20 catch-up task into a forward caller.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time as time_module
from typing import Callable, Mapping, Sequence, cast
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from data_module.official_trading_calendar import OfficialTradingCalendar  # noqa: E402
from scripts import run_daily_ml_allocation_orchestration as daily_orchestration  # noqa: E402
TAIPEI = ZoneInfo("Asia/Taipei")
TAIPEI_CUTOFF = time(8, 30)
FORWARD_DEADLINE = time(8, 35)
SCHEDULED_WAKE_LOCAL_TIME = "16:15"
TASK_NAME = "baldr-ml-allocation-forward-daily"
SCHEMA_VERSION = "ml-forward-scheduled-status.v1"
CONFIG_SCHEMA_VERSION = "ml-forward-scheduled-config.v1"
DERIVED_SHADOW_SCRIPT = ROOT / "scripts" / "run_daily_ml_allocation_derived_shadow.py"
DEFAULT_CONFIG_ROOT = ROOT / "output" / "v4_ml_forward_scheduler"
DEFAULT_STATUS_ROOT = ROOT / "output" / "v4_ml_forward_scheduler"
SHA256_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


class ForwardScheduleConfigError(ValueError):
    """Frozen forward scheduler config violates its source/date contract."""


@dataclass(frozen=True)
class ForwardSource:
    kind: str
    path: Path | None = None
    file_hash: str | None = None
    root: Path | None = None
    manifest: Path | None = None
    manifest_file_hash: str | None = None


@dataclass(frozen=True)
class ForwardScheduleConfig:
    config_path: Path
    config_file_hash: str
    run_date: date
    database: Path
    paper_state_db: Path
    output_root: Path
    release_root: Path
    release_manifest_file_hash: str
    deadline_at: datetime
    source: ForwardSource


def _canonical_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _aware_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ForwardScheduleConfigError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ForwardScheduleConfigError(
            f"{field_name} must be an ISO timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForwardScheduleConfigError(f"{field_name} must contain a timezone")
    return parsed.astimezone(TAIPEI)


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ForwardScheduleConfigError(f"config.{key} is required")
    return value.strip()


def _required_path(payload: Mapping[str, object], key: str) -> Path:
    return Path(_required_text(payload, key)).expanduser().resolve()


def _required_sha256(payload: Mapping[str, object], key: str) -> str:
    value = _required_text(payload, key)
    if SHA256_RE.fullmatch(value) is None:
        raise ForwardScheduleConfigError(f"config.{key} must be sha256:<64 hex>")
    return value.lower()


def _validate_exact_keys(
    payload: Mapping[str, object],
    *,
    required: set[str],
    label: str,
) -> None:
    keys = set(payload)
    missing = sorted(required - keys)
    extra = sorted(keys - required)
    if missing:
        raise ForwardScheduleConfigError(
            f"{label} missing required keys: {','.join(missing)}"
        )
    if extra:
        raise ForwardScheduleConfigError(
            f"{label} has unsupported keys: {','.join(extra)}"
        )


def load_schedule_config(
    path: Path,
    *,
    expected_run_date: date,
) -> ForwardScheduleConfig:
    """Read one config byte sequence and validate its date/source branch."""

    resolved = path.expanduser().resolve()
    try:
        raw = resolved.read_bytes()
    except OSError as error:
        raise ForwardScheduleConfigError(
            f"forward config read failed: {type(error).__name__}"
        ) from error
    file_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ForwardScheduleConfigError("forward config JSON is invalid") from error
    if not isinstance(decoded, dict):
        raise ForwardScheduleConfigError("forward config must be a JSON object")
    required = {
        "schema_version",
        "task_name",
        "decision_timezone",
        "decision_time",
        "scheduled_wake_local",
        "run_date",
        "database",
        "paper_state_db",
        "output_root",
        "release_root",
        "release_manifest_file_hash",
        "natural_forward_deadline_at",
        "source",
    }
    _validate_exact_keys(decoded, required=required, label="config")
    if decoded.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise ForwardScheduleConfigError("config.schema_version is unsupported")
    if decoded.get("task_name") != TASK_NAME:
        raise ForwardScheduleConfigError("config.task_name does not match wrapper")
    if decoded.get("decision_timezone") != "Asia/Taipei":
        raise ForwardScheduleConfigError("config.decision_timezone must be Asia/Taipei")
    if decoded.get("decision_time") != "08:30":
        raise ForwardScheduleConfigError("config.decision_time must be 08:30")
    if decoded.get("scheduled_wake_local") != SCHEDULED_WAKE_LOCAL_TIME:
        raise ForwardScheduleConfigError(
            "config.scheduled_wake_local must be 16:15"
        )
    run_date_text = _required_text(decoded, "run_date")
    try:
        run_date = date.fromisoformat(run_date_text)
    except ValueError as error:
        raise ForwardScheduleConfigError("config.run_date must be YYYY-MM-DD") from error
    if run_date.isoformat() != run_date_text:
        raise ForwardScheduleConfigError("config.run_date must be YYYY-MM-DD")
    if run_date != expected_run_date:
        raise ForwardScheduleConfigError(
            "forward config run_date does not equal current Taipei natural date"
        )
    deadline_at = _aware_timestamp(
        decoded.get("natural_forward_deadline_at"),
        field_name="config.natural_forward_deadline_at",
    )
    expected_deadline = datetime.combine(
        run_date,
        FORWARD_DEADLINE,
        tzinfo=TAIPEI,
    )
    if deadline_at != expected_deadline:
        raise ForwardScheduleConfigError(
            "config.natural_forward_deadline_at must equal Taipei 08:35 for run_date"
        )

    source_value = decoded.get("source")
    if not isinstance(source_value, dict):
        raise ForwardScheduleConfigError("config.source must be an object")
    source: ForwardSource
    source_kind = source_value.get("kind")
    if source_kind == "operational_publication":
        _validate_exact_keys(
            source_value,
            required={"kind", "path", "file_hash"},
            label="config.source operational_publication",
        )
        source = ForwardSource(
            kind="operational_publication",
            path=_required_path(source_value, "path"),
            file_hash=_required_sha256(source_value, "file_hash"),
        )
    elif source_kind == "archive":
        _validate_exact_keys(
            source_value,
            required={"kind", "root", "manifest", "manifest_file_hash"},
            label="config.source archive",
        )
        source = ForwardSource(
            kind="archive",
            root=_required_path(source_value, "root"),
            manifest=_required_path(source_value, "manifest"),
            manifest_file_hash=_required_sha256(
                source_value,
                "manifest_file_hash",
            ),
        )
    else:
        raise ForwardScheduleConfigError(
            "config.source.kind must be operational_publication or archive"
        )
    return ForwardScheduleConfig(
        config_path=resolved,
        config_file_hash=file_hash,
        run_date=run_date,
        database=_required_path(decoded, "database"),
        paper_state_db=_required_path(decoded, "paper_state_db"),
        output_root=_required_path(decoded, "output_root"),
        release_root=_required_path(decoded, "release_root"),
        release_manifest_file_hash=_required_sha256(
            decoded,
            "release_manifest_file_hash",
        ),
        deadline_at=deadline_at,
        source=source,
    )


def _taipei_cutoff_for(value: datetime, cutoff: time = TAIPEI_CUTOFF) -> datetime:
    local = value.astimezone(TAIPEI)
    return datetime.combine(local.date(), cutoff, tzinfo=TAIPEI)


def _wait_until_taipei_cutoff(
    *,
    now_fn: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> datetime:
    """Wait on the real Taipei clock; test clocks are accepted only by tests."""

    clock = now_fn or (lambda: datetime.now(TAIPEI))
    sleeper = sleep_fn or time_module.sleep
    while True:
        current_raw = clock()
        if current_raw.tzinfo is None or current_raw.utcoffset() is None:
            raise ValueError("scheduled Taipei clock must include timezone")
        current = current_raw.astimezone(TAIPEI)
        cutoff = _taipei_cutoff_for(current)
        if current >= cutoff:
            return current
        remaining = (cutoff - current).total_seconds()
        sleeper(min(max(remaining, 0.1), 60.0))


def _source_args(source: ForwardSource) -> list[str]:
    if source.kind == "operational_publication":
        if source.path is None or source.file_hash is None:
            raise ForwardScheduleConfigError(
                "operational source requires path and file_hash"
            )
        return [
            "--pit-machine-operational-publication",
            str(source.path),
        ]
    if source.kind == "archive":
        if (
            source.root is None
            or source.manifest is None
            or source.manifest_file_hash is None
        ):
            raise ForwardScheduleConfigError(
                "archive source requires root, manifest and manifest_file_hash"
            )
        return [
            "--pit-machine-archive-root",
            str(source.root),
            "--pit-machine-archive-manifest",
            str(source.manifest),
            "--pit-machine-archive-manifest-file-hash",
            source.manifest_file_hash,
        ]
    raise ForwardScheduleConfigError("unsupported forward source kind")


def build_child_command(
    config: ForwardScheduleConfig,
    *,
    decision_at: datetime,
    derived_script: Path = DERIVED_SHADOW_SCRIPT,
) -> list[str]:
    """Build the exact child argv; it never includes legacy catch-up flags."""

    return [
        sys.executable,
        str(derived_script.expanduser().resolve()),
        "--database",
        str(config.database),
        "--paper-state-db",
        str(config.paper_state_db),
        "--output-root",
        str(config.output_root),
        "--release-root",
        str(config.release_root),
        "--mode",
        "forward_natural_date",
        "--decision-at",
        decision_at.astimezone(TAIPEI).isoformat(timespec="seconds"),
        *_source_args(config.source),
    ]


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_receipt(status_root: Path, payload: Mapping[str, object]) -> dict[str, str]:
    root = status_root.expanduser().resolve()
    receipt_root = root / "receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    receipt_path = receipt_root / f"{stamp}-{os.getpid()}.json"
    paths = {
        "receipt_path": str(receipt_path),
        "latest_status_path": str(root / "latest_status.json"),
    }
    record = dict(payload)
    record.update(paths)
    _atomic_write_json(receipt_path, record)
    latest_path = root / "latest_status.json"
    _atomic_write_json(latest_path, record)
    return paths


def _base_payload(
    *,
    observed: datetime,
    decision_at: datetime,
    deadline_at: datetime,
    config_path: Path,
    status: str,
    blockers: Sequence[str],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task": TASK_NAME,
        "producer": "scripts.scheduled.run_ml_allocation_forward_daily",
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "taipei_now": observed.astimezone(TAIPEI).isoformat(),
        "decision_at": decision_at.astimezone(TAIPEI).isoformat(),
        "natural_forward_deadline_at": deadline_at.astimezone(TAIPEI).isoformat(),
        "scheduled_wake_local": SCHEDULED_WAKE_LOCAL_TIME,
        "config_path": str(config_path.expanduser().resolve()),
        "status": status,
        "blockers": list(blockers),
        "candidate_only": True,
        "forward_credit_granted": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
        "writes_source_database": False,
        "writes_market_database": False,
        "training_started": False,
        "promotion_eligible": False,
        "post_deadline_maturity": None,
        "post_deadline_maturity_degraded": False,
        "post_deadline_maturity_exit_code": 0,
    }


def _verify_source(source: ForwardSource) -> str:
    if source.kind == "operational_publication":
        if source.path is None or source.file_hash is None:
            raise ForwardScheduleConfigError("operational source contract is incomplete")
        if not source.path.is_file():
            raise ForwardScheduleConfigError("operational publication path is missing")
        observed_hash = _canonical_file_hash(source.path)
        if observed_hash != source.file_hash:
            raise ForwardScheduleConfigError(
                "operational publication file hash changed from frozen config"
            )
        return observed_hash
    if source.kind == "archive":
        if (
            source.root is None
            or source.manifest is None
            or source.manifest_file_hash is None
        ):
            raise ForwardScheduleConfigError("archive source contract is incomplete")
        if not source.root.is_dir():
            raise ForwardScheduleConfigError("archive root is missing")
        if not source.manifest.is_file():
            raise ForwardScheduleConfigError("archive manifest is missing")
        observed_hash = _canonical_file_hash(source.manifest)
        if observed_hash != source.manifest_file_hash:
            raise ForwardScheduleConfigError(
                "archive manifest file hash changed from frozen config"
            )
        return observed_hash
    raise ForwardScheduleConfigError("unsupported forward source kind")


def _verify_release(config: ForwardScheduleConfig) -> str:
    """Re-read the frozen release manifest before starting the child."""

    if not config.release_root.is_dir():
        raise ForwardScheduleConfigError("release root is missing")
    manifest = config.release_root / "release_manifest.json"
    if not manifest.is_file():
        raise ForwardScheduleConfigError("release manifest is missing")
    observed_hash = _canonical_file_hash(manifest)
    if observed_hash != config.release_manifest_file_hash:
        raise ForwardScheduleConfigError(
            "release manifest file hash changed from frozen config"
        )
    return observed_hash


def run_preflight(
    *,
    derived_script: Path = DERIVED_SHADOW_SCRIPT,
) -> tuple[dict[str, object], int]:
    """Check deployment inputs without waiting, producing, or running ML."""

    from scripts.scheduled.prepare_ml_allocation_forward_config import (
        default_archive_root,
        default_calendar_cache_root,
        default_database,
        default_output_root,
        default_paper_state_db,
        default_release_manifest_file_hash,
        default_release_root,
        default_temporary_closure_path,
    )

    release_root = default_release_root()
    release_manifest = release_root / "release_manifest.json"
    expected_release_hash = default_release_manifest_file_hash()
    checks: list[dict[str, object]] = []

    def check_path(name: str, path: Path, *, kind: str) -> None:
        exists = path.is_dir() if kind == "directory" else path.is_file()
        checks.append(
            {
                "name": name,
                "kind": kind,
                "path": str(path.expanduser().resolve()),
                "exists": exists,
            }
        )

    check_path("derived_script", derived_script, kind="file")
    check_path("market_database", default_database(), kind="file")
    check_path("paper_state_database", default_paper_state_db(), kind="file")
    check_path("shadow_output_root", default_output_root(), kind="directory")
    check_path("archive_root", default_archive_root(), kind="directory")
    check_path("calendar_cache_root", default_calendar_cache_root(), kind="directory")
    check_path(
        "temporary_closure_root",
        default_temporary_closure_path(),
        kind="directory",
    )
    check_path("release_root", release_root, kind="directory")
    check_path("release_manifest", release_manifest, kind="file")

    observed_release_hash: str | None = None
    release_error: str | None = None
    if release_manifest.is_file():
        try:
            observed_release_hash = _canonical_file_hash(release_manifest)
        except OSError as error:
            release_error = f"{type(error).__name__}:{error}"
    if observed_release_hash != expected_release_hash:
        release_error = release_error or "release manifest file hash mismatch"

    blockers = [
        f"missing:{item['name']}"
        for item in checks
        if item["exists"] is not True
    ]
    if release_error is not None:
        blockers.append(f"release_pin:{release_error}")
    payload: dict[str, object] = {
        "schema_version": "ml-forward-preflight.v1",
        "task": TASK_NAME,
        "status": "ready" if not blockers else "blocked",
        "checks": checks,
        "release_root": str(release_root.expanduser().resolve()),
        "release_manifest_file_hash": expected_release_hash,
        "release_manifest_file_hash_observed": observed_release_hash,
        "blockers": blockers,
        "wait_started": False,
        "config_producer_called": False,
        "child_started": False,
        "writes_market_database": False,
        "writes_source_database": False,
        "forward_credit_granted": False,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }
    return payload, 0 if not blockers else 2


def _parse_child_payload(stdout: str) -> Mapping[str, object]:
    text = stdout.strip()
    if not text:
        raise ForwardScheduleConfigError("forward child returned empty JSON")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ForwardScheduleConfigError("forward child returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ForwardScheduleConfigError("forward child JSON must be an object")
    return payload


def _child_completion_is_allowed(
    payload: Mapping[str, object],
    *,
    deadline_at: datetime,
) -> tuple[bool, str | None]:
    status = payload.get("status")
    if status == "skipped_non_trading_day":
        return True, None
    if status != "completed":
        return False, "child_status_not_completed"
    clock_value = _child_completion_clock(payload)
    if not isinstance(clock_value, Mapping):
        return False, "child_completion_gate_missing"
    if clock_value.get("within_forward_completion_window") is not True:
        return False, "child_completion_gate_not_passed"
    completed_at = _aware_timestamp(
        clock_value.get("post_inference_completed_at"),
        field_name="child.natural_forward_completion_clock.post_inference_completed_at",
    )
    if completed_at.astimezone(timezone.utc) > deadline_at.astimezone(timezone.utc):
        return False, "child_completion_after_08:35"
    return True, None


def _child_completion_clock(
    payload: Mapping[str, object],
) -> Mapping[str, object] | None:
    """Read the real derived payload's nested orchestration clock.

    The derived CLI returns the orchestration status as a top-level object and
    keeps the natural forward clock under ``daily_orchestration``.  A top-level
    projection is accepted for compatibility with a small number of older
    isolated receipts, but the scheduled caller never synthesizes this clock.
    """

    value = payload.get("natural_forward_completion_clock")
    if isinstance(value, Mapping):
        return value
    orchestration = payload.get("daily_orchestration")
    if isinstance(orchestration, Mapping):
        nested = orchestration.get("natural_forward_completion_clock")
        if isinstance(nested, Mapping):
            return nested
    return None


def _calendar_cache_path_from_environment() -> Path | None:
    for name in (
        "ML_FORWARD_CALENDAR_CACHE_ROOT",
        "FORMAL_DAILY_CALENDAR_CACHE_ROOT",
    ):
        value = os.environ.get(name)
        if isinstance(value, str) and value.strip():
            return Path(value.strip()).expanduser().resolve()
    return None


def _child_daily_orchestration(
    payload: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if payload is None:
        return None
    value = payload.get("daily_orchestration")
    return value if isinstance(value, Mapping) else None


def _post_deadline_maturity(
    *,
    config: ForwardScheduleConfig,
    decision_at: datetime,
    child_payload: Mapping[str, object] | None,
    maturity_calendar: object | None,
) -> dict[str, object]:
    """在 child timeout window 外回填既有 shadow outcome。

    child 只負責在 08:35 前完成 observation emission。此函式由 wrapper
    在 ``subprocess.run`` 返回後呼叫，因此成熟掃描的耗時不會佔用 child
    deadline。lane root、source database 與 strict T-1 都由 frozen config／
    child status 綁定；缺少可驗證 cutoff 時 fail closed，不以日期減一天猜測。
    """

    run_root = (
        config.output_root / "scheduled" / "ml_allocation_copilot"
    ).resolve()
    sidecar_path = run_root / "shadow_evidence_collector" / "shadow_evidence.sqlite"
    base: dict[str, object] = {
        "mode": "maturity_only_post_deadline",
        "run_root": str(run_root),
        "sidecar_database_path": str(sidecar_path),
        "source_database_path": str(config.database.resolve()),
        "source_database_mode": "ro",
        "query_only": True,
        "post_deadline": True,
        "child_result_available": child_payload is not None,
        "natural_day_credit_granted": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "writes_market_database": False,
        "source_binding": {
            "config_output_root": str(config.output_root.resolve()),
            "config_database": str(config.database.resolve()),
            "lane_root": str(run_root),
            "sidecar_database": str(sidecar_path),
        },
    }

    daily_status = _child_daily_orchestration(child_payload)
    cutoff_date: date | None = None
    cutoff_reason: str | None = None
    child_cutoff_value = (
        daily_status.get("natural_shadow_maturity_cutoff_date")
        if daily_status is not None
        else None
    )
    child_cutoff_reason = (
        daily_status.get("natural_shadow_maturity_cutoff_reason")
        if daily_status is not None
        else None
    )
    if child_payload is not None and not (
        isinstance(child_cutoff_value, str) and child_cutoff_value.strip()
    ):
        # A successful child must publish the common maturity contract.  An
        # absent cutoff is a broken source binding, not a normal pending state;
        # allowing it through would make a successful receipt look complete
        # while the post-deadline consumer had no legal maturity date.
        return {
            **base,
            "status": "blocked",
            "blocker": "child_maturity_cutoff_contract_missing",
        }
    if isinstance(child_cutoff_value, str) and child_cutoff_value.strip():
        try:
            cutoff_date = date.fromisoformat(child_cutoff_value)
        except ValueError:
            return {
                **base,
                "status": "blocked",
                "blocker": "child_maturity_cutoff_date_invalid",
            }
    # A timeout can leave a durable observation without a completed child JSON
    # payload.  Recover the cutoff from the official cache only when the
    # scheduled environment supplied that cache; otherwise retain a visible
    # block instead of guessing a weekday or calendar date.  A child-provided
    # cutoff uses the same resolver so a stale or arbitrary past date cannot be
    # accepted merely because it is before the runtime clock.
    calendar_service = maturity_calendar
    if calendar_service is None:
        cache_path = _calendar_cache_path_from_environment()
        if cache_path is None:
            return {
                **base,
                "status": "blocked",
                "blocker": "maturity_calendar_source_missing",
            }
        try:
            calendar_service = OfficialTradingCalendar(
                config.database,
                calendar_cache_path=cache_path,
            )
        except Exception as exc:  # noqa: BLE001 - preserve block evidence
            return {
                **base,
                "status": "blocked",
                "blocker": (
                    "maturity_calendar_init:"
                    f"{type(exc).__name__}:{' '.join(str(exc).split())}"
                ),
            }
    expected_cutoff, expected_reason = (
        daily_orchestration.resolve_shadow_maturity_cutoff(
            calendar=cast(daily_orchestration.TradingCalendar, calendar_service),
            decision_date=decision_at.astimezone(TAIPEI).date(),
        )
    )
    if expected_cutoff is None:
        return {
            **base,
            "status": "blocked",
            "blocker": (
                "maturity_cutoff_unavailable:"
                + (expected_reason or "unknown")
            ),
        }
    if cutoff_date is not None and cutoff_date != expected_cutoff:
        return {
            **base,
            "status": "blocked",
            "cutoff_date": cutoff_date.isoformat(),
            "expected_cutoff_date": expected_cutoff.isoformat(),
            "blocker": "child_maturity_cutoff_not_strict_t_minus_one",
        }
    cutoff_date = expected_cutoff
    cutoff_reason = expected_reason

    child_maturity = (
        daily_status.get("natural_shadow_maturity")
        if daily_status is not None
        else None
    )
    if isinstance(child_maturity, Mapping):
        child_run_root = child_maturity.get("run_root")
        if isinstance(child_run_root, str) and child_run_root.strip():
            if Path(child_run_root).expanduser().resolve() != run_root:
                return {
                    **base,
                    "status": "blocked",
                    "cutoff_date": cutoff_date.isoformat(),
                    "blocker": "child_maturity_lane_root_mismatch",
                }
    child_database_path = (
        daily_status.get("natural_shadow_maturity_database_path")
        if daily_status is not None
        else None
    )
    if isinstance(child_database_path, str) and child_database_path.strip():
        if Path(child_database_path).expanduser().resolve() != config.database.resolve():
            return {
                **base,
                "status": "blocked",
                "cutoff_date": cutoff_date.isoformat(),
                "blocker": "child_maturity_database_path_mismatch",
            }

    result = daily_orchestration.run_shadow_maturity_refresh(
        database_path=config.database,
        run_root=run_root,
        cutoff_date=cutoff_date,
    )
    return {
        **result,
        "mode": "maturity_only_post_deadline",
        "post_deadline": True,
        "child_result_available": child_payload is not None,
        "cutoff_date": cutoff_date.isoformat(),
        "cutoff_reason": cutoff_reason,
        "child_cutoff_date": (
            child_cutoff_value if isinstance(child_cutoff_value, str) else None
        ),
        "child_cutoff_reason": (
            child_cutoff_reason
            if isinstance(child_cutoff_reason, str)
            else None
        ),
        "strict_t_minus_one_verified": True,
    }


def _attach_post_deadline_maturity(
    *,
    payload: dict[str, object],
    config: ForwardScheduleConfig,
    decision_at: datetime,
    child_payload: Mapping[str, object] | None,
    maturity_calendar: object | None,
) -> dict[str, object]:
    try:
        result = _post_deadline_maturity(
            config=config,
            decision_at=decision_at,
            child_payload=child_payload,
            maturity_calendar=maturity_calendar,
        )
    except Exception as exc:  # noqa: BLE001 - wrapper remains fail closed
        result = {
            "mode": "maturity_only_post_deadline",
            "status": "blocked",
            "post_deadline": True,
            "child_result_available": child_payload is not None,
            "blocker": f"{type(exc).__name__}:{' '.join(str(exc).split())}",
            "natural_day_credit_granted": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
            "writes_market_database": False,
        }
    payload["post_deadline_maturity"] = result
    result_status = result.get("status")
    is_blocked = isinstance(result_status, str) and result_status.startswith(
        "blocked"
    )
    payload["post_deadline_maturity_degraded"] = is_blocked
    payload["post_deadline_maturity_exit_code"] = 2 if is_blocked else 0
    if is_blocked:
        blockers = payload.get("blockers")
        blocker_list = list(blockers) if isinstance(blockers, list) else []
        marker = "post_deadline_maturity:blocked"
        if marker not in blocker_list:
            blocker_list.append(marker)
        payload["blockers"] = blocker_list
    return payload


def run_once(
    *,
    config_path: Path | None = None,
    config_root: Path | None = None,
    observed: datetime,
    derived_script: Path = DERIVED_SHADOW_SCRIPT,
    status_root_override: Path | None = None,
    child_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    maturity_calendar: object | None = None,
) -> tuple[dict[str, object], int]:
    """Run one already-cutoff invocation; ``observed`` must be an aware clock."""

    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("observed must contain a timezone")
    local_now = observed.astimezone(TAIPEI)
    decision_at = _taipei_cutoff_for(local_now)
    deadline_at = datetime.combine(local_now.date(), FORWARD_DEADLINE, tzinfo=TAIPEI)
    requested_config_path = config_path
    if requested_config_path is None:
        requested_config_path = (
            (config_root or DEFAULT_CONFIG_ROOT)
            / "configs"
            / f"{local_now.date().isoformat()}.json"
        )
    status_root = status_root_override or DEFAULT_STATUS_ROOT
    if local_now < decision_at:
        payload = _base_payload(
            observed=local_now,
            decision_at=decision_at,
            deadline_at=deadline_at,
            config_path=requested_config_path,
            status="waiting_for_taipei_cutoff",
            blockers=["taipei_08:30_decision_clock_not_reached"],
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    if local_now > deadline_at:
        payload = _base_payload(
            observed=local_now,
            decision_at=decision_at,
            deadline_at=deadline_at,
            config_path=requested_config_path,
            status="blocked_forward_window_expired",
            blockers=["forward_capture_started_after_taipei_08:35"],
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    if config_path is None:
        try:
            from scripts.scheduled.prepare_ml_allocation_forward_config import (
                ForwardConfigProducerError,
                default_archive_root,
                default_calendar_cache_root,
                default_database,
                default_output_root,
                default_paper_state_db,
                default_release_root,
                default_temporary_closure_path,
                prepare_daily_config,
            )

            producer_root = config_root or DEFAULT_CONFIG_ROOT
            producer_status = prepare_daily_config(
                config_root=producer_root,
                archive_root=default_archive_root(),
                decision_at=decision_at,
                now=local_now,
                database=default_database(),
                paper_state_db=default_paper_state_db(),
                output_root=default_output_root(),
                release_root=default_release_root(),
                calendar_cache_path=default_calendar_cache_root(),
                temporary_closure_path=default_temporary_closure_path(),
            )
            if producer_status.get("status") == "skipped_non_trading_day":
                payload = _base_payload(
                    observed=local_now,
                    decision_at=decision_at,
                    deadline_at=deadline_at,
                    config_path=requested_config_path,
                    status="skipped_non_trading_day",
                    blockers=[],
                )
                payload["config_producer_status"] = producer_status
                paths = _write_receipt(status_root, payload)
                payload.update(paths)
                return payload, 0
        except (ForwardConfigProducerError, OSError, TypeError, ValueError) as error:
            payload = _base_payload(
                observed=local_now,
                decision_at=decision_at,
                deadline_at=deadline_at,
                config_path=requested_config_path,
                status="blocked_config_producer",
                blockers=[
                    f"forward_config_producer:{type(error).__name__}:{error}"
                ],
            )
            paths = _write_receipt(status_root, payload)
            payload.update(paths)
            return payload, 2
    try:
        config = load_schedule_config(
            requested_config_path,
            expected_run_date=local_now.date(),
        )
    except ForwardScheduleConfigError as error:
        payload = _base_payload(
            observed=local_now,
            decision_at=decision_at,
            deadline_at=deadline_at,
            config_path=requested_config_path,
            status="blocked_invalid_config",
            blockers=[f"forward_config:{type(error).__name__}:{error}"],
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    status_root = status_root_override or config.output_root / "scheduled" / "ml_allocation_forward"
    try:
        observed_release_manifest_hash = _verify_release(config)
        observed_source_hash = _verify_source(config.source)
        command = build_child_command(
            config,
            decision_at=decision_at,
            derived_script=derived_script,
        )
    except (ForwardScheduleConfigError, OSError) as error:
        payload = _base_payload(
            observed=local_now,
            decision_at=decision_at,
            deadline_at=deadline_at,
            config_path=config.config_path,
            status="blocked_source_contract",
            blockers=[f"forward_source:{type(error).__name__}:{error}"],
        )
        payload["config_file_sha256"] = config.config_file_hash
        payload["release_manifest_file_hash"] = config.release_manifest_file_hash
        payload["source_kind"] = config.source.kind
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2

    current = (now_fn or (lambda: datetime.now(TAIPEI)))()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("forward scheduler clock must contain a timezone")
    current = current.astimezone(TAIPEI)
    remaining = (deadline_at - current).total_seconds()
    if remaining <= 0:
        payload = _base_payload(
            observed=current,
            decision_at=decision_at,
            deadline_at=deadline_at,
            config_path=config.config_path,
            status="blocked_forward_window_expired",
            blockers=["forward_capture_deadline_reached_before_child_start"],
        )
        payload["config_file_sha256"] = config.config_file_hash
        payload["release_manifest_file_hash"] = config.release_manifest_file_hash
        payload["source_kind"] = config.source.kind
        payload = _attach_post_deadline_maturity(
            payload=payload,
            config=config,
            decision_at=decision_at,
            child_payload=None,
            maturity_calendar=maturity_calendar,
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    runner = child_runner or subprocess.run
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.1, remaining),
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        payload = _base_payload(
            observed=datetime.now(TAIPEI),
            decision_at=decision_at,
            deadline_at=deadline_at,
            config_path=config.config_path,
            status="blocked_child_timeout",
            blockers=["forward_child_crossed_taipei_08:35_deadline"],
        )
        payload.update(
            {
                "config_file_sha256": config.config_file_hash,
                "release_manifest_file_hash": config.release_manifest_file_hash,
                "release_manifest_file_hash_observed": observed_release_manifest_hash,
                "source_kind": config.source.kind,
                "source_file_hash_observed": observed_source_hash,
                "child_stdout_sha256": hashlib.sha256(
                    str(error.stdout or "").encode("utf-8")
                ).hexdigest(),
            }
        )
        payload = _attach_post_deadline_maturity(
            payload=payload,
            config=config,
            decision_at=decision_at,
            child_payload=None,
            maturity_calendar=maturity_calendar,
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    except OSError as error:
        payload = _base_payload(
            observed=datetime.now(TAIPEI),
            decision_at=decision_at,
            deadline_at=deadline_at,
            config_path=config.config_path,
            status="blocked_child_start",
            blockers=[f"forward_child_start:{type(error).__name__}:{error}"],
        )
        payload["config_file_sha256"] = config.config_file_hash
        payload["release_manifest_file_hash"] = config.release_manifest_file_hash
        payload["source_kind"] = config.source.kind
        payload = _attach_post_deadline_maturity(
            payload=payload,
            config=config,
            decision_at=decision_at,
            child_payload=None,
            maturity_calendar=maturity_calendar,
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2

    stdout = completed.stdout or ""
    payload = _base_payload(
        observed=datetime.now(TAIPEI),
        decision_at=decision_at,
        deadline_at=deadline_at,
        config_path=config.config_path,
        status="blocked_child_result",
        blockers=[],
    )
    payload.update(
        {
            "config_file_sha256": config.config_file_hash,
            "release_manifest_file_hash": config.release_manifest_file_hash,
            "release_manifest_file_hash_observed": observed_release_manifest_hash,
            "source_kind": config.source.kind,
            "source_file_hash_observed": observed_source_hash,
            "child_returncode": completed.returncode,
            "child_stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "child_stderr_tail": (completed.stderr or "")[-1_000:],
        }
    )
    try:
        child_payload = _parse_child_payload(stdout)
    except ForwardScheduleConfigError as error:
        payload["status"] = "blocked_child_payload"
        payload["blockers"] = [f"forward_child:{type(error).__name__}:{error}"]
        payload = _attach_post_deadline_maturity(
            payload=payload,
            config=config,
            decision_at=decision_at,
            child_payload=None,
            maturity_calendar=maturity_calendar,
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    payload["child_status"] = child_payload.get("status")
    child_clock = _child_completion_clock(child_payload)
    if isinstance(child_clock, Mapping):
        payload["child_completion_clock"] = dict(child_clock)
    if completed.returncode != 0:
        payload["status"] = "blocked_child_exit"
        payload["blockers"] = ["forward_child_returncode_nonzero"]
        payload = _attach_post_deadline_maturity(
            payload=payload,
            config=config,
            decision_at=decision_at,
            child_payload=child_payload,
            maturity_calendar=maturity_calendar,
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    try:
        allowed, reason = _child_completion_is_allowed(
            child_payload,
            deadline_at=deadline_at,
        )
    except ForwardScheduleConfigError as error:
        allowed, reason = False, f"child_completion_clock_invalid:{error}"
    if not allowed:
        payload["status"] = "blocked_child_completion_gate"
        payload["blockers"] = [reason or "child_completion_gate_not_passed"]
        payload = _attach_post_deadline_maturity(
            payload=payload,
            config=config,
            decision_at=decision_at,
            child_payload=child_payload,
            maturity_calendar=maturity_calendar,
        )
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    if child_payload.get("status") == "skipped_non_trading_day":
        payload["status"] = "skipped_non_trading_day"
        payload["blockers"] = []
    else:
        payload["status"] = "completed_candidate_shadow"
        payload["candidate_forward_gate_verified"] = True
        payload["blockers"] = []
    payload = _attach_post_deadline_maturity(
        payload=payload,
        config=config,
        decision_at=decision_at,
        child_payload=child_payload,
        maturity_calendar=maturity_calendar,
    )
    if payload["post_deadline_maturity_exit_code"] != 0:
        payload["status"] = "blocked_post_deadline_maturity"
        blockers = payload.get("blockers")
        blocker_list = list(blockers) if isinstance(blockers, list) else []
        if "post_deadline_maturity_failed" not in blocker_list:
            blocker_list.append("post_deadline_maturity_failed")
        payload["blockers"] = blocker_list
        paths = _write_receipt(status_root, payload)
        payload.update(paths)
        return payload, 2
    paths = _write_receipt(status_root, payload)
    payload.update(paths)
    return payload, 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="只檢查 wrapper／路徑／V2 manifest pin；不等待、不產生 config、不執行 child",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=(
            Path(os.environ["ML_FORWARD_CONFIG_PATH"])
            if os.environ.get("ML_FORWARD_CONFIG_PATH")
            else None
        ),
        help=(
            "explicit immutable natural-date forward config; when omitted, "
            "the producer creates/loads configs/YYYY-MM-DD.json"
        ),
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        default=Path(
            os.environ.get("ML_FORWARD_CONFIG_ROOT", str(DEFAULT_CONFIG_ROOT))
        ),
        help="date-keyed create-only config root used when --config is omitted",
    )
    parser.add_argument(
        "--derived-script",
        type=Path,
        default=DERIVED_SHADOW_SCRIPT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--status-root",
        type=Path,
        default=None,
        help="optional isolated receipt root; defaults under configured output_root",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.preflight:
        payload, code = run_preflight(derived_script=args.derived_script)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return code
    reached = _wait_until_taipei_cutoff()
    payload, code = run_once(
        config_path=args.config,
        config_root=args.config_root,
        observed=reached,
        derived_script=args.derived_script,
        status_root_override=args.status_root,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
