"""Market regime 的 causal analysis kernels。"""

import numpy as np
import pandas as pd


def calculate_ma_slope(ma_series: pd.Series, period: int = 7) -> float:
    if len(ma_series) < period:
        return 0.0
    recent = ma_series.iloc[-period:].to_numpy()
    slope = np.polyfit(np.arange(len(recent)), recent, 1)[0]
    if len(recent) == 0 or recent[0] == 0:
        return 0.0
    return float((slope * period) / recent[0] * 100)


def calculate_bollinger_bandwidth(
    close: pd.Series, window: int = 20, std_dev: float = 2
) -> pd.Series:
    moving_average = close.rolling(window=window, min_periods=1).mean()
    rolling_std = close.rolling(window=window, min_periods=1).std()
    upper = moving_average + rolling_std * std_dev
    lower = moving_average - rolling_std * std_dev
    return (((upper - lower) / moving_average.replace(0, np.nan)) * 100).fillna(0)
