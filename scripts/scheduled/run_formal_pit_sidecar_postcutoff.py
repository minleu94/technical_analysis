"""在台北 08:30 後以盤前 archive 發布 PIT sector sidecar。

這個入口不抓取 HTTP source。它以真實 decision clock 重新建立當日 handoff，
再把 08:30 前已完成的 immutable archive 交給 formal sidecar publisher／
assembler consumer；沒有該 archive、coverage 或授權證據時只保存 blocked
receipt。
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_pit_history_handoff import (  # noqa: E402
    persist_pit_candidate_history_handoff,
)
from data_module.formal_pit_sector_publisher import (  # noqa: E402
    publish_formal_pit_sector_sidecar,
)
from data_module.official_trading_calendar import OfficialTradingCalendar  # noqa: E402
from data_module.pit_prospective_denominator import (  # noqa: E402
    validate_prospective_pit_denominator,
)
from data_module.formal_runtime_config import (  # noqa: E402
    FORMAL_RUNTIME_CONFIG_ENV,
    FormalRuntimeConfigError,
    load_optional_formal_runtime_config,
)


TASK_NAME = "baldr-formal-pit-sidecar-postcutoff-daily"
TAIPEI = ZoneInfo("Asia/Taipei")
PIT_CUTOFF = time(8, 30)
DEFAULT_PUBLICATION_ROOT = ROOT / "output" / "formal_daily_publications"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publication-root",
        type=Path,
        help="持久 publication root；預設為 repository output",
    )
    parser.add_argument(
        "--denominator-path",
        type=Path,
        help="獨立官方 denominator；省略時從當日 pit_denominator 找最新已驗證檔",
    )
    parser.add_argument(
        "--status-root",
        type=Path,
        help="狀態輸出目錄；預設為 publication root/scheduler/pit_sidecar",
    )
    return parser


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.strip())


def _publication_root(override: Path | None) -> Path:
    configured = override or _env_path("FORMAL_DAILY_PUBLICATION_ROOT")
    return (configured or DEFAULT_PUBLICATION_ROOT).expanduser().resolve()


def _status_root(publication_root: Path, override: Path | None) -> Path:
    configured = override or _env_path("FORMAL_DAILY_PIT_SIDECAR_STATUS_ROOT")
    root = (configured or publication_root / "scheduler" / "pit_sidecar").expanduser().resolve()
    try:
        root.relative_to(publication_root)
    except ValueError as error:
        raise ValueError("PIT sidecar status root must be under publication root") from error
    return root


def _write_status(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _coverage_start_from_environment_or_denominator(
    denominator: Mapping[str, object],
) -> date:
    configured = os.environ.get("FORMAL_DAILY_PIT_HISTORY_COVERAGE_START")
    raw = configured.strip() if isinstance(configured, str) and configured.strip() else denominator.get("coverage_start")
    if not isinstance(raw, str):
        raise ValueError("PIT coverage start is missing")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as error:
        raise ValueError("PIT coverage start must be YYYY-MM-DD") from error
    if parsed.isoformat() != raw:
        raise ValueError("PIT coverage start must be YYYY-MM-DD")
    return parsed


def _find_denominator(
    publication_root: Path,
    *,
    target_date: date,
    decision_at: datetime,
    configured: Path | None,
) -> Path:
    if configured is not None:
        path = configured.expanduser().resolve()
        validate_prospective_pit_denominator(path, now=decision_at)
        return path
    candidates = sorted(
        (publication_root / "pit_denominator").glob(
            target_date.isoformat() + "*/denominator.json"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    failures: list[str] = []
    for candidate in candidates:
        try:
            validate_prospective_pit_denominator(candidate, now=decision_at)
            return candidate.resolve()
        except Exception as error:  # noqa: BLE001 - try next immutable run
            failures.append(f"{candidate.name}:{type(error).__name__}")
    detail = ";".join(failures[:3])
    raise ValueError(
        "verified PIT denominator is missing for "
        + target_date.isoformat()
        + (":" + detail if detail else "")
    )


def run_sidecar(
    *,
    publication_root: Path,
    status_root: Path,
    denominator_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, object], int]:
    decision = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = decision.astimezone(TAIPEI)
    status_path = status_root / "latest_status.json"
    runtime_config: dict[str, object] | None = None
    runtime_config_error: str | None = None
    try:
        runtime_config = load_optional_formal_runtime_config(
            role="pit_sidecar_wrapper",
            observed=decision,
        )
    except FormalRuntimeConfigError as error:
        runtime_config_error = str(error)
    base: dict[str, object] = {
        "schema_version": "formal-pit-sidecar-scheduled-status.v1",
        "task": TASK_NAME,
        "producer": "data_module.formal_pit_sector_publisher",
        "consumer": "data_module.portfolio_ml_dataset_assembler._spool_sector_memberships",
        "observed_at": decision.isoformat(),
        "decision_at": decision.isoformat(),
        "decision_timezone": "Asia/Taipei",
        "publication_root": str(publication_root),
        "status_path": str(status_path),
        "capture_policy": "read_existing_archive_captured_before_taipei_0830",
        "same_day_post_cutoff_http_refetch": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "production_action_allowed": False,
        "broker_order_allowed": False,
        "writes_source_database": False,
        "writes_formal_controlled_paths": False,
        "training_started": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
        "formal_runtime_config": (
            runtime_config
            if runtime_config is not None
            else {
                "status": "absent" if runtime_config_error is None else "invalid",
                "environment_variable": FORMAL_RUNTIME_CONFIG_ENV,
                "error": runtime_config_error,
            }
        ),
    }
    if runtime_config_error is not None:
        payload = {
            **base,
            "status": "blocked",
            "blockers": [f"runtime_config_invalid:{runtime_config_error}"],
            "formal_ready": False,
            "formal_consumer_compatible": False,
            "candidate_only": True,
        }
        _write_status(status_path, payload)
        return payload, 2
    if runtime_config is not None and runtime_config.get("activation_status") != "active":
        payload = {
            **base,
            "status": "waiting_for_runtime_config",
            "blockers": [
                "runtime_config_waiting_for_activation:"
                f"{runtime_config.get('activation_trading_day')}"
            ],
            "formal_ready": False,
            "formal_consumer_compatible": False,
            "candidate_only": True,
        }
        _write_status(status_path, payload)
        return payload, 2
    if local.time() < PIT_CUTOFF:
        payload = {
            **base,
            "status": "waiting_for_taipei_cutoff",
            "blockers": [
                "pit_formal_sidecar_waiting_for_taipei_0830_cutoff"
            ],
            "formal_ready": False,
            "formal_consumer_compatible": False,
            "candidate_only": True,
        }
        _write_status(status_path, payload)
        return payload, 2
    try:
        denominator = _find_denominator(
            publication_root,
            target_date=local.date(),
            decision_at=decision,
            configured=denominator_path or _env_path("FORMAL_DAILY_PIT_DENOMINATOR_PATH"),
        )
        denominator_payload = validate_prospective_pit_denominator(
            denominator,
            now=decision,
        )
        coverage_start = _coverage_start_from_environment_or_denominator(
            denominator_payload
        )
        handoff = persist_pit_candidate_history_handoff(
            archive_root=publication_root / "pit_candidate_archive",
            publication_root=publication_root,
            decision_at=decision,
            expected_universe_path=denominator,
            coverage_start=coverage_start,
            calendar=OfficialTradingCalendar(),
        )
        handoff_path = Path(str(handoff["handoff_path"])).resolve()
        result = publish_formal_pit_sector_sidecar(
            handoff_path=handoff_path,
            denominator_path=denominator,
            publication_root=publication_root,
            decision_at=decision,
            now=decision,
        )
        status_text = str(result.get("status", "blocked"))
        raw_blockers = result.get("blockers")
        blockers = (
            [str(item) for item in raw_blockers]
            if isinstance(raw_blockers, list)
            else []
        )
        payload = {
            **base,
            "status": status_text,
            "denominator_path": str(denominator),
            "denominator_file_hash": _file_hash(denominator),
            "handoff_path": str(handoff_path),
            "handoff_file_hash": _file_hash(handoff_path),
            "handoff": handoff,
            "publisher": result,
            "formal_ready": result.get("formal_ready") is True,
            "formal_consumer_compatible": result.get("formal_consumer_compatible") is True,
            "candidate_only": result.get("candidate_only") is True,
            "blockers": blockers,
        }
        _write_status(status_path, payload)
        return payload, 0 if status_text == "formal_source_publication" else 2
    except Exception as error:  # noqa: BLE001 - preserve a concrete retry status
        payload = {
            **base,
            "status": "blocked",
            "blockers": [
                f"pit_formal_sidecar_schedule_failed:{type(error).__name__}:{str(error).splitlines()[0][:220]}"
            ],
            "formal_ready": False,
            "formal_consumer_compatible": False,
            "candidate_only": True,
        }
        _write_status(status_path, payload)
        return payload, 2


def _file_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        publication_root = _publication_root(args.publication_root)
        status_root = _status_root(publication_root, args.status_root)
        payload, exit_code = run_sidecar(
            publication_root=publication_root,
            status_root=status_root,
            denominator_path=args.denominator_path,
        )
    except (OSError, TypeError, ValueError) as error:
        payload = {
            "schema_version": "formal-pit-sidecar-scheduled-status.v1",
            "task": TASK_NAME,
            "status": "blocked",
            "blockers": [
                f"pit_formal_sidecar_configuration_failed:{type(error).__name__}:{str(error).splitlines()[0][:220]}"
            ],
            "formal_ready": False,
            "formal_consumer_compatible": False,
            "candidate_only": True,
            "formal_oos_allowed": False,
            "production_action_allowed": False,
        }
        exit_code = 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
