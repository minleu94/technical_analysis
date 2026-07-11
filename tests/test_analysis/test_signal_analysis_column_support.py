import pandas as pd

from analysis_module.pattern_analysis import pattern_column_support
from analysis_module.signal_analysis.signal_combiner import (
    SignalCombiner,
    resolve_pattern_column,
)


def test_signal_combiner_reexports_shared_pattern_column_resolver():
    assert resolve_pattern_column is pattern_column_support.resolve_pattern_column


def test_signal_combiner_column_facade_matches_shared_resolver():
    combiner = SignalCombiner()

    for columns, eng_name in (
        (["Close", "收盤價"], "Close"),
        (["Close"], "Close"),
        (["成交量"], "Volume"),
        (["Volume", "成交股數"], "Volume"),
        (["Open"], "Close"),
    ):
        frame = pd.DataFrame(columns=columns)

        assert combiner._get_column_name(frame, eng_name) == resolve_pattern_column(
            frame.columns,
            combiner.reverse_mapping,
            eng_name,
        )
