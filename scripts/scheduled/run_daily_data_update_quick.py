from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_module.update_service import UpdateService
from app_module.update_status_history import append_update_status_history
from data_module.config import TWStockConfig
from data_module.official_trading_calendar import (
    OfficialTradingCalendar,
    OfficialTradingCalendarError,
)
from scripts.scheduled.scheduled_clock import scheduled_now


StepAction = Callable[[], dict[str, Any]]


def _parse_date(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text[:8], fmt)
        except ValueError:
            continue
    return None


def _calendar_records_for_window(
    reference_date: date,
    days: int,
    *,
    calendar: OfficialTradingCalendar | None = None,
) -> list[dict[str, Any]]:
    resolver = calendar or OfficialTradingCalendar(
        calendar_cache_path=_default_calendar_cache_path(),
    )
    return resolver.get_recent_official_trading_days(
        reference_date,
        max(1, int(days)),
        include_reference=True,
        allow_online_probe=True,
    )


def _scheduled_target_weekday(
    today: date,
    calendar: OfficialTradingCalendar | None = None,
) -> date:
    """Compatibility name for the latest official session selector."""

    records = _calendar_records_for_window(today, 1, calendar=calendar)
    return date.fromisoformat(str(records[-1]["date_str"]))


def _weekday_window(
    end_day: date,
    days: int,
    calendar: OfficialTradingCalendar | None = None,
) -> tuple[str, str]:
    """Compatibility name for an official-calendar update window."""

    records = _calendar_records_for_window(end_day, days, calendar=calendar)
    return str(records[0]["date_str"]), str(records[-1]["date_str"])


def _serializable_calendar_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in record.items() if key != "date"}
        for record in records
    ]


