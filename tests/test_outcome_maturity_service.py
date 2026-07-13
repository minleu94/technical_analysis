from __future__ import annotations

from app_module.outcome_maturity_service import OutcomeMaturityService


TRADING_DATES = (
    "2026-07-06",
    "2026-07-07",
    "2026-07-08",
    "2026-07-09",
    "2026-07-10",
    "2026-07-13",
    "2026-07-14",
)


def test_five_day_maturity_uses_fifth_future_trading_day() -> None:
    result = OutcomeMaturityService().evaluate(
        event_date="2026-07-06",
        window_days=5,
        trading_dates=TRADING_DATES,
        as_of_date="2026-07-10",
    )

    assert result.expected_trading_date == "2026-07-13"
    assert result.status == "pending"
    assert result.remaining_trading_days == 1


def test_mature_window_is_ready() -> None:
    result = OutcomeMaturityService().evaluate(
        event_date="2026-07-06",
        window_days=5,
        trading_dates=TRADING_DATES,
        as_of_date="2026-07-13",
    )

    assert result.status == "ready"
    assert result.remaining_trading_days == 0


def test_unknown_future_calendar_is_waiting_for_calendar() -> None:
    result = OutcomeMaturityService().evaluate(
        event_date="2026-07-10",
        window_days=20,
        trading_dates=TRADING_DATES,
        as_of_date="2026-07-14",
    )

    assert result.expected_trading_date is None
    assert result.status == "waiting_for_calendar"
    assert result.remaining_trading_days == 18
