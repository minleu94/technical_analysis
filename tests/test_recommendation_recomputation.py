from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

import app_module.recommendation_service as recommendation_service_module
from app_module.recommendation_service import RecommendationService
from decision_module.strategy_configurator import StrategyConfigurator


def _stock_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": pd.date_range("2026-01-01", periods=40),
            "證券代號": ["2330"] * 40,
            "證券名稱": ["台積電"] * 40,
            "收盤價": list(range(100, 140)),
            "開盤價": list(range(99, 139)),
            "最高價": list(range(101, 141)),
            "最低價": list(range(98, 138)),
            "成交股數": [1000] * 39 + [2000],
        }
    )


@patch("pandas.read_csv")
def test_recommendation_enriches_features_once_per_stock(
    mock_read_csv: MagicMock,
    monkeypatch,
) -> None:
    config = MagicMock()
    config.use_sqlite = False
    config.stock_data_file.exists.return_value = True
    config.stock_data_file.stat.return_value.st_size = 1024
    config.all_stocks_data_file.exists.return_value = False
    mock_read_csv.return_value = _stock_frame()
    service = RecommendationService(config, industry_mapper=MagicMock())
    service.strategy_configurator.generate_recommendations = lambda frame, _: pd.DataFrame()

    calls = 0
    original = recommendation_service_module.enrich_latest_market_features

    def counted(frame: pd.DataFrame) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return original(frame)

    monkeypatch.setattr(
        recommendation_service_module,
        "enrich_latest_market_features",
        counted,
    )

    service.run_recommendation({}, max_stocks=1, top_n=1)

    assert calls == 1


def test_configurator_skips_default_rsi_calculator_when_joined_column_exists(
    monkeypatch,
) -> None:
    configurator = StrategyConfigurator()
    frame = _stock_frame()
    frame["RSI"] = np.linspace(40, 60, len(frame))
    calls = 0

    def calculate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"RSI": np.full(len(frame), 70.0)}

    monkeypatch.setattr(
        configurator.technical_analyzer.calculator,
        "calculate_momentum_indicators",
        calculate,
    )

    result = configurator.configure_technical_indicators(
        frame,
        {
            "momentum": {
                "enabled": True,
                "rsi": {"enabled": True, "timeperiod": 14},
            }
        },
        full_config={"config_schema_version": 1},
    )

    assert calls == 0
    pd.testing.assert_series_equal(result["RSI"], frame["RSI"])


def test_configurator_recalculates_custom_rsi_parameter(monkeypatch) -> None:
    configurator = StrategyConfigurator()
    frame = _stock_frame()
    frame["RSI"] = np.linspace(40, 60, len(frame))
    calls = 0

    def calculate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"RSI": np.full(len(frame), 70.0)}

    monkeypatch.setattr(
        configurator.technical_analyzer.calculator,
        "calculate_momentum_indicators",
        calculate,
    )

    result = configurator.configure_technical_indicators(
        frame,
        {
            "momentum": {
                "enabled": True,
                "rsi": {"enabled": True, "timeperiod": 7},
            }
        },
        full_config={"config_schema_version": 1},
    )

    assert calls == 1
    assert result["RSI"].eq(70.0).all()
