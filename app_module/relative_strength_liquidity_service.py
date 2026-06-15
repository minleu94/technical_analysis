from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd

from app_module.decision_desk_dtos import DecisionDeskQuality, RelativeStrengthLiquiditySummary


class RelativeStrengthLiquidityProvider(Protocol):
    def fetch(self, as_of_date: date) -> pd.DataFrame: ...


class RelativeStrengthLiquidityService:
    """Build stock relative strength and liquidity ranking for Daily Decision Desk."""

    def __init__(
        self,
        provider: RelativeStrengthLiquidityProvider,
        *,
        top_n: int = 10,
        min_avg_turnover: int = 20_000_000,
    ) -> None:
        self.provider = provider
        self.top_n = top_n
        self.min_avg_turnover = Decimal(int(min_avg_turnover))

    def build_snapshot(self, as_of_date: date) -> RelativeStrengthLiquiditySummary:
        try:
            frame = self.provider.fetch(as_of_date)
        except Exception as exc:  # noqa: BLE001
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"relative_strength_liquidity_provider_error:{exc}",),
            )

        if frame is None or frame.empty:
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("relative_strength_liquidity_missing",),
            )

        result = self._build_from_frame(frame, as_of_date)
        return result

    def _build_from_frame(self, frame: pd.DataFrame, as_of_date: date) -> RelativeStrengthLiquiditySummary:
        required = {"日期", "證券代號", "收盤價", "成交股數"}
        if not required.issubset(set(frame.columns)):
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=("relative_strength_liquidity_missing_required_columns",),
            )

        data = frame.copy()
        data["_date"] = data["日期"].map(self._parse_date)
        data["_close"] = data["收盤價"].map(self._to_decimal)
        data["_volume"] = data["成交股數"].map(self._to_decimal)
        data["_code"] = data["證券代號"].map(lambda value: str(value).strip())
        data = data.dropna(subset=["_date", "_close", "_volume", "_code"])

        if data.empty:
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("relative_strength_liquidity_missing",),
            )

        eligible_dates = [item for item in data["_date"].unique() if item <= as_of_date]
        if not eligible_dates:
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("relative_strength_liquidity_missing",),
            )
        effective_date = max(eligible_dates)
        warnings: list[str] = []
        if effective_date != as_of_date:
            warnings.append(f"relative_strength_liquidity_as_of_fallback:{effective_date.isoformat()}")

        ranking: list[dict[str, Any]] = []
        skipped = 0
        for stock_code, stock_frame in data.groupby("_code", sort=False):
            item = self._rank_stock(str(stock_code), stock_frame, effective_date)
            if item is None:
                skipped += 1
                continue
            ranking.append(item)

        if not ranking:
            return RelativeStrengthLiquiditySummary(
                as_of_date=effective_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=tuple(warnings + ["relative_strength_liquidity_insufficient_history"]),
            )

        ranking = sorted(ranking, key=lambda item: (-int(item["strength_20d_bp"]), -int(item["strength_5d_bp"]), item["stock_code"]))
        weak = sorted(ranking, key=lambda item: (int(item["strength_20d_bp"]), int(item["strength_5d_bp"]), item["stock_code"]))
        low_liquidity = tuple(
            item["stock_code"]
            for item in ranking
            if Decimal(str(item["avg_turnover"])) < self.min_avg_turnover
        )

        if skipped:
            warnings.append(f"relative_strength_liquidity_skipped_symbols:{skipped}")

        # 如果 skipped 包含不滿足 21 天歷史的情形，並不一定是 exception，但如果出現 skipped 代表部分股票沒被算
        # 如果整個 ranking 為空，我們已經在上面回傳 degraded 並加 warnings。
        # 依照需求：若有警告，品質降為 DEGRADED；若無，則為 OBSERVED。
        quality = DecisionDeskQuality.OBSERVED if not warnings else DecisionDeskQuality.DEGRADED
        return RelativeStrengthLiquiditySummary(
            as_of_date=effective_date,
            quality=quality,
            warnings=tuple(warnings),
            top_strength_codes=tuple(item["stock_code"] for item in ranking[: self.top_n]),
            weak_strength_codes=tuple(item["stock_code"] for item in weak[: self.top_n] if int(item["strength_20d_bp"]) < 0),
            low_liquidity_codes=low_liquidity,
            meta={
                "source": "relative_strength_liquidity_service",
                "min_avg_turnover": int(self.min_avg_turnover),
                "ranking": ranking[: self.top_n],
            },
        )

    def _rank_stock(self, stock_code: str, frame: pd.DataFrame, effective_date: date) -> dict[str, Any] | None:
        history = frame.sort_values("_date").drop_duplicates(subset=["_date"], keep="last")
        history = history.loc[history["_date"] <= effective_date]
        
        # 限制：20日相對強度必須至少有 21 個有效交易觀測值 (即當日 + 前 20 日)
        if len(history) < 21:
            return None
            
        current_rows = history.loc[history["_date"] == effective_date]
        if current_rows.empty:
            return None
        current = current_rows.iloc[-1]
        close_now = current["_close"]
        if close_now is None or close_now <= 0:
            return None

        close_5 = self._lookback_close(history, effective_date, 5)
        close_20 = self._lookback_close(history, effective_date, 20)
        if close_5 is None or close_20 is None or close_5 <= 0 or close_20 <= 0:
            return None

        strength_5d_bp = self._return_bp(close_now, close_5)
        strength_20d_bp = self._return_bp(close_now, close_20)
        avg_turnover = self._avg_turnover(history)
        if avg_turnover is None:
            return None

        return {
            "stock_code": stock_code,
            "strength_5d_bp": strength_5d_bp,
            "strength_20d_bp": strength_20d_bp,
            "avg_turnover": int(avg_turnover),
        }

    @staticmethod
    def _lookback_close(history: pd.DataFrame, effective_date: date, target_days: int) -> Decimal | None:
        prior = history.loc[history["_date"] < effective_date]
        if prior.empty:
            return None
        if len(prior) < target_days:
            return None
        value = prior.iloc[len(prior) - target_days]["_close"]
        return value if isinstance(value, Decimal) else None

    @staticmethod
    def _avg_turnover(history: pd.DataFrame) -> Decimal | None:
        turnovers: list[Decimal] = []
        for _, row in history.tail(20).iterrows():
            close_value = row["_close"]
            volume_value = row["_volume"]
            if isinstance(close_value, Decimal) and isinstance(volume_value, Decimal):
                turnovers.append(close_value * volume_value)
        if not turnovers:
            return None
        return sum(turnovers, Decimal("0")) / Decimal(len(turnovers))

    @staticmethod
    def _return_bp(current: Decimal, base: Decimal) -> int:
        value = ((current - base) / base) * Decimal("10000")
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value is None or isinstance(value, bool) or pd.isna(value):
            return None
        try:
            parsed = Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _parse_date(value: object) -> date | None:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        text = str(value).strip().replace("-", "").replace("/", "")
        if len(text) != 8 or not text.isdigit():
            return None
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None


