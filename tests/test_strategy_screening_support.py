import pandas as pd

from decision_module.strategy_screening_support import (
    build_recommendation_row,
    filter_completed_frame,
)


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
