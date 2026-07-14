"""Conservative observed-history universe policy for Terra V0."""

from __future__ import annotations

from collections import defaultdict

from data_module.ml_historical_snapshot_provider import HistoricalPriceObservation


class ConservativeObservedHistoryUniverse:
    """Uses observed decision-time history, never an inferred survivor universe."""

    def __init__(self, minimum_observed_history_days: int = 252) -> None:
        if minimum_observed_history_days != 252:
            raise ValueError("conservative_observed_history requires 252 trading days")
        self.minimum_observed_history_days = minimum_observed_history_days

    def select(
        self,
        prices: tuple[HistoricalPriceObservation, ...],
        *,
        decision_date: str,
    ) -> tuple[tuple[str, ...], dict[str, int]]:
        observed_dates: dict[str, set[str]] = defaultdict(set)
        for row in prices:
            if row.trading_date < decision_date:
                observed_dates[row.symbol].add(row.trading_date)
        selected = tuple(
            symbol for symbol, dates in sorted(observed_dates.items())
            if len(dates) >= self.minimum_observed_history_days
        )
        diagnostics = {
            "listing_date_unavailable": len(observed_dates),
            "delisting_date_unavailable": len(observed_dates),
            "insufficient_observed_history": sum(
                len(dates) < self.minimum_observed_history_days for dates in observed_dates.values()
            ),
        }
        return selected, diagnostics
