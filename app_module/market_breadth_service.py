from __future__ import annotations

import numbers
from datetime import date, datetime
from typing import Protocol

import pandas as pd

from app_module.decision_desk_dtos import DecisionDeskQuality, MarketBreadthSummary


class MarketBreadthProvider(Protocol):
    def fetch(self, as_of_date: date) -> pd.DataFrame: ...


class MarketBreadthService:
    """Compute market breadth summary from injected DataFrame/provider."""

    def __init__(self, provider: MarketBreadthProvider | None = None, *, data: pd.DataFrame | None = None):
        if provider is None and data is None:
            raise ValueError("must provide provider or data")
        if provider is not None and data is not None:
            raise ValueError("provider and data cannot both be provided")

        self.provider = provider
        self.data = data

    def build_snapshot(self, as_of_date: date) -> MarketBreadthSummary:
        try:
            if self.provider is not None:
                data = self.provider.fetch(as_of_date)
            else:
                data = self.data
        except Exception as exc:  # noqa: BLE001
            return MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"market_breadth_provider_error:{exc}",),
            )

        if data is None or data.empty:
            return MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("market_breadth_missing",),
            )

        row = self._find_row(data, as_of_date)
        if row is None:
            return MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("market_breadth_missing",),
            )

        row_dict = dict(zip(row.index, row.values))
        parsed = self._parse_counts(row_dict)
        if parsed is None:
            return MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=("market_breadth_invalid_counts",),
                advancing=None,
                declining=None,
                unchanged=None,
            )

        advancing, declining, unchanged = parsed
        breadth_ratio_bp = self._calc_breadth_ratio_bp(advancing, declining)
        return MarketBreadthSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            breadth_ratio_bp=breadth_ratio_bp,
            advancing=advancing,
            declining=declining,
            unchanged=unchanged,
        )

    def _find_row(self, data: pd.DataFrame, target_date: date) -> pd.Series | None:
        candidate_columns = ("as_of_date", "date", "trade_date", "timestamp", "time")
        for column in candidate_columns:
            if column not in data.columns:
                continue
            parsed_column = self._parse_date_series(data[column])
            if parsed_column is None:
                continue
            matched = parsed_column == target_date
            if not bool(matched.any()):
                continue
            return data.loc[matched].iloc[0]
        return None

    def _parse_date_series(self, values: pd.Series) -> pd.Series | None:
        parsed: list[date | None] = []
        for item in values:
            parsed.append(self._parse_date_value(item))
        if all(item is None for item in parsed):
            return None
        return pd.Series(parsed, index=values.index)

    def _parse_date_value(self, value: object) -> date | None:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, (int, float)):
            raw = str(int(value))
            if len(raw) == 8 and raw.isdigit():
                return self._parse_date_str(raw, "%Y%m%d")
            return None
        if isinstance(value, str):
            return (
                self._parse_date_str(value, "%Y-%m-%d")
                or self._parse_date_str(value, "%Y%m%d")
            )
        return None

    @staticmethod
    def _parse_date_str(raw: str, fmt: str) -> date | None:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            return None

    def _parse_counts(self, row: dict[str, object]) -> tuple[int, int, int | None] | None:
        advancing = self._read_int(row, ("advancing", "advancing_count", "adv"))
        declining = self._read_int(row, ("declining", "declining_count", "dec"))
        if advancing is None or declining is None:
            return None
        unchanged = self._read_int(row, ("unchanged", "unchanged_count"))
        return advancing, declining, unchanged

    def _read_int(self, row: dict[str, object], names: tuple[str, ...]) -> int | None:
        for name in names:
            if name not in row:
                continue
            raw = row[name]
            if raw is None:
                continue
            if isinstance(raw, bool):
                continue
            if isinstance(raw, numbers.Integral):
                return int(raw)
            if isinstance(raw, numbers.Real):
                try:
                    real_value = float(raw)
                except (TypeError, ValueError):
                    continue
                if not real_value.is_integer():
                    continue
                try:
                    return int(real_value)
                except (TypeError, ValueError, OverflowError):
                    continue
            if isinstance(raw, str) and raw.strip().isdigit():
                try:
                    return int(raw.strip())
                except ValueError:
                    continue
        return None

    def _calc_breadth_ratio_bp(self, advancing: int, declining: int) -> int:
        total = advancing + declining
        if total <= 0:
            return 0
        return (advancing * 10000) // total
