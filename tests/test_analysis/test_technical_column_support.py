import pandas as pd

from analysis_module.column_support import resolve_column
from analysis_module.technical_analysis import technical_column_support
from analysis_module.technical_analysis.math_analyzer import (
    MathAnalyzer,
    resolve_technical_column as math_resolve_technical_column,
)
from analysis_module.technical_analysis.technical_analyzer import (
    TechnicalAnalyzer,
    resolve_technical_column as analyzer_resolve_technical_column,
)
from analysis_module.technical_analysis.technical_indicators import (
    TechnicalIndicatorCalculator,
    resolve_technical_column as indicator_resolve_technical_column,
)


def test_technical_analysis_facades_reexport_shared_column_resolver():
    assert indicator_resolve_technical_column is (
        technical_column_support.resolve_technical_column
    )
    assert math_resolve_technical_column is (
        technical_column_support.resolve_technical_column
    )
    assert analyzer_resolve_technical_column is (
        technical_column_support.resolve_technical_column
    )


def test_technical_analysis_column_facades_match_shared_resolver():
    for facade in (
        TechnicalIndicatorCalculator(logger=object()),
        MathAnalyzer(),
        TechnicalAnalyzer(),
    ):
        for columns, eng_name in (
            (["Close", "收盤價"], "Close"),
            (["Close"], "Close"),
            (["成交量"], "Volume"),
            (["Volume", "成交股數"], "Volume"),
            (["Open"], "Close"),
        ):
            frame = pd.DataFrame(columns=columns)

            assert facade._get_column_name(frame, eng_name) == (
                technical_column_support.resolve_technical_column(
                    frame.columns,
                    facade.reverse_mapping,
                    eng_name,
                )
            )


def test_shared_column_resolver_preserves_lookup_order_and_missing_fallback():
    reverse_mapping = {"Close": "收盤價", "Volume": "成交量"}

    assert resolve_column(["Close", "收盤價"], reverse_mapping, "Close") == "收盤價"
    assert resolve_column(["Close"], reverse_mapping, "Close") == "Close"
    assert resolve_column(["Open"], reverse_mapping, "Close") is None
