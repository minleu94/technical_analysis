import warnings

import numpy as np
import pandas as pd

from analysis_module.pattern_analysis import PatternAnalyzer
from analysis_module.pattern_analysis.pattern_analyzer import _safe_polyfit


def test_identify_flag_skips_underconstrained_peak_trough_regressions(monkeypatch):
    analyzer = PatternAnalyzer()
    prices = list(range(100, 120)) + [130, 118, 128, 116, 126, 114, 124, 112, 122, 110]
    df = pd.DataFrame({"收盤價": prices})

    monkeypatch.setattr(
        analyzer,
        "find_peaks_and_troughs",
        lambda *_args, **_kwargs: [
            {"idx": 22, "type": "peak"},
            {"idx": 24, "type": "trough"},
        ],
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = analyzer.identify_flag(df, window=10)

    assert result == []
    assert not any(isinstance(item.message, np.exceptions.RankWarning) for item in caught)


def test_safe_polyfit_rejects_non_finite_values_before_lapack():
    with np.testing.assert_raises(ValueError):
        _safe_polyfit([0, 1, 2], [1.0, np.nan, 3.0], 1)


def test_safe_polyfit_rejects_duplicate_x_values_before_lapack():
    with np.testing.assert_raises(ValueError):
        _safe_polyfit([1, 1, 1], [1.0, 2.0, 3.0], 1)
