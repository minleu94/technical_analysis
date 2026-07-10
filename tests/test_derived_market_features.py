from __future__ import annotations

from decimal import Decimal

import pandas as pd

from decision_module.derived_market_features import (
    enrich_latest_market_features,
    latest_feature_decimal,
)


def test_enrich_latest_market_features_writes_only_latest_row() -> None:
    frame = pd.DataFrame(
        {
            "日期": pd.date_range("2026-01-01", periods=3),
            "收盤價": [Decimal("10"), Decimal("11"), Decimal("12.1")],
            "成交股數": [100, 200, 300],
        }
    )

    result = enrich_latest_market_features(frame)

    assert "漲幅%" not in frame.columns
    assert result["漲幅%"].isna().sum() == 2
    assert latest_feature_decimal(result, "漲幅%") == Decimal("10")
    assert latest_feature_decimal(result, "成交量變化率%") == Decimal("100")


def test_enrich_latest_market_features_uses_zero_for_invalid_denominator() -> None:
    frame = pd.DataFrame({"收盤價": [0, 12], "成交股數": [0, 100]})

    result = enrich_latest_market_features(frame)

    assert latest_feature_decimal(result, "漲幅%") == Decimal("0")
    assert latest_feature_decimal(result, "成交量變化率%") == Decimal("0")


def test_enrich_latest_market_features_uses_previous_twenty_volume_rows() -> None:
    frame = pd.DataFrame(
        {
            "收盤價": [Decimal("100")] * 22,
            "成交股數": [100] + [200] * 20 + [400],
        }
    )

    result = enrich_latest_market_features(frame)

    assert latest_feature_decimal(result, "成交量變化率%") == Decimal("100")


def test_latest_feature_decimal_returns_none_for_missing_or_invalid_value() -> None:
    assert latest_feature_decimal(pd.DataFrame(), "漲幅%") is None
    assert latest_feature_decimal(pd.DataFrame({"漲幅%": ["invalid"]}), "漲幅%") is None
