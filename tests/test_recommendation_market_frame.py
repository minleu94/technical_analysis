import pandas as pd
import pytest

from app_module.recommendation_market_frame import normalize_market_frame


def test_normalize_market_frame_maps_legacy_stock_columns_without_mutating_input() -> None:
    source = pd.DataFrame(
        {
            "日期": ["2026-07-10"],
            "股票代號": ["2330"],
            "股票名稱": ["台積電"],
        }
    )

    normalized, stock_column = normalize_market_frame(source)

    assert stock_column == "證券代號"
    assert normalized["證券代號"].tolist() == ["2330"]
    assert normalized["證券名稱"].tolist() == ["台積電"]
    assert "證券代號" not in source.columns
    assert "證券名稱" not in source.columns


def test_normalize_market_frame_uses_stock_code_as_missing_name() -> None:
    source = pd.DataFrame({"日期": ["2026-07-10"], "證券代號": ["0050"]})

    normalized, stock_column = normalize_market_frame(source)

    assert stock_column == "證券代號"
    assert normalized["證券名稱"].tolist() == ["0050"]


def test_normalize_market_frame_rejects_missing_stock_code_column() -> None:
    with pytest.raises(ValueError, match="找不到股票代號欄位"):
        normalize_market_frame(pd.DataFrame({"日期": ["2026-07-10"]}))
