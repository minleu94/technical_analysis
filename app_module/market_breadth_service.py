from __future__ import annotations

import numbers
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
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
        snapshot_date = self._parse_snapshot_date(row_dict, as_of_date)
        quality = self._parse_quality(row_dict)
        warnings = self._parse_warnings(row_dict)
        parsed = self._parse_counts(row_dict)
        if parsed is None:
            return MarketBreadthSummary(
                as_of_date=snapshot_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=warnings + ("market_breadth_invalid_counts",),
                advancing=None,
                declining=None,
                unchanged=None,
            )

        advancing, declining, unchanged = parsed
        breadth_ratio_bp = self._calc_breadth_ratio_bp(advancing, declining)
        return MarketBreadthSummary(
            as_of_date=snapshot_date,
            quality=quality,
            warnings=warnings,
            breadth_ratio_bp=breadth_ratio_bp,
            advancing=advancing,
            declining=declining,
            unchanged=unchanged,
            meta=self._parse_meta(row_dict),
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
        if len(data) == 1:
            return data.iloc[0]
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

    def _parse_snapshot_date(self, row: dict[str, object], default: date) -> date:
        for name in ("as_of_date", "date", "trade_date", "日期"):
            if name not in row:
                continue
            parsed = self._parse_date_value(row[name])
            if parsed is not None:
                return parsed
        return default

    @staticmethod
    def _parse_quality(row: dict[str, object]) -> DecisionDeskQuality:
        raw = row.get("quality")
        if raw is None:
            return DecisionDeskQuality.OBSERVED
        try:
            return DecisionDeskQuality(str(raw))
        except ValueError:
            return DecisionDeskQuality.DEGRADED

    @staticmethod
    def _parse_warnings(row: dict[str, object]) -> tuple[str, ...]:
        raw = row.get("warnings")
        if raw is None:
            return ()
        if isinstance(raw, str):
            if not raw.strip():
                return ()
            return tuple(item for item in raw.split("|") if item)
        if isinstance(raw, (tuple, list, set)):
            return tuple(str(item) for item in raw)
        return (str(raw),)

    @staticmethod
    def _parse_meta(row: dict[str, object]) -> dict[str, object]:
        excluded = {
            "as_of_date",
            "date",
            "trade_date",
            "timestamp",
            "time",
            "日期",
            "quality",
            "warnings",
            "advancing",
            "advancing_count",
            "adv",
            "declining",
            "declining_count",
            "dec",
            "unchanged",
            "unchanged_count",
        }
        meta: dict[str, object] = {}
        for key, value in row.items():
            if key in excluded or pd.isna(value):
                continue
            if isinstance(value, numbers.Integral):
                meta[key] = int(value)
            elif isinstance(value, numbers.Real):
                real_value = float(value)
                meta[key] = int(real_value) if real_value.is_integer() else real_value
            else:
                meta[key] = value
        return meta


class SQLiteDailyPriceMarketBreadthProvider:
    """Read-only provider that derives market breadth from SQLite daily_prices."""

    def __init__(self, db_path: str | Path, *, lookback_days: int = 60):
        self.db_path = Path(db_path)
        self.lookback_days = lookback_days

    def fetch(self, as_of_date: date) -> pd.DataFrame:
        if not self.db_path.exists():
            return pd.DataFrame()

        target_key = as_of_date.strftime("%Y%m%d")
        with sqlite3.connect(self.db_path) as conn:
            date_rows = pd.read_sql_query(
                """
                SELECT DISTINCT 日期
                FROM daily_prices
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') <= ?
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                LIMIT ?
                """,
                conn,
                params=(target_key, self.lookback_days + 1),
            )
            if date_rows.empty:
                return pd.DataFrame()

            normalized_dates = [
                str(item).replace("-", "").replace("/", "")
                for item in date_rows["日期"].tolist()
            ]
            actual_key = normalized_dates[0]
            placeholders = ",".join("?" for _ in normalized_dates)
            prices = pd.read_sql_query(
                f"""
                SELECT 日期, 證券代號, 收盤價, 漲跌價差, 成交股數
                FROM daily_prices
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') IN ({placeholders})
                """,
                conn,
                params=tuple(normalized_dates),
            )

        if prices.empty:
            return pd.DataFrame()

        return self._build_breadth_frame(prices, actual_key, target_key)

    def _build_breadth_frame(self, prices: pd.DataFrame, actual_key: str, target_key: str) -> pd.DataFrame:
        data = prices.copy()
        data["_date_key"] = data["日期"].map(self._normalize_date_key)
        data["_close"] = data["收盤價"].map(self._to_decimal)
        data["_change"] = data["漲跌價差"].map(self._to_decimal)
        data["_volume"] = data["成交股數"].map(self._to_decimal)

        current = data.loc[data["_date_key"] == actual_key].copy()
        current = current.dropna(subset=["證券代號", "_close"])
        if current.empty:
            return pd.DataFrame()

        previous_key = self._previous_date_key(data, actual_key)
        previous = data.loc[data["_date_key"] == previous_key].copy() if previous_key else pd.DataFrame()
        previous_close_by_code = (
            previous.dropna(subset=["證券代號", "_close"])
            .drop_duplicates(subset=["證券代號"], keep="last")
            .set_index("證券代號")["_close"]
            .to_dict()
            if not previous.empty
            else {}
        )

        advancing = 0
        declining = 0
        unchanged = 0
        limit_up = 0
        limit_down = 0
        skipped = 0

        for _, row in current.iterrows():
            stock_code = row["證券代號"]
            close_value = row["_close"]
            change = row["_change"]
            if change is None:
                previous_close = previous_close_by_code.get(stock_code)
                if previous_close is None:
                    skipped += 1
                    continue
                change = close_value - previous_close
            else:
                previous_close = close_value - change

            if change > 0:
                advancing += 1
            elif change < 0:
                declining += 1
            else:
                unchanged += 1

            if previous_close and previous_close > 0:
                change_ratio = change / previous_close
                if change_ratio >= Decimal("0.095"):
                    limit_up += 1
                elif change_ratio <= Decimal("-0.095"):
                    limit_down += 1

        warnings: list[str] = []
        quality = DecisionDeskQuality.OBSERVED
        actual_date = self._parse_date_key(actual_key)
        if actual_key != target_key and actual_date is not None:
            quality = DecisionDeskQuality.DEGRADED
            warnings.append(f"market_breadth_as_of_fallback:{actual_date.isoformat()}")
        if skipped:
            quality = DecisionDeskQuality.DEGRADED
            warnings.append(f"market_breadth_skipped_rows:{skipped}")

        row = {
            "as_of_date": actual_date.isoformat() if actual_date is not None else actual_key,
            "quality": quality.value,
            "warnings": "|".join(warnings),
            "advancing": advancing,
            "declining": declining,
            "unchanged": unchanged,
            "source": "sqlite_daily_prices",
            "stock_count": int(len(current)),
            "limit_up_count": limit_up,
            "limit_down_count": limit_down,
            "volume_expansion_bp": self._volume_expansion_bp(current, previous),
            "new_high_20_count": self._new_extreme_count(data, current, actual_key, 20, "high"),
            "new_low_20_count": self._new_extreme_count(data, current, actual_key, 20, "low"),
            "new_high_60_count": self._new_extreme_count(data, current, actual_key, 60, "high"),
            "new_low_60_count": self._new_extreme_count(data, current, actual_key, 60, "low"),
        }
        return pd.DataFrame([row])

    @staticmethod
    def _normalize_date_key(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().replace("-", "").replace("/", "")
        return text if len(text) == 8 and text.isdigit() else None

    @staticmethod
    def _parse_date_key(value: str) -> date | None:
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            return None

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value is None or isinstance(value, bool) or pd.isna(value):
            return None
        try:
            return Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _previous_date_key(data: pd.DataFrame, actual_key: str) -> str | None:
        keys = sorted(key for key in data["_date_key"].dropna().unique() if key < actual_key)
        return keys[-1] if keys else None

    @staticmethod
    def _volume_expansion_bp(current: pd.DataFrame, previous: pd.DataFrame) -> int | None:
        if current.empty or previous.empty or "_volume" not in current.columns or "_volume" not in previous.columns:
            return None
        current_volume = sum((item for item in current["_volume"] if item is not None), Decimal("0"))
        previous_volume = sum((item for item in previous["_volume"] if item is not None), Decimal("0"))
        if previous_volume <= 0:
            return None
        return int(((current_volume / previous_volume) * Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _new_extreme_count(
        data: pd.DataFrame,
        current: pd.DataFrame,
        actual_key: str,
        window: int,
        direction: str,
    ) -> int | None:
        keys = sorted(key for key in data["_date_key"].dropna().unique() if key <= actual_key)
        window_keys = keys[-window:]
        if len(window_keys) < window:
            return None
        history = data.loc[data["_date_key"].isin(window_keys)].dropna(subset=["證券代號", "_close"])
        if history.empty:
            return None

        count = 0
        for _, row in current.iterrows():
            stock_code = row["證券代號"]
            current_close = row["_close"]
            stock_history = history.loc[history["證券代號"] == stock_code, "_close"]
            if stock_history.empty or current_close is None:
                continue
            extreme = max(stock_history) if direction == "high" else min(stock_history)
            if current_close == extreme:
                count += 1
        return count
