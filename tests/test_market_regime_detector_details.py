from types import SimpleNamespace

import pandas as pd

from decision_module.market_regime_detector import MarketRegimeDetector


def test_breakout_details_include_base_indicators(tmp_path):
    detector = MarketRegimeDetector(
        SimpleNamespace(resolve_output_path=lambda _: tmp_path),
        use_persistent_history=False,
    )
    close = pd.Series([100.0] * 25)
    atr = pd.Series([5.0] * 25)
    bb_bandwidth = pd.Series([0.20] * 19 + [0.05])

    result = detector._classify_regime(
        close=close,
        ma20=100.0,
        ma60=105.0,
        ma20_slope=0.0,
        adx_value=18.0,
        plus_di=24.5,
        minus_di=18.2,
        latest_atr=5.0,
        atr_series=atr,
        latest_bb_bandwidth=0.05,
        bb_bandwidth_series=bb_bandwidth,
        rsi_value=50.0,
        trend_distance=-1.0,
        volume_series=None,
        date="2026-06-24",
    )

    details = result["details"]
    assert result["regime"] == "Breakout"
    assert details["ma60"] == 105.0
    assert details["ma20_slope"] == 0.0
    assert details["plus_di"] == 24.5
    assert details["minus_di"] == 18.2
