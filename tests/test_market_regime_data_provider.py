from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from decision_module.market_regime_detector import MarketRegimeDetector


def test_detect_regime_uses_injected_market_frame_provider(tmp_path) -> None:
    provider = MagicMock(
        return_value=pd.DataFrame(
            {"日期": ["2026-07-10"], "收盤價": [100], "最高價": [101], "最低價": [99]}
        )
    )
    detector = MarketRegimeDetector(
        SimpleNamespace(
            resolve_output_path=lambda _: tmp_path,
            market_index_file=tmp_path / "must-not-be-read.csv",
            use_sqlite=True,
        ),
        use_persistent_history=False,
        market_frame_provider=provider,
    )

    result = detector.detect_regime()

    provider.assert_called_once_with()
    assert result == {
        "regime": "Trend",
        "confidence": 0.5,
        "details": {"error": "數據不足"},
    }


def test_detect_regime_normalizes_raw_sqlite_market_index_schema(tmp_path) -> None:
    dates = pd.date_range("2026-01-01", periods=80, freq="D").strftime("%Y%m%d")
    provider = MagicMock(
        return_value=pd.DataFrame(
            {
                "日期": dates,
                "收盤指數": range(100, 180),
            }
        )
    )
    detector = MarketRegimeDetector(
        SimpleNamespace(
            resolve_output_path=lambda _: tmp_path,
            market_index_file=tmp_path / "must-not-be-read.csv",
            use_sqlite=True,
        ),
        use_persistent_history=False,
        market_frame_provider=provider,
    )

    result = detector.detect_regime()

    assert result.get("details", {}).get("error") != "找不到收盤價欄位"
    assert result.get("details", {}).get("error") != "數據不足"
