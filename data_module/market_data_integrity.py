"""Market-data integrity contracts shared by sync and controlled repair tools."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pandas as pd
import requests


TAIEX_INDEX_NAME = "TAIEX"
REQUIRED_DAILY_PRICE_COLUMNS = frozenset({"證券代號", "收盤價"})


def is_valid_daily_price_frame(frame: pd.DataFrame) -> bool:
    """Return whether a CSV has the minimum contract for an individual-stock price file."""
    return not frame.empty and REQUIRED_DAILY_PRICE_COLUMNS.issubset(frame.columns)


def normalize_market_index_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize the single-series TAIEX CSV into the SQLite market-index contract."""
    normalized = frame.copy()
    if "收盤指數" not in normalized.columns and "收盤價" in normalized.columns:
        normalized["收盤指數"] = normalized["收盤價"]
    if "指數名稱" not in normalized.columns:
        normalized["指數名稱"] = TAIEX_INDEX_NAME
    else:
        normalized["指數名稱"] = normalized["指數名稱"].fillna("").astype(str).str.strip()
        normalized.loc[normalized["指數名稱"] == "", "指數名稱"] = TAIEX_INDEX_NAME
    return normalized


def is_weekend_date_key(date_key: str) -> bool:
    """Return whether a normalized YYYYMMDD date falls on Saturday or Sunday."""
    try:
        return datetime.strptime(date_key, "%Y%m%d").weekday() >= 5
    except ValueError:
        return False


def should_accept_daily_price_session(
    date_key: str,
    *,
    official_session_lookup: Callable[[str], bool] | None = None,
) -> bool:
    """Accept weekdays by default; require explicit official evidence for a weekend session."""
    if not is_weekend_date_key(date_key):
        return True
    return bool(official_session_lookup and official_session_lookup(date_key))


def official_twse_session_exists(date_key: str) -> bool:
    """Check whether TWSE reports a market session for a date; errors fail closed."""
    try:
        response = requests.get(
            "https://www.twse.com.tw/exchangeReport/MI_INDEX",
            params={"response": "json", "date": date_key, "type": "ALLBUT0999"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("stat") == "OK" and bool(payload.get("data"))
    except (requests.RequestException, ValueError):
        return False
