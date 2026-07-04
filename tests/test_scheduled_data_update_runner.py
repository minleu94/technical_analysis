from __future__ import annotations

from datetime import date

from scripts.scheduled.run_daily_data_update_quick import _scheduled_target_weekday, _weekday_window


def test_scheduled_target_weekday_uses_today_on_weekday() -> None:
    assert _scheduled_target_weekday(date(2026, 7, 3)) == date(2026, 7, 3)


def test_scheduled_target_weekday_falls_back_to_friday_on_weekend() -> None:
    assert _scheduled_target_weekday(date(2026, 7, 4)) == date(2026, 7, 3)
    assert _scheduled_target_weekday(date(2026, 7, 5)) == date(2026, 7, 3)


def test_weekday_window_includes_requested_number_of_weekdays() -> None:
    start_date, end_date = _weekday_window(date(2026, 7, 3), 5)

    assert start_date == "2026-06-29"
    assert end_date == "2026-07-03"
