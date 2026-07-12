from __future__ import annotations

import math

import pandas as pd
import pytest

from analysis_module.technical_analysis.indicator_parameter_registry import InvalidParameterError
from decision_module.indicator_reuse import prepare_indicator_reuse


def test_default_rsi_and_bollinger_reuse_existing_columns() -> None:
    frame = pd.DataFrame(
        {
            "RSI": [50],
            "upperband": [11],
            "middleband": [10],
            "lowerband": [9],
        }
    )
    config = {
        "momentum": {"enabled": True, "rsi": {"enabled": True}},
        "volatility": {"enabled": True, "bollinger": {"enabled": True}},
    }

    plan = prepare_indicator_reuse(frame, config, {"config_schema_version": 0})

    assert plan.reused_indicators == frozenset({"rsi", "bollinger"})
    assert plan.technical_config["momentum"]["rsi"]["enabled"] is False
    assert plan.technical_config["volatility"]["bollinger"]["enabled"] is False
    assert plan.frame["BB_Upper"].tolist() == [11]
    assert plan.frame["BB_Middle"].tolist() == [10]
    assert plan.frame["BB_Lower"].tolist() == [9]


def test_default_kd_reuse_adds_legacy_analysis_aliases() -> None:
    frame = pd.DataFrame({"slowk": [25], "slowd": [30]})
    config = {"momentum": {"enabled": True, "kd": {"enabled": True}}}

    plan = prepare_indicator_reuse(frame, config, {"config_schema_version": 0})

    assert plan.reused_indicators == frozenset({"kd"})
    assert plan.frame["SlowK"].tolist() == [25]
    assert plan.frame["SlowD"].tolist() == [30]


def test_custom_rsi_period_is_not_reused() -> None:
    frame = pd.DataFrame({"RSI": [50]})
    config = {
        "momentum": {
            "enabled": True,
            "rsi": {"enabled": True, "timeperiod": 7},
        }
    }

    plan = prepare_indicator_reuse(frame, config, {"config_schema_version": 0})

    assert "rsi" not in plan.reused_indicators
    assert plan.technical_config["momentum"]["rsi"]["enabled"] is True


def test_all_invalid_indicator_values_are_not_reused() -> None:
    frame = pd.DataFrame({"RSI": [math.nan, math.nan]})
    config = {"momentum": {"enabled": True, "rsi": {"enabled": True}}}

    plan = prepare_indicator_reuse(frame, config, {"config_schema_version": 0})

    assert "rsi" not in plan.reused_indicators


def test_schema_v1_missing_parameter_still_fails_closed() -> None:
    frame = pd.DataFrame({"RSI": [50]})
    config = {"momentum": {"enabled": True, "rsi": {"enabled": True}}}

    with pytest.raises(InvalidParameterError):
        prepare_indicator_reuse(frame, config, {"config_schema_version": 1})
