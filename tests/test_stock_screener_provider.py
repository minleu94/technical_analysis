from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pandas as pd
from decision_module.stock_screener import StockScreener


STOCK_COLUMNS = [
    "排名",
    "證券代號",
    "證券名稱",
    "收盤價",
    "漲幅%",
    "成交量變化率%",
    "評分",
    "推薦理由",
]
INDUSTRY_COLUMNS = ["排名", "指數名稱", "收盤指數", "漲幅%"]
TODAY = date.today()


def _config(tmp_path: Path, *, use_sqlite: bool = False) -> SimpleNamespace:
    technical_dir = tmp_path / "technical_analysis"
    meta_data_dir = tmp_path / "meta_data"
    technical_dir.mkdir()
    meta_data_dir.mkdir()
    return SimpleNamespace(
        use_sqlite=use_sqlite,
        db_file=tmp_path / "twstock.db",
        technical_dir=technical_dir,
        industry_index_file=meta_data_dir / "industry_index.csv",
        meta_data_dir=meta_data_dir,
    )


def _stock_frame() -> pd.DataFrame:
    start = TODAY - timedelta(days=2)
    rows = []
    for code, name, closes in (
        ("2330", "台積電", (100, 105, 112)),
        ("2317", "鴻海", (100, 98, 94)),
        ("1101", "台泥", (100, 101, 102)),
    ):
        for offset, close in enumerate(closes):
            rows.append(
                {
                    "日期": (start + timedelta(days=offset)).strftime("%Y%m%d"),
                    "證券代號": code,
                    "證券名稱": name,
                    "收盤價": close,
                    "開盤價": close,
                    "最高價": close,
                    "最低價": close,
                    "成交股數": 1_000_000 + offset * 100_000,
                    "成交金額": close * (1_000_000 + offset * 100_000),
                }
            )
    return pd.DataFrame(rows)


def _industry_frame() -> pd.DataFrame:
    start = TODAY - timedelta(days=1)
    return pd.DataFrame(
        [
            {"日期": start.strftime("%Y%m%d"), "指數名稱": "半導體", "收盤指數": 100},
            {"日期": TODAY.strftime("%Y%m%d"), "指數名稱": "半導體", "收盤指數": 110},
            {"日期": start.strftime("%Y%m%d"), "指數名稱": "金融保險", "收盤指數": 100},
            {"日期": TODAY.strftime("%Y%m%d"), "指數名稱": "金融保險", "收盤指數": 90},
        ]
    )


def test_public_stock_methods_use_injected_provider_and_keep_schema_and_universe_count(tmp_path: Path) -> None:
    provider = MagicMock(return_value=_stock_frame())
    screener = StockScreener(_config(tmp_path), min_price=0, recent_stock_provider=provider)

    strong, strong_universe = screener.get_strong_stocks(period="day", top_n=2)
    weak, weak_universe = screener.get_weak_stocks(period="day", top_n=2)

    assert list(strong.columns) == STOCK_COLUMNS
    assert list(weak.columns) == STOCK_COLUMNS
    assert strong_universe == weak_universe == 3
    assert strong.iloc[0]["證券代號"] == "2330"
    assert weak.iloc[0]["證券代號"] == "2317"
    assert strong.iloc[0]["評分"].startswith("Top")
    assert weak.iloc[0]["評分"].startswith("Bottom")
    assert provider.call_args_list == [
        call("day", screener.volume_lookback),
        call("day", screener.volume_lookback),
    ]


def test_public_industry_methods_use_injected_provider_and_keep_schema(tmp_path: Path) -> None:
    provider = MagicMock(return_value=_industry_frame())
    screener = StockScreener(_config(tmp_path), recent_industry_provider=provider)

    strong = screener.get_strong_industries(period="day", top_n=2)
    weak = screener.get_weak_industries(period="day", top_n=2)

    assert list(strong.columns) == INDUSTRY_COLUMNS
    assert list(weak.columns) == INDUSTRY_COLUMNS
    assert strong.iloc[0]["指數名稱"] == "半導體"
    assert weak.iloc[0]["指數名稱"] == "金融保險"
    assert provider.call_args_list == [call("day"), call("day")]


