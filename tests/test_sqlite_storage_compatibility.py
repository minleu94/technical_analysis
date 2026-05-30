import pandas as pd

from data_module.config import TWStockConfig
from data_module.data_loader import DataLoader
from app_module.backtest_service import BacktestService


def _config(tmp_path):
    return TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="unit",
    )


def test_data_loader_falls_back_to_daily_price_csv_when_sqlite_is_empty(tmp_path):
    config = _config(tmp_path)
    config.use_sqlite = True
    pd.DataFrame({
        "日期": ["20260529"],
        "證券代號": ["2330"],
        "收盤價": [100.0],
    }).to_csv(config.daily_price_dir / "20260529.csv", index=False, encoding="utf-8-sig")

    df = DataLoader(config).load_daily_price("2026-05-29")

    assert df is not None
    assert len(df) == 1
    assert str(int(df.iloc[0]["證券代號"])) == "2330"


def test_data_loader_falls_back_to_market_index_csv_when_sqlite_is_empty(tmp_path):
    config = _config(tmp_path)
    config.use_sqlite = True
    pd.DataFrame({
        "日期": ["2026-05-29"],
        "收盤指數": [21300.0],
    }).to_csv(config.market_index_file, index=False, encoding="utf-8-sig")

    df = DataLoader(config).load_market_index()

    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["收盤指數"] == 21300.0


def test_backtest_service_falls_back_to_csv_when_sqlite_price_table_is_empty(tmp_path):
    config = _config(tmp_path)
    config.use_sqlite = True
    pd.DataFrame({
        "日期": ["2026-05-29"],
        "證券代號": ["2330"],
        "收盤價": [100.0],
        "開盤價": [99.0],
        "最高價": [101.0],
        "最低價": [98.0],
        "成交股數": [1000],
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")

    df = BacktestService(config)._load_price_data("2330", "2026-05-29", "2026-05-29")

    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["收盤價"] == 100.0


def test_backtest_service_falls_back_to_csv_when_sqlite_indicator_table_is_empty(tmp_path):
    config = _config(tmp_path)
    config.use_sqlite = True
    pd.DataFrame({
        "日期": ["2026-05-29"],
        "證券代號": ["2330"],
        "RSI": [55.0],
    }).to_csv(config.get_technical_file("2330"), index=False, encoding="utf-8-sig")

    df = BacktestService(config)._load_indicator_data("2330", "2026-05-29", "2026-05-29")

    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["RSI"] == 55.0
