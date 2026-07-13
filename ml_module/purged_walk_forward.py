"""Purged expanding walk-forward split with test embargo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass(frozen=True)
class MLTimeWindowRow:
    row_id: str
    decision_date: str
    label_end_date: str


@dataclass(frozen=True)
class PurgedWalkForwardFold:
    fold_id: str
    train_rows: tuple[MLTimeWindowRow, ...]
    test_rows: tuple[MLTimeWindowRow, ...]
    test_start: str
    test_end: str
    purge_trading_days: int
    embargo_trading_days: int


class PurgedWalkForwardSplitter:
    def __init__(
        self,
        *,
        minimum_train_dates: int,
        test_date_count: int,
        purge_trading_days: int | None = None,
        embargo_trading_days: int | None = None,
        **legacy_calendar_parameters: int,
    ) -> None:
        if legacy_calendar_parameters:
            names = ", ".join(sorted(legacy_calendar_parameters))
            raise TypeError(
                f"ambiguous calendar parameters ({names}); use purge_trading_days "
                "and embargo_trading_days"
            )
        if purge_trading_days is None or embargo_trading_days is None:
            raise TypeError(
                "purge_trading_days and embargo_trading_days are required"
            )
        if minimum_train_dates <= 0:
            raise ValueError("minimum_train_dates must be positive")
        if test_date_count <= 0:
            raise ValueError("test_date_count must be positive")
        if purge_trading_days < 0 or embargo_trading_days < 0:
            raise ValueError(
                "purge_trading_days and embargo_trading_days must be non-negative"
            )
        self.minimum_train_dates = minimum_train_dates
        self.test_date_count = test_date_count
        self.purge_trading_days = purge_trading_days
        self.embargo_trading_days = embargo_trading_days

    def split(self, rows: Iterable[MLTimeWindowRow]) -> tuple[PurgedWalkForwardFold, ...]:
        ordered = tuple(sorted(rows, key=lambda row: (row.decision_date, row.row_id)))
        dates = tuple(sorted({row.decision_date for row in ordered}))
        folds: list[PurgedWalkForwardFold] = []
        start_index = self.minimum_train_dates
        while start_index + self.test_date_count <= len(dates):
            test_dates = dates[start_index : start_index + self.test_date_count]
            test_start = test_dates[0]
            test_end = test_dates[-1]
            purge_boundary_index = max(0, start_index - self.purge_trading_days)
            eligible_train_dates = frozenset(dates[:purge_boundary_index])
            train = tuple(
                row
                for row in ordered
                if row.decision_date in eligible_train_dates
                and _date(row.label_end_date) < _date(test_start)
            )
            test = tuple(row for row in ordered if row.decision_date in test_dates)
            if train and test:
                folds.append(
                    PurgedWalkForwardFold(
                        fold_id=f"fold-{len(folds) + 1:03d}",
                        train_rows=train,
                        test_rows=test,
                        test_start=test_start,
                        test_end=test_end,
                        purge_trading_days=self.purge_trading_days,
                        embargo_trading_days=self.embargo_trading_days,
                    )
                )
            start_index += self.test_date_count + self.embargo_trading_days
        return tuple(folds)


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])