def test_successful_injected_providers_never_construct_db_manager(tmp_path: Path, monkeypatch) -> None:
    import data_module.db_manager as db_manager_module

    db_manager = MagicMock(side_effect=AssertionError("DBManager must not be constructed"))
    monkeypatch.setattr(db_manager_module, "DBManager", db_manager)
    screener = StockScreener(
        _config(tmp_path, use_sqlite=True),
        min_price=0,
        recent_stock_provider=MagicMock(return_value=_stock_frame()),
        recent_industry_provider=MagicMock(return_value=_industry_frame()),
    )

    screener.get_strong_stocks(period="day", top_n=2)
    screener.get_weak_stocks(period="day", top_n=2)
    screener.get_strong_industries(period="day", top_n=2)
    screener.get_weak_industries(period="day", top_n=2)

    db_manager.assert_not_called()


def test_empty_injected_frames_mean_successful_read_with_empty_screen_and_no_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    import data_module.db_manager as db_manager_module

    config = _config(tmp_path, use_sqlite=True)
    stock_frame = _stock_frame()
    for code, frame in stock_frame.groupby("證券代號"):
        frame.to_csv(config.technical_dir / f"{code}_indicators.csv", index=False, encoding="utf-8-sig")
    _industry_frame().to_csv(config.industry_index_file, index=False, encoding="utf-8-sig")
    db_manager = MagicMock(side_effect=AssertionError("empty provider must not fall back"))
    monkeypatch.setattr(db_manager_module, "DBManager", db_manager)
    stock_provider = MagicMock(return_value=pd.DataFrame())
    industry_provider = MagicMock(return_value=pd.DataFrame())
    screener = StockScreener(
        config,
        recent_stock_provider=stock_provider,
        recent_industry_provider=industry_provider,
    )

    strong_stocks, strong_universe = screener.get_strong_stocks()
    weak_stocks, weak_universe = screener.get_weak_stocks()
    strong_industries = screener.get_strong_industries()
    weak_industries = screener.get_weak_industries()

    assert strong_stocks.empty and strong_universe == 0
    assert weak_stocks.empty and weak_universe == 0
    assert strong_industries.empty
    assert weak_industries.empty
    assert stock_provider.call_count == 2
    assert industry_provider.call_count == 2
    db_manager.assert_not_called()


def test_none_provider_result_uses_csv_self_loading_fallback(tmp_path: Path) -> None:
    config = _config(tmp_path)
    stock_frame = _stock_frame()
    for code, frame in stock_frame.groupby("證券代號"):
        frame.to_csv(config.technical_dir / f"{code}_indicators.csv", index=False, encoding="utf-8-sig")
    _industry_frame().to_csv(config.industry_index_file, index=False, encoding="utf-8-sig")

    stock_provider = MagicMock(return_value=None)
    industry_provider = MagicMock(return_value=None)
    screener = StockScreener(
        config,
        min_price=0,
        recent_stock_provider=stock_provider,
        recent_industry_provider=industry_provider,
    )

    strong, strong_universe = screener.get_strong_stocks(period="day", top_n=2)
    weak, weak_universe = screener.get_weak_stocks(period="day", top_n=2)
    strong_industries = screener.get_strong_industries(period="day", top_n=2)
    weak_industries = screener.get_weak_industries(period="day", top_n=2)

    assert list(strong.columns) == STOCK_COLUMNS
    assert list(weak.columns) == STOCK_COLUMNS
    assert strong_universe == weak_universe == 3
    assert strong.iloc[0]["證券代號"] == "2330"
    assert weak.iloc[0]["證券代號"] == "2317"
    assert list(strong_industries.columns) == INDUSTRY_COLUMNS
    assert list(weak_industries.columns) == INDUSTRY_COLUMNS
    assert strong_industries.iloc[0]["指數名稱"] == "半導體"
    assert weak_industries.iloc[0]["指數名稱"] == "金融保險"
