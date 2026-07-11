import warnings
from typing import Any

import numpy as np


# 模組級多項式擬合與 R方 快取
_polyfit_cache: dict[tuple[tuple[float, ...], tuple[float, ...], int], Any] = {}
_r_squared_cache: dict[tuple[tuple[float, ...], tuple[float, ...]], float] = {}


def _clear_polyfit_cache():
    """清空多項式擬合與 R方 快取，防止記憶體洩漏"""
    _polyfit_cache.clear()
    _r_squared_cache.clear()


def _safe_linear_fit(x, y):
    """高效的一階線性擬合 (最小平方法代數公式)"""
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    num = np.sum((x - x_mean) * (y - y_mean))
    den = np.sum((x - x_mean) ** 2)
    if den == 0:
        raise ValueError("division by zero in linear fit")
    slope = num / den
    intercept = y_mean - slope * x_mean
    return slope, intercept


def _safe_polyfit(x, y, deg):
    x_values = np.asarray(list(x), dtype=float)
    y_values = np.asarray(list(y), dtype=float)

    # 🚀 效能優化：使用 tuple 進行擬合快取，避免 rolling 內重複計算相同區間的迴歸
    key = (tuple(x_values), tuple(y_values), deg)
    if key in _polyfit_cache:
        return _polyfit_cache[key]

    if len(x_values) <= deg or len(y_values) <= deg:
        raise ValueError("not enough points for polynomial fit")
    if len(x_values) != len(y_values):
        raise ValueError("x and y length mismatch")
    if not np.isfinite(x_values).all() or not np.isfinite(y_values).all():
        raise ValueError("non-finite values for polynomial fit")

    if deg == 1:
        try:
            res = _safe_linear_fit(x_values, y_values)
            _polyfit_cache[key] = res
            return res
        except ValueError:
            pass

    if len(np.unique(x_values)) <= deg:
        raise ValueError("not enough unique x values for polynomial fit")
    with warnings.catch_warnings():
        warnings.simplefilter("error", np.exceptions.RankWarning)
        res = np.polyfit(x_values, y_values, deg)
        _polyfit_cache[key] = res
        return res


def _safe_r_squared(actual, fitted):
    actual_values = np.asarray(actual, dtype=float)
    fitted_values = np.asarray(fitted, dtype=float)

    # 🚀 效能優化：使用 tuple 進行 R方 快取
    key = (tuple(actual_values), tuple(fitted_values))
    if key in _r_squared_cache:
        return _r_squared_cache[key]

    denominator = np.sum((actual_values - np.mean(actual_values)) ** 2)
    if denominator == 0 or not np.isfinite(denominator):
        res = 0.0
    else:
        value = 1 - np.sum((actual_values - fitted_values) ** 2) / denominator
        res = float(value) if np.isfinite(value) else 0.0

    _r_squared_cache[key] = res
    return res
