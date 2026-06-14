import numpy as np
import pandas as pd

from analysis_module.technical_analysis.technical_analyzer import TechnicalAnalyzer
from analysis_module.technical_analysis.technical_indicators import (
    TechnicalIndicatorCalculator,
)


def _price_data(rows: int = 60) -> pd.DataFrame:
    close = np.linspace(100.0, 130.0, rows)
    return pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=rows),
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.arange(rows) + 1_000,
        }
    )


class TestTechnicalIndicatorCalculator:
    def test_calculate_ma_series_returns_indicator_dataframe(self) -> None:
        result = TechnicalIndicatorCalculator().calculate_ma_series(_price_data())

        assert {"SMA30", "DEMA30", "EMA30"} <= set(result.columns)
        assert result["SMA30"].notna().any()

    def test_calculate_momentum_indicators_returns_named_arrays(self) -> None:
        result = TechnicalIndicatorCalculator().calculate_momentum_indicators(
            _price_data()
        )

        assert {"RSI", "MACD", "MACD_signal", "MACD_hist"} <= set(result)
        assert all(len(values) == 60 for values in result.values())

    def test_calculate_volatility_indicators_returns_named_arrays(self) -> None:
        result = TechnicalIndicatorCalculator().calculate_volatility_indicators(
            _price_data()
        )

        assert {"upperband", "middleband", "lowerband", "SAR"} <= set(result)
        assert all(len(values) == 60 for values in result.values())


class TestTechnicalAnalyzer:
    def test_add_momentum_indicators_returns_enriched_dataframe(self) -> None:
        result = TechnicalAnalyzer().add_momentum_indicators(_price_data())

        assert {"RSI", "MACD", "MACD_signal", "MACD_hist", "SlowK", "SlowD"} <= set(
            result.columns
        )

    def test_add_volatility_indicators_returns_enriched_dataframe(self) -> None:
        result = TechnicalAnalyzer().add_volatility_indicators(_price_data())

        assert {"BB_Upper", "BB_Middle", "BB_Lower", "SAR", "ATR"} <= set(
            result.columns
        )

    def test_add_trend_indicators_returns_enriched_dataframe(self) -> None:
        result = TechnicalAnalyzer().add_trend_indicators(_price_data())

        assert {"TSF", "ADX"} <= set(result.columns)
