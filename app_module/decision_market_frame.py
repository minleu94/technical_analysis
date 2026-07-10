"""Daily Decision Desk 單次 snapshot 共用的唯讀市場資料 frame。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock

import pandas as pd


class DecisionMarketFrameLoader:
    """在單次 snapshot 內重用 daily_prices，下一次 snapshot 必須 reset。"""

    COLUMNS = ("日期", "證券代號", "收盤價", "漲跌價差", "成交股數")

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._as_of_date: date | None = None
        self._lookback_days = 0
        self._frame: pd.DataFrame | None = None
        self._lock = RLock()

    def reset(self, as_of_date: date) -> None:
        with self._lock:
            self._as_of_date = as_of_date
            self._lookback_days = 0
            self._frame = None

    def load(self, as_of_date: date, lookback_days: int) -> pd.DataFrame:
        if lookback_days <= 0:
            return pd.DataFrame(columns=self.COLUMNS)
        with self._lock:
            if (
                self._frame is None
                or self._as_of_date != as_of_date
                or lookback_days > self._lookback_days
            ):
                self._frame = self._read_frame(as_of_date, lookback_days)
                self._as_of_date = as_of_date
                self._lookback_days = lookback_days
            return self._slice_to_lookback(self._frame, lookback_days).copy()

    def load_recent_prices(
        self,
        stock_code: str,
        decision_date: date,
        limit: int,
    ) -> list[tuple[date, Decimal]]:
        if limit <= 0:
            return []
        frame = self.load(decision_date, limit)
        if frame.empty:
            return []

        code = str(stock_code).strip()
        selected = frame.loc[
            frame["證券代號"].astype(str).str.strip() == code,
            ["日期", "收盤價"],
        ]
        prices: list[tuple[date, Decimal]] = []
        for raw_date, raw_price in selected.itertuples(index=False, name=None):
            parsed_date = self._parse_date(raw_date)
            if parsed_date is None or parsed_date > decision_date:
                continue
            try:
                price = Decimal(str(raw_price).replace(",", ""))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if price.is_finite() and price > 0:
                prices.append((parsed_date, price))
        prices.sort(key=lambda item: item[0], reverse=True)
        return prices[:limit]

    def _read_frame(self, as_of_date: date, lookback_days: int) -> pd.DataFrame:
        if not self.db_path.exists():
            return pd.DataFrame(columns=self.COLUMNS)

        target_key = as_of_date.strftime("%Y%m%d")
        db_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        try:
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
                    params=(target_key, int(lookback_days)),
                )
                if date_rows.empty:
                    return pd.DataFrame(columns=self.COLUMNS)
                normalized_dates = [
                    str(value).strip().replace("-", "").replace("/", "")
                    for value in date_rows["日期"].tolist()
                ]
                placeholders = ",".join("?" for _ in normalized_dates)
                return pd.read_sql_query(
                    f"""
                    SELECT 日期, 證券代號, 收盤價, 漲跌價差, 成交股數
                    FROM daily_prices
                    WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') IN ({placeholders})
                    ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') ASC, 證券代號 ASC
                    """,
                    conn,
                    params=tuple(normalized_dates),
                )
        except sqlite3.Error:
            return pd.DataFrame(columns=self.COLUMNS)

    @classmethod
    def _slice_to_lookback(cls, frame: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
        if frame.empty or "日期" not in frame.columns:
            return frame.copy()
        date_keys = frame["日期"].map(cls._normalize_date_key)
        selected_keys = sorted(
            {key for key in date_keys if key is not None},
            reverse=True,
        )[:lookback_days]
        result = frame.loc[date_keys.isin(selected_keys)].copy()
        result["_date_key"] = result["日期"].map(cls._normalize_date_key)
        result = result.sort_values(["_date_key", "證券代號"]).drop(columns=["_date_key"])
        return result.reset_index(drop=True)

    @staticmethod
    def _normalize_date_key(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().replace("-", "").replace("/", "")
        return text if len(text) == 8 and text.isdigit() else None

    @classmethod
    def _parse_date(cls, value: object) -> date | None:
        key = cls._normalize_date_key(value)
        if key is None:
            return None
        try:
            return datetime.strptime(key, "%Y%m%d").date()
        except ValueError:
            return None
