import importlib

import pandas as pd
import pytest

from analysis_module.pattern_analysis import pattern_column_support


MODULES = (
    "analysis_module.signal_analysis.signal_combiner",
    "analysis_module.pattern_analysis.signal_combiner",
)


@pytest.mark.parametrize("module_name", MODULES)
def test_signal_combiner_reexports_shared_pattern_column_resolver(module_name):
    module = importlib.import_module(module_name)
    assert module.resolve_pattern_column is pattern_column_support.resolve_pattern_column


@pytest.mark.parametrize("module_name", MODULES)
def test_signal_combiner_column_facade_matches_shared_resolver(module_name):
    module = importlib.import_module(module_name)
    combiner = module.SignalCombiner()

    for columns, eng_name in (
        (["Close", "收盤價"], "Close"),
        (["Close"], "Close"),
        (["成交量"], "Volume"),
        (["Volume", "成交股數"], "Volume"),
        (["Open"], "Close"),
    ):
        frame = pd.DataFrame(columns=columns)

        assert combiner._get_column_name(frame, eng_name) == module.resolve_pattern_column(
            frame.columns,
            combiner.reverse_mapping,
            eng_name,
        )


@pytest.mark.parametrize("module_name", MODULES)
@pytest.mark.parametrize("pattern,rsi,direction", [("W底", 20, 1), ("頭肩頂", 80, -1)])
def test_shared_pipeline_preserves_direction_volume_and_distinct_reliability(
    module_name, pattern, rsi, direction, monkeypatch,
):
    combiner = importlib.import_module(module_name).SignalCombiner()
    frame = pd.DataFrame({
        "Close": [100] * 21,
        "Volume": [100] * 20 + [1000],
        "RSI": [50] * 20 + [rsi],
        "ADX": [30] * 21,
    })
    original = frame.copy(deep=True)
    monkeypatch.setattr(combiner.pattern_analyzer, "identify_pattern", lambda df, kind: [(0, 20)])
    result = combiner.analyze_combined_signals(
        frame, pattern_types=[pattern], volume_conditions=["spike"],
    )
    assert result.loc[20, "Combined_Signal"] == 3 * direction
    assert result.loc[20, "Volume_Signal"] == direction
    if ".pattern_analysis." in module_name:
        assert result.loc[20, "Signal_Reliability"] == pytest.approx(1)
        assert "Signal_Direction" not in result.columns
    else:
        assert result.loc[20, "Signal_Reliability"] == pytest.approx(0.9)
        assert result.loc[20, "Signal_Direction"] == direction
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("module_name", MODULES)
def test_no_signal_pipeline_preserves_missing_volume_behavior(module_name):
    combiner = importlib.import_module(module_name).SignalCombiner()
    frame = pd.DataFrame({"Close": [100, 101], "ADX": [10, 10]})
    result = combiner.analyze_combined_signals(frame, volume_conditions=["spike"])
    assert result["Combined_Signal"].tolist() == [0, 0]
    assert result["Signal_Reliability"].tolist() == [0, 0]
