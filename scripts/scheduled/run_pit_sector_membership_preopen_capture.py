"""在台北 08:30 前保存官方 PIT current-day archive。

此排程是 PIT 日常鏈的 capture half：它只在台北 08:30 前啟動官方
TWSE／TPEx read-only source，並把 response completion、raw custody、machine
consumer readback 與 durable archive 一起保存。盤後 publisher 只讀這份
archive，不會用新的同日 HTTP response 取代盤前 evidence。
"""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_daily_input_producer import (  # noqa: E402
    FormalDailyInputProducerError,
    capture_pit_candidate_before_cutoff,
    reuse_pit_candidate_archive_before_cutoff,
)
from data_module.pit_prospective_denominator import (  # noqa: E402
    validate_prospective_pit_denominator,
)
from scripts.capture_pit_prospective_denominator import (  # noqa: E402
    capture_live_denominator,
)


TASK_NAME = "baldr-pit-sector-membership-preopen-capture-daily"
DEFAULT_PUBLICATION_ROOT = ROOT / "output" / "formal_daily_publications"
TAIPEI = ZoneInfo("Asia/Taipei")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publication-root",
        type=Path,
        help="持久 publication root；只能是 repository output 或隔離 TEMP",
    )
    parser.add_argument(
        "--status-root",
        type=Path,
        help="狀態輸出目錄；預設為 publication root/scheduler/pit_preopen_capture",
    )
    return parser


def _publication_root(override: Path | None) -> Path:
    configured = override or _env_path("FORMAL_DAILY_PUBLICATION_ROOT")
    return (configured or DEFAULT_PUBLICATION_ROOT).expanduser().resolve()


def _status_root(publication_root: Path, override: Path | None) -> Path:
    configured = override or _env_path("FORMAL_DAILY_PIT_CAPTURE_STATUS_ROOT")
    root = (configured or publication_root / "scheduler" / "pit_preopen_capture").expanduser().resolve()
    try:
        root.relative_to(publication_root)
    except ValueError as error:
        raise ValueError("PIT capture status root must be under publication root") from error
    return root


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.strip())


