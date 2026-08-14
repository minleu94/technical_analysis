"""推薦流程共用的最新市場衍生特徵。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd

from financial_module.units import to_decimal


_HUNDRED = Decimal("100")
_ZERO = Decimal("0")


def _to_valid_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool) or pd.isna(value):
        return None
    try:
        converted = to_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return converted if converted.is_finite() else None


def _price_change_percent(frame: pd.DataFrame) -> Decimal:
    close_column = next(
        (column for column in ("收盤價", "Close", "close") if column in frame.columns),
        None,
    )
    if close_column is None or len(frame) < 2:
        return _ZERO

    previous = _to_valid_decimal(frame[close_column].iloc[-2])
    current = _to_valid_decimal(frame[close_column].iloc[-1])
    if previous is None or current is None or previous <= _ZERO:
        return _ZERO
    return (current - previous) / previous * _HUNDRED


def _volume_change_percent(frame: pd.DataFrame) -> Decimal:
    if "成交股數" not in frame.columns or len(frame) < 2:
        return _ZERO

    latest = _to_valid_decimal(frame["成交股數"].iloc[-1])
    history = frame["成交股數"].iloc[-21:-1] if len(frame) >= 21 else frame["成交股數"].iloc[:-1]
    history_values = [
        converted
        for value in history
        if (converted := _to_valid_decimal(value)) is not None
    ]
    if latest is None or not history_values:
        return _ZERO

    average = sum(history_values, _ZERO) / Decimal(len(history_values))
    if average <= _ZERO:
        return _ZERO
    return (latest / average - Decimal("1")) * _HUNDRED


def _assign_latest_feature(
    frame: pd.DataFrame,
    *,
    column: str,
    index: object,
    value: Decimal,
) -> None:
    """將 Decimal 特徵安全寫入 pandas 欄位，避免 dtype 隱式升級。"""

    series = frame[column]
    if pd.api.types.is_numeric_dtype(series):
        # pandas 的數值欄位不能直接容納 Decimal；這裡是分析資料框邊界，
        # 明確轉成 nullable float，避免新版本 pandas 將隱式轉型升級為錯誤。
        frame[column] = pd.to_numeric(series, errors="coerce").astype("Float64")
        frame.at[index, column] = float(value)  # numeric-boundary: analytics
        return
    frame.at[index, column] = value


def enrich_latest_market_features(frame: pd.DataFrame) -> pd.DataFrame:
    """回傳防禦性複製，並只在最新一列加入推薦所需的衍生特徵。"""

    result = frame.sort_values("日期").copy() if "日期" in frame.columns else frame.copy()
    if result.empty:
        return result

    latest_index = result.index[-1]
    if "漲幅%" not in result.columns:
        result["漲幅%"] = pd.Series(pd.NA, index=result.index, dtype="object")
    if "成交量變化率%" not in result.columns:
        result["成交量變化率%"] = pd.Series(pd.NA, index=result.index, dtype="object")
    _assign_latest_feature(
        result,
        column="漲幅%",
        index=latest_index,
        value=_price_change_percent(result),
    )
    _assign_latest_feature(
        result,
        column="成交量變化率%",
        index=latest_index,
        value=_volume_change_percent(result),
    )
    return result


def latest_feature_decimal(frame: pd.DataFrame, column: str) -> Decimal | None:
    """從已 enrichment 的最新列讀取 Decimal，不重新計算。"""

    if frame.empty or column not in frame.columns:
        return None
    return _to_valid_decimal(frame.iloc[-1][column])
