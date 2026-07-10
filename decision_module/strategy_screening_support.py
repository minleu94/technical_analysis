"""StrategyConfigurator 已完成 frame 的純篩選與輸出列組裝。"""

from typing import Any, Mapping

import pandas as pd


def filter_completed_frame(frame: pd.DataFrame, filters: Mapping[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    if "漲幅%" in result.columns:
        if "price_change_min" in filters:
            result = result[result["漲幅%"] >= filters["price_change_min"]]
        if "price_change_max" in filters:
            result = result[result["漲幅%"] <= filters["price_change_max"]]
    if "成交量變化率%" in result.columns and "volume_ratio_min" in filters:
        result = result[result["成交量變化率%"] >= filters["volume_ratio_min"]]
    rsi_col = next((column for column in ("RSI", "rsi", "RSI_14") if column in result.columns), None)
    if rsi_col is not None:
        if "rsi_min" in filters:
            result = result[result[rsi_col] >= filters["rsi_min"]]
        if "rsi_max" in filters:
            result = result[result[rsi_col] <= filters["rsi_max"]]
    return result


def build_recommendation_row(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "TotalScore" in result.columns:
        result["綜合評分"] = result["TotalScore"]
    return result
