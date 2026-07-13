"""因果 event-price 交易日解析器。"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class EventPriceObservation:
    trading_date: str
    close: Decimal


@dataclass(frozen=True)
class EventPriceResolution:
    price_date: str | None
    close: Decimal | None
    fallback_reason: str | None
    quality: str


class EventPriceResolver:
    """只選 decision / data-as-of 邊界當下已可見的最近交易日。"""

    def resolve(
        self,
        *,
        decision_date: str,
        data_as_of_date: str | None,
        prices: tuple[EventPriceObservation, ...],
    ) -> EventPriceResolution:
        boundary = min(decision_date, data_as_of_date or decision_date)
        ordered = tuple(sorted(prices, key=lambda item: item.trading_date))
        keys = tuple(item.trading_date for item in ordered)
        index = bisect_right(keys, boundary) - 1
        if index < 0:
            return EventPriceResolution(None, None, "no_visible_price", "missing")
        selected = ordered[index]
        if selected.trading_date == decision_date:
            reason = None
            quality = "observed"
        elif data_as_of_date is not None and data_as_of_date < decision_date:
            reason = "data_as_of_boundary"
            quality = "degraded"
        else:
            reason = "previous_trading_day"
            quality = "degraded"
        return EventPriceResolution(
            price_date=selected.trading_date,
            close=selected.close,
            fallback_reason=reason,
            quality=quality,
        )
