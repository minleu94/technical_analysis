"""Purged expanding walk-forward split with test embargo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
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
    purge_days: int
    embargo_days: int


class PurgedWalkForwardSplitter:
    def __init__(
        self,
        *,
        minimum_train_dates: int,
        test_date_count: int,
        purge_days: int,
        embargo_days: int,
    ) -> None:
        if minimum_train_dates <= 0:
            raise ValueError("minimum_train_dates must be positive")
        if test_date_count <= 0:
            raise ValueError("test_date_count must be positive")
        if purge_days < 0 or embargo_days < 0:
            raise ValueError("purge_days and embargo_days must be non-negative")
        self.minimum_train_dates = minimum_train_dates
        self.test_date_count = test_date_count
        self.purge_days = purge_days
        self.embargo_days = embargo_days

    def split(self, rows: Iterable[MLTimeWindowRow]) -> tuple[PurgedWalkForwardFold, ...]:
        ordered = tuple(sorted(rows, key=lambda row: (row.decision_date, row.row_id)))
        dates = tuple(sorted({row.decision_date for row in ordered}))
        folds: list[PurgedWalkForwardFold] = []
        start_index = self.minimum_train_dates
        while start_index + self.test_date_count <= len(dates):
            test_dates = dates[start_index : start_index + self.test_date_count]
            test_start = test_dates[0]
            test_end = test_dates[-1]
            purge_cutoff = _date(test_start) - timedelta(days=self.purge_days)
            train = tuple(
                row
                for row in ordered
                if _date(row.decision_date) < purge_cutoff
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
                        purge_days=self.purge_days,
                        embargo_days=self.embargo_days,
                    )
                )
            start_index += self.test_date_count + self.embargo_days
        return tuple(folds)


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])
