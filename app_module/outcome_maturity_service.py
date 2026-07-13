"""Forward outcome 的交易日成熟度計算。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutcomeMaturity:
    expected_trading_date: str | None
    status: str
    remaining_trading_days: int


class OutcomeMaturityService:
    def evaluate(
        self,
        *,
        event_date: str,
        window_days: int,
        trading_dates: tuple[str, ...],
        as_of_date: str,
    ) -> OutcomeMaturity:
        if window_days <= 0:
            raise ValueError("window_days must be positive")
        ordered = tuple(sorted(set(trading_dates)))
        future = tuple(date for date in ordered if date > event_date)
        observed = sum(1 for date in future if date <= as_of_date)
        remaining = max(window_days - observed, 0)
        expected = future[window_days - 1] if len(future) >= window_days else None
        if expected is None:
            status = "waiting_for_calendar"
        elif expected <= as_of_date:
            status = "ready"
        else:
            status = "pending"
        return OutcomeMaturity(expected, status, remaining)
