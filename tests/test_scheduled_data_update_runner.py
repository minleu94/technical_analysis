from __future__ import annotations

from datetime import date, timezone
import json

from scripts.batch_update_daily_data import _format_update_diagnostic
from scripts.scheduled import run_daily_data_update_quick as runner
from scripts.scheduled.run_daily_data_update_quick import (
    _scheduled_target_weekday,
    _technical_is_current,
    _tpex_warning_messages,
    _twse_skip_warning_messages,
    _weekday_window,
)


def test_update_diagnostic_is_ascii_safe_for_windows_stdout() -> None:
    diagnostic = {
        "date": "2026-07-10",
        "outcome": "no_data",
        "reason_code": "twse_official_no_data",
        "request_attempts": [
            {
                "request_type": "ALLBUT0999",
                "http_status": 200,
                "api_status": "很抱歉，沒有符合條件的資料!",
            }
        ],
    }

    line = _format_update_diagnostic(diagnostic)

    line.encode("cp1252")
    assert json.loads(line.removeprefix("UPDATE_DIAGNOSTIC ")) == diagnostic


def test_scheduled_target_weekday_uses_today_on_weekday() -> None:
    assert _scheduled_target_weekday(date(2026, 7, 3)) == date(2026, 7, 3)


def test_scheduled_target_weekday_falls_back_to_friday_on_weekend() -> None:
    assert _scheduled_target_weekday(date(2026, 7, 4)) == date(2026, 7, 3)
    assert _scheduled_target_weekday(date(2026, 7, 5)) == date(2026, 7, 3)


def test_weekday_window_includes_requested_number_of_weekdays() -> None:
    start_date, end_date = _weekday_window(date(2026, 7, 3), 5)

    assert start_date == "2026-06-29"
    assert end_date == "2026-07-03"


def test_tpex_warning_messages_report_missing_failed_dates() -> None:
    warnings = _tpex_warning_messages(
        {
            "failed_dates": ["20260706"],
            "requested_dates": ["20260706"],
            "skipped_dates": [],
        }
    )

    assert warnings == ["TPEX 每日股價缺少日期：20260706"]


def test_twse_skip_warning_messages_report_explicit_no_data_dates() -> None:
    warnings = _twse_skip_warning_messages({"no_data_skipped_dates": ["2026-07-10"]})

    assert warnings == ["TWSE 官方無交易資料日（休市／颱風等），已略過日期：2026-07-10"]


def test_twse_skip_warning_messages_ignore_existing_file_skips() -> None:
    assert _twse_skip_warning_messages({"skipped_dates": ["2026-07-10"]}) == []


def test_technical_is_not_current_when_latest_date_coverage_lags() -> None:
    current, message = _technical_is_current(
        {
            "daily_data": {"latest_date": "2026-07-06"},
            "technical_indicators": {"latest_date": "2026-07-06"},
        },
        {
            "success": True,
            "is_current": False,
            "daily_latest_date": "20260706",
            "eligible_stock_count": 2,
            "covered_stock_count": 1,
        },
    )

    assert current is False
    assert "1/2" in message


def test_quick_update_publishes_running_before_work_and_terminal_metadata(
    tmp_path, monkeypatch
) -> None:
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    status_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    log_path = output_root / "scheduled" / "data_update_quick" / "run.log"
    observed = {"running": False}

    class _FakeUpdateService:
        def __init__(self, _config) -> None:
            pass

        def check_data_overview(self):
            if not observed["running"]:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                assert payload["status"] == "running"
                assert payload["process_id"] > 0
                observed["running"] = True
            return {
                "success": True,
                "daily_data": {"latest_date": "2026-07-03"},
                "technical_indicators": {"latest_date": "2026-07-03"},
            }

        def _success(self, *_args, **_kwargs):
            return {"success": True}

        update_daily = _success
        update_tpex_daily_price_range = _success
        sync_source_to_sqlite = _success
        update_market = _success
        update_industry = _success
        update_broker_branch = _success

        def check_technical_indicator_latest_coverage(self):
            return {"success": True, "is_current": True}

    monkeypatch.setattr(runner, "UpdateService", _FakeUpdateService)
    clock = iter(
        (
            runner.datetime(2026, 7, 3, 4, 20, tzinfo=timezone.utc),
            runner.datetime(2026, 7, 3, 4, 21, tzinfo=timezone.utc),
        )
    )
    monkeypatch.setattr(
        runner,
        "scheduled_now",
        lambda: next(clock),
    )

    exit_code = runner.main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--status-path",
            str(status_path),
            "--log-path",
            str(log_path),
        ]
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert observed["running"] is True
    assert payload["status"] == "passed"
    assert payload["run_id"].startswith("20260703-")
    assert payload["started_at"] < payload["completed_at"]
    assert payload["checked_at"] == payload["completed_at"]
    history_path = status_path.parent / "history.jsonl"
    history_records = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["status"] for record in history_records] == ["running", "passed"]
    assert all(record["run_id"] == payload["run_id"] for record in history_records)
