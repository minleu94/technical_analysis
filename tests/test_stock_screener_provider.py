from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from decision_module.stock_screener import StockScreener


def test_stock_screener_uses_injected_recent_frame_providers() -> None:
    stock_provider = MagicMock(return_value=pd.DataFrame({"證券代號": ["2330"]}))
    industry_provider = MagicMock(return_value=pd.DataFrame({"指數名稱": ["半導體"]}))
    screener = StockScreener(
        SimpleNamespace(),
        recent_stock_provider=stock_provider,
        recent_industry_provider=industry_provider,
    )

    stock_frame = screener._load_sqlite_recent_stock_prices("day")
    industry_frame = screener._load_sqlite_recent_industry_indices("week")

    stock_provider.assert_called_once_with("day", screener.volume_lookback)
    industry_provider.assert_called_once_with("week")
    assert stock_frame.iloc[0]["證券代號"] == "2330"
    assert industry_frame.iloc[0]["指數名稱"] == "半導體"
