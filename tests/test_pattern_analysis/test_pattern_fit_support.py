import numpy as np

from analysis_module.pattern_analysis import pattern_analyzer
from analysis_module.pattern_analysis.pattern_fit_support import (
    _clear_polyfit_cache,
    _safe_polyfit,
    _safe_r_squared,
)


def test_safe_polyfit_preserves_linear_coefficients():
    assert _safe_polyfit([0, 1, 2], [1, 3, 5], 1) == (2.0, 1.0)


def test_safe_polyfit_preserves_quadratic_numpy_equivalence():
    expected = np.polyfit([0, 1, 2], [1, 2, 5], 2)

    np.testing.assert_allclose(_safe_polyfit([0, 1, 2], [1, 2, 5], 2), expected)


def test_safe_r_squared_preserves_zero_fallbacks():
    assert _safe_r_squared([3, 3, 3], [3, 3, 3]) == 0.0
    assert _safe_r_squared([1, 2, 3], [1, np.nan, 3]) == 0.0


def test_clear_polyfit_cache_preserves_recalculated_result():
    first = _safe_polyfit([0, 1, 2], [1, 3, 5], 1)
    second = _safe_polyfit([0, 1, 2], [1, 3, 5], 1)

    _clear_polyfit_cache()

    third = _safe_polyfit([0, 1, 2], [1, 3, 5], 1)

    assert first == second == third == (2.0, 1.0)


def test_pattern_analyzer_reexports_fit_support_callables():
    assert pattern_analyzer._safe_polyfit is _safe_polyfit
    assert pattern_analyzer._safe_r_squared is _safe_r_squared
    assert pattern_analyzer._clear_polyfit_cache is _clear_polyfit_cache
