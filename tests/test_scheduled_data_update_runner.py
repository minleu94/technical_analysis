from __future__ import annotations

from datetime import date

from scripts.scheduled.run_daily_data_update_quick import (
    _scheduled_target_weekday,
    _technical_is_current,
    _tpex_warning_messages,
    _twse_skip_warning_messages,
    _weekday_window,
)


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
