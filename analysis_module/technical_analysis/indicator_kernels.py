"""不依賴 UI/Application 的技術指標純資料 kernel。"""

import numpy as np
import pandas as pd


def clean_price_values(series: pd.Series) -> np.ndarray:
    """將價格轉成 causal float64 array；缺值只可使用當下以前的觀測值。"""
    cleaned = series
    if cleaned.dtype == "object":
        cleaned = cleaned.mask(cleaned.isin(["--", "", "nan", "NaN", "None"]), np.nan)
        cleaned = pd.to_numeric(cleaned, errors="coerce")
    prices = np.ascontiguousarray(cleaned.values, dtype=np.float64)
    if np.isnan(prices).any():
        prices = pd.Series(prices).ffill().fillna(0.0).to_numpy(dtype=np.float64)
    return np.ascontiguousarray(prices, dtype=np.float64)
