"""推薦市場資料框的純正規化步驟。"""

from typing import Tuple

import pandas as pd


def normalize_market_frame(source: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    """統一推薦管線需要的證券代號與名稱欄位，且不改動來源資料。"""
    frame = source.copy()
    if "證券代號" not in frame.columns:
        if "股票代號" not in frame.columns:
            raise ValueError("找不到股票代號欄位")
        frame["證券代號"] = frame["股票代號"]

    if "證券名稱" not in frame.columns:
        if "股票名稱" in frame.columns:
            frame["證券名稱"] = frame["股票名稱"]
        else:
            frame["證券名稱"] = frame["證券代號"]

    return frame, "證券代號"