def _write_status(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _find_verified_denominator(
    publication_root: Path,
    *,
    target_date: datetime,
) -> tuple[Path | None, str | None]:
    """找出當日已驗證的獨立分母；只接受同一台北自然日的封套。"""

    local_date = target_date.astimezone(TAIPEI).date().isoformat()
    candidates = sorted(
        (
            publication_root.expanduser().resolve() / "pit_denominator"
        ).glob(local_date + "*/denominator.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    failures: list[str] = []
    for candidate in candidates:
        try:
            payload = validate_prospective_pit_denominator(
                candidate,
                now=target_date,
            )
            if payload.get("coverage_start") != local_date:
                failures.append(f"{candidate.name}:coverage_start_mismatch")
                continue
            return candidate.resolve(), "existing_verified"
        except Exception as error:  # noqa: BLE001 - try next immutable run
            failures.append(f"{candidate.name}:{type(error).__name__}")
    detail = ";".join(failures[:3])
    return None, "missing" + (":" + detail if detail else "")


def _refresh_pit_denominator(
    *,
    publication_root: Path,
    observed: datetime,
    allow_network: bool,
) -> dict[str, object]:
    """在 PIT 盤前 task 內自動建立當日獨立 denominator。"""

    root = publication_root.expanduser().resolve()
    existing, existing_reason = _find_verified_denominator(
        root,
        target_date=observed,
    )
    if existing is not None:
        return {
            "status": "existing_verified",
            "path": str(existing),
            "coverage_start": observed.astimezone(TAIPEI).date().isoformat(),
            "network_attempted": False,
        }
    if not allow_network:
        return {
            "status": "skipped_injected_clock",
            "reason": "operational denominator refresh is disabled for an injected test clock",
            "existing_lookup": existing_reason,
            "network_attempted": False,
        }
    target_date = observed.astimezone(TAIPEI).date()
    output_dir = (
        root
        / "pit_denominator"
        / f"{target_date.isoformat()}-run-{uuid.uuid4().hex[:16]}"
    )
    try:
        result = capture_live_denominator(
            output_dir=output_dir,
            coverage_start=target_date,
        )
        path = Path(str(result["path"])).expanduser().resolve()
        validated = validate_prospective_pit_denominator(path)
    except Exception as error:  # noqa: BLE001 - source failure stays observable
        return {
            "status": "blocked",
            "reason": f"pit_denominator_refresh_failed:{type(error).__name__}:{str(error).splitlines()[0][:220]}",
            "existing_lookup": existing_reason,
            "network_attempted": True,
        }
    license_scope = validated.get("license_scope")
    license_status = (
        license_scope.get("status")
        if isinstance(license_scope, Mapping)
        else None
    )
    return {
        "status": "captured_verified",
        "path": str(path),
        "file_sha256": result.get("file_sha256"),
        "content_sha256": validated.get("content_sha256"),
        "coverage_start": validated.get("coverage_start"),
        "symbol_count": validated.get("symbol_count"),
        "license_scope_status": license_status,
        "network_attempted": True,
    }


def run_capture(
    *,
    publication_root: Path,
    status_root: Path,
    now: datetime | None = None,
) -> tuple[dict[str, object], int]:
    injected_clock = now is not None
    observed = now or datetime.now(timezone.utc)
    status_path = status_root / "latest_status.json"
    base: dict[str, object] = {
        "schema_version": "pit-preopen-capture-scheduled-status.v1",
        "task": TASK_NAME,
        "producer": "data_module.formal_daily_input_producer.capture_pit_candidate_before_cutoff",
        "observed_at": observed.isoformat(),
        "publication_root": str(publication_root),
        "status_path": str(status_path),
        "capture_policy": "capture_before_taipei_0830_then_read_archive_after_cutoff",
        "post_cutoff_refetch_forbidden": True,
        "candidate_only": True,
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "production_action_allowed": False,
        "broker_order_allowed": False,
        "writes_source_database": False,
        "writes_formal_controlled_paths": False,
        "training_started": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    try:
        try:
            result = reuse_pit_candidate_archive_before_cutoff(
                publication_root=publication_root,
                now=observed,
            )
            capture_mode = "reused_existing_verified_archive"
        except FormalDailyInputProducerError as error:
            # A missing current-day archive is the only condition that permits
            # the one live preopen capture.  A present but invalid archive must
            # remain fail-closed instead of being hidden by a second capture.
            if not str(error).startswith("PIT preopen archive is missing for "):
                raise
            result = capture_pit_candidate_before_cutoff(
                publication_root=publication_root,
                now=observed,
            )
            capture_mode = "new_live_capture"
        denominator = _refresh_pit_denominator(
            publication_root=publication_root,
            observed=observed,
            allow_network=not injected_clock,
        )
        archive_value = result.get("durable_archive")
        archive_info = (
            {str(key): value for key, value in archive_value.items()}
            if isinstance(archive_value, Mapping)
            else None
        )
        payload = {
            **base,
            "status": "machine_verified_candidate",
            "capture": result,
            "archive_manifest_path": archive_info.get("archive_manifest_path")
            if archive_info is not None
            else None,
            "archive_readback_verified": result.get("durable_archive_verified") is True,
            "capture_mode": capture_mode,
            "denominator_refresh": denominator,
        }
        _write_status(status_path, payload)
        return payload, 2 if denominator.get("status") == "blocked" else 0
    except Exception as error:  # noqa: BLE001 - scheduled boundary is fail closed
        payload = {
            **base,
            "status": "blocked",
            "blockers": [
                f"pit_preopen_capture_failed:{type(error).__name__}:{str(error).splitlines()[0][:220]}"
            ],
            "capture": {},
        }
        _write_status(status_path, payload)
        return payload, 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        publication_root = _publication_root(args.publication_root)
        status_root = _status_root(publication_root, args.status_root)
        payload, exit_code = run_capture(
            publication_root=publication_root,
            status_root=status_root,
        )
    except (OSError, TypeError, ValueError, FormalDailyInputProducerError) as error:
        payload = {
            "schema_version": "pit-preopen-capture-scheduled-status.v1",
            "task": TASK_NAME,
            "status": "blocked",
            "blockers": [
                f"pit_preopen_capture_configuration_failed:{type(error).__name__}:{str(error).splitlines()[0][:220]}"
            ],
            "candidate_only": True,
            "formal_ready": False,
            "formal_oos_allowed": False,
            "production_action_allowed": False,
        }
        exit_code = 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
