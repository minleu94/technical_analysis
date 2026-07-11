import pandas as pd

from analysis_module.pattern_analysis import PatternAnalyzer
from analysis_module.pattern_analysis.pattern_column_support import resolve_pattern_column


def test_resolve_pattern_column_prefers_chinese_close_alias():
    analyzer = PatternAnalyzer()

    assert resolve_pattern_column(
        pd.DataFrame(columns=["Close", "收盤價"]).columns,
        analyzer.reverse_mapping,
        "Close",
    ) == "收盤價"
    assert resolve_pattern_column(
        pd.DataFrame(columns=["Close"]).columns,
        analyzer.reverse_mapping,
        "Close",
    ) == "Close"


def test_resolve_pattern_column_preserves_volume_alias_and_missing_fallbacks():
    analyzer = PatternAnalyzer()

    assert resolve_pattern_column(
        pd.DataFrame(columns=["成交量"]).columns,
        analyzer.reverse_mapping,
        "Volume",
    ) is None
    assert resolve_pattern_column(
        pd.DataFrame(columns=["Volume", "成交股數"]).columns,
        analyzer.reverse_mapping,
        "Volume",
    ) == "成交股數"
    assert resolve_pattern_column(
        pd.DataFrame(columns=["Open"]).columns,
        analyzer.reverse_mapping,
        "Close",
    ) is None


def test_pattern_analyzer_column_name_facade_matches_support_function():
    analyzer = PatternAnalyzer()

    for columns, eng_name in (
        (["Close", "收盤價"], "Close"),
        (["Close"], "Close"),
        (["成交量"], "Volume"),
        (["Volume", "成交股數"], "Volume"),
        (["Open"], "Close"),
    ):
        frame = pd.DataFrame(columns=columns)

        assert analyzer._get_column_name(frame, eng_name) == resolve_pattern_column(
            frame.columns,
            analyzer.reverse_mapping,
            eng_name,
        )
