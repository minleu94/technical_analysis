import pandas as pd
import pytest

from decision_module.market_regime_kernels import (
    calculate_bollinger_bandwidth,
    calculate_ma_slope,
)


def test_ma_slope_golden_and_short_history_boundary() -> None:
    assert calculate_ma_slope(pd.Series([100, 101]), period=3) == 0.0
    assert calculate_ma_slope(pd.Series([100, 101, 102]), period=3) == pytest.approx(3.0)


def test_bollinger_bandwidth_is_prefix_invariant() -> None:
    close = pd.Series([100, 102, 101, 105, 104], dtype="float64")
    full = calculate_bollinger_bandwidth(close, window=3, std_dev=2)

    for length in range(1, len(close) + 1):
        prefix = calculate_bollinger_bandwidth(close.iloc[:length], window=3, std_dev=2)
        pd.testing.assert_series_equal(prefix, full.iloc[:length])
