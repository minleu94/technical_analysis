"""UpdateService 使用的無 I/O 資料正規化 helper。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable


def date_key(value: Any) -> str:
    import pandas as pd  # type: ignore[import-untyped]

    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    text = text.replace("/", "-")
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    compact = text.replace("-", "")
    if len(compact) == 8 and compact.isdigit():
        return compact

    try:
        parts = text.split("-")
        if len(parts) == 3:
            year_text, month_text, day_text = parts
            if (
                len(year_text) == 4
                and year_text.isdigit()
                and month_text.isdigit()
                and day_text.isdigit()
            ):
                return f"{int(year_text):04d}{int(month_text):02d}{int(day_text):02d}"
            if (
                0 < len(year_text) < 4
                and year_text.isdigit()
                and month_text.isdigit()
                and day_text.isdigit()
            ):
                year = int(year_text) + 1911
                return f"{year:04d}{int(month_text):02d}{int(day_text):02d}"
    except Exception:
        pass

    try:
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return compact
        return parsed.strftime("%Y%m%d")
    except Exception:
        return compact


def stock_code_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit() and len(text) <= 4:
        return text.zfill(4)
    return text


def iter_weekday_date_keys(
    start_date: str,
    end_date: str,
    *,
    date_key_fn: Callable[[Any], str] = date_key,
) -> list[str]:
    start_key = date_key_fn(start_date)
    end_key = date_key_fn(end_date)
    start_dt = datetime.strptime(start_key, "%Y%m%d")
    end_dt = datetime.strptime(end_key, "%Y%m%d")
    if start_dt > end_dt:
        raise ValueError("start_date must be <= end_date")

    date_keys: list[str] = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:
            date_keys.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return date_keys


def normalize_sqlite_dates(
    df: Any,
    *,
    date_key_fn: Callable[[Any], str] = date_key,
    stock_code_key_fn: Callable[[Any], str] = stock_code_key,
) -> Any:
    date_col = "日期" if "日期" in df.columns else ("日期" if "日期" in df.columns else None)
    if date_col is None:
        return df
    normalized = df.copy()
    if date_col != "日期":
        normalized = normalized.rename(columns={date_col: "日期"})
    if "證券代號" in normalized.columns and "證券代號" not in normalized.columns:
        normalized = normalized.rename(columns={"證券代號": "證券代號"})
    if "證券名稱" in normalized.columns and "證券名稱" not in normalized.columns:
        normalized = normalized.rename(columns={"證券名稱": "證券名稱"})
    normalized["日期"] = normalized["日期"].map(date_key_fn)
    if "證券代號" in normalized.columns:
        normalized["證券代號"] = normalized["證券代號"].map(stock_code_key_fn)
    return normalized


def sqlite_csv_dtype() -> dict[str, Any]:
    return {
        "日期": str,
        "證券代號": str,
        "股票代號": str,
        "stock_code": str,
        "stock_id": str,
        "date": str,
    }