class SQLiteDailyPriceRelativeStrengthLiquidityProvider:
    """Read-only provider that supplies price and volume history from SQLite daily_prices."""

    def __init__(self, db_path: str | Path, *, lookback_days: int = 40) -> None:
        self.db_path = Path(db_path)
        self.lookback_days = lookback_days

    def fetch(self, as_of_date: date) -> pd.DataFrame:
        if not self.db_path.exists():
            return pd.DataFrame()
        target_key = as_of_date.strftime("%Y%m%d")
        try:
            db_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(db_uri, uri=True) as conn:
                conn.execute("PRAGMA query_only=ON")
                date_rows = pd.read_sql_query(
                    """
                    SELECT DISTINCT 日期
                    FROM daily_prices
                    WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') <= ?
                    ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                    LIMIT ?
                    """,
                    conn,
                    params=(target_key, self.lookback_days),
                )
                if date_rows.empty:
                    return pd.DataFrame()
                normalized_dates = [
                    str(item).replace("-", "").replace("/", "")
                    for item in date_rows["日期"].tolist()
                ]
                placeholders = ",".join("?" for _ in normalized_dates)
                return pd.read_sql_query(
                    f"""
                    SELECT 日期, 證券代號, 收盤價, 成交股數
                    FROM daily_prices
                    WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') IN ({placeholders})
                    ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') ASC, 證券代號 ASC
                    """,
                    conn,
                    params=tuple(normalized_dates),
                )
        except sqlite3.OperationalError:
            return pd.DataFrame()
