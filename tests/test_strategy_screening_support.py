import pandas as pd
import logging

from decision_module.strategy_screening_support import (
    build_recommendation_row,
    filter_completed_frame,
)
from decision_module.strategy_configurator import StrategyConfigurator


def test_filter_completed_frame_preserves_order_and_applies_price_volume_and_rsi() -> None:
    frame = pd.DataFrame(
        {
            "證券代號": ["A", "B", "C"],
            "漲幅%": [2, 8, 4],
            "成交量變化率%": [20, 5, 30],
            "RSI": [55, 55, 75],
        }
    )

    result = filter_completed_frame(
        frame,
        {"price_change_min": 1, "price_change_max": 6, "volume_ratio_min": 10, "rsi_max": 70},
    )

    assert result["證券代號"].tolist() == ["A"]
    assert frame["證券代號"].tolist() == ["A", "B", "C"]


def test_filter_completed_frame_keeps_rows_when_filter_columns_are_missing() -> None:
    frame = pd.DataFrame({"證券代號": ["A", "B"], "TotalScore": [80, 70]})

    result = filter_completed_frame(frame, {"price_change_min": 10, "volume_ratio_min": 100})

    assert result["證券代號"].tolist() == ["A", "B"]


def test_build_recommendation_row_keeps_score_column_and_existing_fields() -> None:
    frame = pd.DataFrame({"證券代號": ["2330"], "TotalScore": [88], "Reason": ["trend"]})

    result = build_recommendation_row(frame)

    assert result.to_dict("records") == [{"證券代號": "2330", "TotalScore": 88, "Reason": "trend", "綜合評分": 88}]


def test_screen_stocks_restores_price_and_volume_diagnostics_with_warning_cap(caplog) -> None:
    configurator = StrategyConfigurator()
    StrategyConfigurator._price_filter_log_count = 0
    StrategyConfigurator._volume_filter_log_count = 0
    price_frame = pd.DataFrame({"漲幅%": [1]})
    volume_frame = pd.DataFrame({"成交量變化率%": [1]})

    with caplog.at_level(logging.DEBUG):
        for _ in range(4):
            configurator.screen_stocks(price_frame, {"price_change_min": 2})
            configurator.screen_stocks(volume_frame, {"volume_ratio_min": 2})
        configurator.screen_stocks(pd.DataFrame({"漲幅%": [3], "成交量變化率%": [3]}), {"price_change_min": 2, "volume_ratio_min": 2})

    warnings = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    debug_messages = [record.message for record in caplog.records if record.levelno == logging.DEBUG]
    assert sum("[漲幅篩選]" in message for message in warnings) == 3
    assert sum("[成交量篩選]" in message for message in warnings) == 3
    assert StrategyConfigurator._price_filter_log_count == 4
    assert StrategyConfigurator._volume_filter_log_count == 4
    assert any("漲幅篩選: 1 -> 0" in message for message in debug_messages)
    assert any("成交量篩選: 1 -> 0" in message for message in debug_messages)
