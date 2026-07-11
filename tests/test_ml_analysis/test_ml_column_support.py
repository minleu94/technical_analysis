import pandas as pd

from analysis_module.ml_analysis.ml_analyzer import MLAnalyzer, resolve_ml_column
from analysis_module.ml_analysis.ml_column_support import resolve_ml_column as canonical_resolver


def test_ml_column_resolver_preserves_facade_identity_and_lookup_order():
    analyzer = MLAnalyzer()
    assert resolve_ml_column is canonical_resolver

    for columns, eng_name, expected in (
        (["Close", "收盤價"], "Close", "收盤價"),
        (["Close"], "Close", "Close"),
        (["成交股數"], "Volume", "成交股數"),
        (["Volume", "成交股數"], "Volume", "成交股數"),
        (["Open"], "Close", None),
    ):
        frame = pd.DataFrame(columns=columns)
        assert analyzer._get_column_name(frame, eng_name) == expected
        assert canonical_resolver(frame.columns, analyzer.reverse_mapping, eng_name) == expected
