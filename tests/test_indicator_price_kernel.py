import numpy as np
import pandas as pd

from analysis_module.technical_analysis.indicator_kernels import clean_price_values


def test_clean_price_values_golden_for_internal_invalid_values() -> None:
    values = clean_price_values(pd.Series([100, "--", 102, "NaN", 104]))

    np.testing.assert_array_equal(values, np.array([100, 100, 102, 102, 104]))
    assert values.dtype == np.float64


def test_clean_price_values_has_causal_prefix_contract() -> None:
    full = pd.Series(["--", 100, 101])

    full_values = clean_price_values(full)

    for prefix_length in range(1, len(full) + 1):
        prefix_values = clean_price_values(full.iloc[:prefix_length])
        np.testing.assert_array_equal(
            prefix_values,
            full_values[:prefix_length],
            err_msg=f"prefix {prefix_length} 不得受未來價格影響",
        )


def test_clean_price_values_uses_zero_only_until_first_observed_price() -> None:
    values = clean_price_values(pd.Series([None, "", 5]))

    np.testing.assert_array_equal(values, np.array([0, 0, 5], dtype=np.float64))
