import pandas as pd

from analysis_module.technical_analysis.technical_date_support import (
    safe_convert_technical_dates,
)
from analysis_module.technical_analysis.technical_indicators import (
    TechnicalIndicatorCalculator,
)


def test_safe_convert_technical_dates_preserves_legacy_values_and_input() -> None:
    source = pd.Series(
        [
            "20260526",
            "2026/05/27",
            "2026-05-28 15:00:00",
            "bad-date",
            None,
            20260530.0,
            "NaT",
        ]
    )
    original = source.copy()
    expected = [
        "2026-05-26",
        "2026-05-27",
        "2026-05-28",
        None,
        None,
        "2026-05-30",
        None,
    ]

    result = safe_convert_technical_dates(source)
    facade_result = TechnicalIndicatorCalculator(logger=object())._safe_convert_date(
        source
    )

    assert result.tolist() == expected
    assert facade_result.tolist() == expected
    pd.testing.assert_series_equal(source, original)