def _default_calendar_cache_path() -> Path | None:
    """Use the existing immutable official-calendar cache when available."""

    path = REPO_ROOT / "output" / "paper_execution_eod_replay" / "calendar_cache"
    return path if path.is_dir() else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _append_history_safely(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """保存 append-only history；history 寫入失敗不掩蓋主要更新結果。"""

    try:
        return append_update_status_history(path, payload)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Unable to append data update history: %s", exc)
        return {
            "appended": False,
            "duplicate": False,
            "path": str(path),
            "error": f"{type(exc).__name__}:{exc}",
        }


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


def _step_payload(name: str, result: dict[str, Any], warning: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "status": "warning" if warning else "passed" if result.get("success", True) else "failed",
        "message": result.get("message", ""),
        "result": result,
    }


def _tpex_warning_messages(result: dict[str, Any]) -> list[str]:
    messages = [str(item) for item in result.get("warnings", []) if str(item).strip()]
    failed_dates = sorted({str(item) for item in result.get("failed_dates", []) if str(item).strip()})
    if failed_dates:
        messages.append(f"TPEX 每日股價缺少日期：{', '.join(failed_dates)}")
    return list(dict.fromkeys(messages))


def _twse_skip_warning_messages(result: dict[str, Any]) -> list[str]:
    skipped_dates = sorted(
        {
            str(item)
            for item in result.get("no_data_skipped_dates", [])
            if str(item).strip()
        }
    )
    if not skipped_dates:
        return []
    return [f"TWSE 官方無交易資料日（休市／颱風等），已略過日期：{', '.join(skipped_dates)}"]


def _run_step(
    *,
    steps: list[dict[str, Any]],
    name: str,
    action: StepAction,
    warning_only: bool = False,
) -> dict[str, Any] | None:
    logging.info("Starting step: %s", name)
    result = action()
    ok = bool(result.get("success", True))
    if not ok and warning_only:
        logging.warning("Step completed with warning: %s: %s", name, result.get("message", ""))
        steps.append(_step_payload(name, result, warning=True))
        return None
    steps.append(_step_payload(name, result))
    if not ok:
        logging.error("Step failed: %s: %s", name, result.get("message", ""))
        return result
    logging.info("Step passed: %s", name)
    return None


def _technical_is_current(
    status: dict[str, Any],
    coverage: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    if coverage and coverage.get("success") and not coverage.get("is_current", True):
        covered = coverage.get("covered_stock_count", 0)
        eligible = coverage.get("eligible_stock_count", 0)
        latest = coverage.get("daily_latest_date") or "latest daily date"
        return False, f"technical coverage lagging at {latest}: {covered}/{eligible}"

    daily_latest = _parse_date((status.get("daily_data") or {}).get("latest_date"))
    technical_latest = _parse_date((status.get("technical_indicators") or {}).get("latest_date"))
    if daily_latest is not None and technical_latest is not None and technical_latest >= daily_latest:
        return True, f"technical indicators current at {technical_latest.strftime('%Y-%m-%d')}"
    return False, ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run scheduled baldr quick data update.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--window-weekdays", type=int, default=10)
    parser.add_argument("--daily-delay-seconds", type=float, default=0.5)
    parser.add_argument("--tpex-delay-seconds", type=float, default=0.5)
    parser.add_argument("--broker-delay-seconds", type=float, default=0.5)
    parser.add_argument("--status-path")
    parser.add_argument(
        "--history-path",
        help="append-only JSONL history path; defaults beside --status-path",
    )
    parser.add_argument("--log-path")
    parser.add_argument(
        "--enable-technical-process-pool",
        action="store_true",
        help=(
            "explicitly enable bounded technical-indicator workers for this run; "
            "default remains serial and parent-only"
        ),
    )
    parser.add_argument("--technical-process-pool-workers", type=int)
    parser.add_argument("--technical-process-pool-max-in-flight", type=int)
    parser.add_argument("--technical-process-pool-max-retries", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_root)
    run_root = output_root / "scheduled" / "data_update_quick"
    run_now = scheduled_now()
    run_date = run_now.date()
    today_key = run_date.strftime("%Y%m%d")
    status_path = Path(args.status_path) if args.status_path else run_root / "latest_status.json"
    history_path = (
        Path(args.history_path)
        if args.history_path
        else status_path.parent / "history.jsonl"
    )
    log_path = Path(args.log_path) if args.log_path else run_root / f"{today_key}_data_update_quick.log"
    _setup_logging(log_path)

    config = TWStockConfig(
        data_root=Path(args.data_root),
        output_root=output_root,
        technical_process_pool_enabled=bool(args.enable_technical_process_pool),
    )
    if args.technical_process_pool_workers is not None:
        config.technical_process_pool_workers = args.technical_process_pool_workers
    if args.technical_process_pool_max_in_flight is not None:
        config.technical_process_pool_max_in_flight = args.technical_process_pool_max_in_flight
    if args.technical_process_pool_max_retries is not None:
        config.technical_process_pool_max_retries = args.technical_process_pool_max_retries

    calendar = OfficialTradingCalendar(
        db_path=config.db_file,
        calendar_cache_path=_default_calendar_cache_path(),
    )
    calendar_records: list[dict[str, Any]] = []
    try:
        if args.start_date and args.end_date:
            start_date = args.start_date
            end_date = args.end_date
            calendar_records = calendar.require_trading_days_in_range(
                date.fromisoformat(start_date),
                date.fromisoformat(end_date),
                allow_online_probe=True,
            )
        else:
            calendar_records = _calendar_records_for_window(
                run_date,
                max(1, args.window_weekdays),
                calendar=calendar,
            )
            start_date = str(calendar_records[0]["date_str"])
            end_date = str(calendar_records[-1]["date_str"])
    except (OfficialTradingCalendarError, ValueError) as exc:
        completed_at = scheduled_now()
        failure_payload = {
            "task": "baldr-data-update-quick-daily",
            "status": "failed",
            "run_id": f"{today_key}-{os.getpid()}",
            "started_at": run_now.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "checked_at": completed_at.isoformat(timespec="seconds"),
            "process_id": os.getpid(),
            "data_root": str(config.data_root),
            "output_root": str(config.output_root),
            "start_date": args.start_date,
            "end_date": args.end_date,
            "calendar_resolution": [],
            "steps": [],
            "warnings": [],
            "errors": [f"official_trading_calendar_unavailable:{type(exc).__name__}:{exc}"],
            "writes_market_data_db": False,
            "writes_evidence_db": False,
            "auto_trading": False,
            "auto_lifecycle_action": False,
            "history_path": str(history_path),
        }
        failure_payload["history"] = _append_history_safely(history_path, failure_payload)
        _write_json(status_path, failure_payload)
        logging.error(failure_payload["errors"][0])
        return 1

    service = UpdateService(config)
    steps: list[dict[str, Any]] = []
    warnings: list[str] = []
    failed: dict[str, Any] | None = None

    logging.info("Scheduled quick data update window: %s to %s", start_date, end_date)

    run_id = f"{today_key}-{os.getpid()}"
    running_payload = {
        "task": "baldr-data-update-quick-daily",
        "status": "running",
        "run_id": run_id,
        "started_at": run_now.isoformat(timespec="seconds"),
        "process_id": os.getpid(),
        "data_root": str(config.data_root),
        "output_root": str(config.output_root),
        "start_date": start_date,
        "end_date": end_date,
        "calendar_resolution": _serializable_calendar_records(calendar_records),
        "log_path": str(log_path),
        "steps": [],
        "warnings": [],
        "errors": [],
        "writes_market_data_db": True,
        "writes_evidence_db": False,
        "auto_trading": False,
        "auto_lifecycle_action": False,
        "history_path": str(history_path),
        "technical_process_pool_enabled": config.technical_process_pool_enabled,
        "technical_process_pool_workers": config.technical_process_pool_workers,
        "technical_process_pool_max_in_flight": config.technical_process_pool_max_in_flight,
        "technical_process_pool_max_retries": config.technical_process_pool_max_retries,
    }
    _write_json(status_path, running_payload)
    running_payload["history"] = _append_history_safely(history_path, running_payload)
    _write_json(status_path, running_payload)

    failed = _run_step(steps=steps, name="check_overview_before", action=service.check_data_overview)
    if failed is None:
        failed = _run_step(
            steps=steps,
            name="update_twse_daily_prices",
            action=lambda: service.update_daily(start_date, end_date, delay_seconds=args.daily_delay_seconds),
        )
    if failed is None:
        failed = _run_step(
            steps=steps,
            name="update_tpex_daily_prices",
            action=lambda: service.update_tpex_daily_price_range(
                start_date,
                end_date,
                delay_seconds=args.tpex_delay_seconds,
                force_refresh=False,
                sync_to_sqlite=False,
                break_on_repeated_source_date=False,
                twse_no_data_dates=next((s["result"].get("no_data_skipped_dates", []) for s in steps if s["name"] == "update_twse_daily_prices"), []),
            ),
            warning_only=True,
        )
    if failed is None:
        failed = _run_step(
            steps=steps,
            name="sync_daily_prices_to_sqlite",
            action=lambda: service.sync_source_to_sqlite("daily_price_files", start_date, end_date),
        )
    if failed is None:
        failed = _run_step(steps=steps, name="update_market_index", action=lambda: service.update_market(start_date, end_date))
    if failed is None:
        failed = _run_step(steps=steps, name="sync_market_index_to_sqlite", action=lambda: service.sync_source_to_sqlite("market_index"))
    if failed is None:
        failed = _run_step(steps=steps, name="update_industry_index", action=lambda: service.update_industry(start_date, end_date))
    if failed is None:
        failed = _run_step(steps=steps, name="sync_industry_index_to_sqlite", action=lambda: service.sync_source_to_sqlite("industry_index"))
    if failed is None:
        failed = _run_step(
            steps=steps,
            name="update_broker_branch",
            action=lambda: service.update_broker_branch(start_date, end_date, delay_seconds=args.broker_delay_seconds),
        )
    if failed is None:
        failed = _run_step(
            steps=steps,
            name="sync_broker_branch_to_sqlite",
            action=lambda: service.sync_source_to_sqlite("broker_branch_files", start_date, end_date),
        )
    if failed is None:
        status = service.check_data_overview()
        coverage = service.check_technical_indicator_latest_coverage()
        current, message = _technical_is_current(status, coverage)
        if current:
            steps.append(
                {
                    "name": "calculate_technical_indicators",
                    "status": "skipped",
                    "message": message,
                    "result": {"success": True, "skipped": True, "skip_reason": "technical_indicators_current"},
                }
            )
            logging.info(message)
        else:
            failed = _run_step(
                steps=steps,
                name="calculate_technical_indicators",
                action=lambda: service.calculate_technical_indicators(
                    target_stock=None,
                    force_all=False,
                    start_date=None,
                    progress_callback=None,
                    incremental_lookback_days=120,
                    technical_process_pool=config.technical_process_pool_enabled,
                    technical_process_pool_workers=config.technical_process_pool_workers,
                    technical_process_pool_max_in_flight=config.technical_process_pool_max_in_flight,
                    technical_process_pool_max_retries=config.technical_process_pool_max_retries,
                ),
            )
    if failed is None:
        failed = _run_step(steps=steps, name="check_overview_after", action=service.check_data_overview)

    for step in steps:
        if step.get("status") == "warning" and step.get("message"):
            warnings.append(str(step["message"]))
        if step.get("name") == "update_twse_daily_prices":
            result = step.get("result")
            if isinstance(result, dict):
                warnings.extend(_twse_skip_warning_messages(result))
        if step.get("name") == "update_tpex_daily_prices":
            result = step.get("result")
            if isinstance(result, dict):
                warnings.extend(_tpex_warning_messages(result))
    warnings = list(dict.fromkeys(warnings))
    final_status = "failed" if failed is not None else "passed_with_warnings" if warnings else "passed"
    completed_at = scheduled_now()
    payload = {
        "task": "baldr-data-update-quick-daily",
        "status": final_status,
        "run_id": run_id,
        "started_at": run_now.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "process_id": os.getpid(),
        "checked_at": completed_at.isoformat(timespec="seconds"),
        "data_root": str(config.data_root),
        "output_root": str(config.output_root),
        "start_date": start_date,
        "end_date": end_date,
        "calendar_resolution": _serializable_calendar_records(calendar_records),
        "log_path": str(log_path),
        "steps": steps,
        "warnings": warnings,
        "errors": [] if failed is None else [failed.get("message", "scheduled quick data update failed")],
        "writes_market_data_db": True,
        "writes_evidence_db": False,
        "auto_trading": False,
        "auto_lifecycle_action": False,
        "history_path": str(history_path),
        "technical_process_pool_enabled": config.technical_process_pool_enabled,
        "technical_process_pool_workers": config.technical_process_pool_workers,
        "technical_process_pool_max_in_flight": config.technical_process_pool_max_in_flight,
        "technical_process_pool_max_retries": config.technical_process_pool_max_retries,
    }
    payload["history"] = _append_history_safely(history_path, payload)
    _write_json(status_path, payload)
    logging.info("Scheduled quick data update finished with status=%s", final_status)
    return 1 if failed is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
