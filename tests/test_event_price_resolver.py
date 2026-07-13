from __future__ import annotations

from decimal import Decimal

from app_module.event_price_resolver import EventPriceObservation, EventPriceResolver


def _prices() -> tuple[EventPriceObservation, ...]:
    return (
        EventPriceObservation("2026-07-09", Decimal("990")),
        EventPriceObservation("2026-07-10", Decimal("1000")),
        EventPriceObservation("2026-07-13", Decimal("1010")),
    )


def test_weekend_uses_previous_visible_trading_day() -> None:
    result = EventPriceResolver().resolve(
        decision_date="2026-07-12",
        data_as_of_date="2026-07-12",
        prices=_prices(),
    )

    assert result.price_date == "2026-07-10"
    assert result.close == Decimal("1000")
    assert result.fallback_reason == "previous_trading_day"
    assert result.quality == "degraded"


def test_future_price_is_never_used() -> None:
    result = EventPriceResolver().resolve(
        decision_date="2026-07-13",
        data_as_of_date="2026-07-10",
        prices=_prices(),
    )

    assert result.price_date == "2026-07-10"
    assert result.fallback_reason == "data_as_of_boundary"


def test_no_visible_price_fails_closed() -> None:
    result = EventPriceResolver().resolve(
        decision_date="2026-07-08",
        data_as_of_date="2026-07-08",
        prices=_prices(),
    )

    assert result.price_date is None
    assert result.close is None
    assert result.fallback_reason == "no_visible_price"
    assert result.quality == "missing"
