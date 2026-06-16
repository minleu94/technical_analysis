from types import SimpleNamespace

import pandas as pd

from app_module.update_service import UpdateService


def _config(tmp_path):
    data_root = tmp_path / "FA_Data"
    meta_dir = data_root / "meta_data"
    technical_dir = data_root / "technical_analysis"
    broker_flow_dir = data_root / "broker_flow"
    daily_price_dir = data_root / "daily_price"
    tpex_daily_price_dir = data_root / "daily_price_tpex"
    meta_dir.mkdir(parents=True)
    technical_dir.mkdir(parents=True)
    broker_flow_dir.mkdir(parents=True)
    daily_price_dir.mkdir(parents=True)
    tpex_daily_price_dir.mkdir(parents=True)

    return SimpleNamespace(
        data_dir=data_root,
        daily_price_dir=daily_price_dir,
        tpex_daily_price_dir=tpex_daily_price_dir,
        meta_data_dir=meta_dir,
        technical_dir=technical_dir,
        log_dir=data_root / "logs",
        db_file=data_root / "sqlite" / "twstock.db",
        use_sqlite=False,
        broker_flow_dir=broker_flow_dir,
        stock_data_file=meta_dir / "stock_data_whole.csv",
        market_index_file=meta_dir / "market_index.csv",
        industry_index_file=meta_dir / "industry_index.csv",
        all_stocks_data_file=meta_dir / "all_stocks_data.csv",
        broker_branch_registry_file=meta_dir / "broker_branch_registry.csv",
        min_data_days=1,
        create_backup=lambda path: None,
    )


def _sqlite_config(tmp_path):
    config = _config(tmp_path)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    config.use_sqlite = True
    return config


def test_check_data_status_includes_broker_branch_and_technical_summary(tmp_path):
    config = _config(tmp_path)
    pd.DataFrame({
        "日期": ["2026-05-18", "2026-05-19"],
        "證券代號": ["2330", "2330"],
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({"日期": ["2026-05-19"], "收盤價": [100]}).to_csv(
        config.market_index_file,
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame({"日期": ["2026-05-19"], "指數": [200]}).to_csv(
        config.industry_index_file,
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame({
        "日期": ["2026-05-19"],
        "證券代號": ["2330"],
        "RSI": [55],
    }).to_csv(config.all_stocks_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "日期": ["2026-05-19"],
        "證券代號": ["2330"],
        "RSI": [55],
    }).to_csv(config.technical_dir / "2330_indicators.csv", index=False, encoding="utf-8-sig")

    branch_dir = config.broker_flow_dir / "9200_1234"
    (branch_dir / "meta").mkdir(parents=True)
    pd.DataFrame({
        "date": ["2026-05-19"],
        "trade_type": ["buy"],
        "counterparty_broker_code": ["9200"],
    }).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "branch_system_key": ["9200_1234"],
        "branch_broker_code": ["9200"],
        "branch_code": ["1234"],
        "branch_display_name": ["測試分點"],
        "url_param_a": ["9200"],
        "url_param_b": ["0000000000001234"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")

    status = UpdateService(config).check_data_status()

    assert set(status) == {
        "daily_data",
        "market_index",
        "industry_index",
        "broker_branch",
        "technical_indicators",
    }
    assert status["broker_branch"]["latest_date"] == "2026-05-19"
    assert status["broker_branch"]["broker_count"] == 1
    assert status["technical_indicators"]["latest_date"] == "2026-05-19"
    assert status["technical_indicators"]["file_count"] == 1


def test_check_data_overview_uses_read_only_lightweight_broker_summary(tmp_path):
    config = _config(tmp_path)
    pd.DataFrame({
        "日期": ["2026-05-19"],
        "證券代號": ["2330"],
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "branch_system_key": ["9200_1234"],
        "branch_broker_code": ["9200"],
        "branch_code": ["1234"],
        "branch_display_name": ["測試分點"],
        "url_param_a": ["9200"],
        "url_param_b": ["0000000000001234"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")

    class NoDeepBrokerStatusService(UpdateService):
        def check_broker_branch_data_status(self, branch_system_keys=None):
            raise AssertionError("overview must not run deep broker status")

    overview = NoDeepBrokerStatusService(config).check_data_overview()

    assert overview["daily_data"]["latest_date"] == "2026-05-19"
    assert overview["broker_branch"]["broker_count"] == 1
    assert overview["broker_branch"]["status"] in {"summary", "missing", "empty"}


def test_check_data_overview_uses_sqlite_when_enabled(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe("daily_prices", pd.DataFrame({
        "日期": ["20260529"],
        "證券代號": ["2330"],
        "收盤價": [100.0],
    }), if_exists="append")

    class NoCsvOverviewService(UpdateService):
        def _overview_csv_status(self, *args, **kwargs):
            raise AssertionError("SQLite overview must not fall back to CSV when SQLite has data")

    overview = NoCsvOverviewService(config).check_data_overview()

    assert overview["daily_data"]["latest_date"] == "2026-05-29"
    assert overview["daily_data"]["total_records"] == 1
    assert overview["daily_data"]["is_overview"] is True


def test_check_source_detail_uses_sqlite_when_enabled(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe("technical_indicators", pd.DataFrame({
        "日期": ["20260529"],
        "證券代號": ["2330"],
        "RSI": [55.0],
    }), if_exists="append")

    class NoCsvDetailService(UpdateService):
        def _check_technical_indicator_status(self):
            raise AssertionError("SQLite detail must not fall back to CSV when SQLite has data")

    detail = NoCsvDetailService(config).check_source_detail("technical")

    assert detail["latest_date"] == "2026-05-29"
    assert detail["total_records"] == 1
    assert detail["file_count"] == 1


def test_sync_daily_price_files_to_sqlite_upserts_only_csv_dates(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe("daily_prices", pd.DataFrame({
        "日期": ["20260528", "20260529"],
        "證券代號": ["2330", "2330"],
        "收盤價": [900.0, 901.0],
    }), if_exists="append")
    pd.DataFrame({
        "日期": ["2026-05-29"],
        "證券代號": ["2330"],
        "證券名稱": ["台積電"],
        "收盤價": [999.0],
    }).to_csv(config.daily_price_dir / "20260529.csv", index=False, encoding="utf-8-sig")

    result = UpdateService(config).sync_source_to_sqlite("daily_price_files")

    assert result["success"] is True
    synced = db.execute_query("SELECT 日期, 證券代號, 收盤價 FROM daily_prices ORDER BY 日期;")
    assert synced.to_dict(orient="records") == [
        {"日期": "20260528", "證券代號": "2330", "收盤價": 900.0},
        {"日期": "20260529", "證券代號": "2330", "收盤價": 999.0},
    ]


def test_sync_daily_price_files_to_sqlite_includes_tpex_daily_price_dir(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    pd.DataFrame({
        "日期": ["2026-06-16"],
        "證券代號": ["2330"],
        "證券名稱": ["台積電"],
        "收盤價": [999.0],
    }).to_csv(config.daily_price_dir / "20260616.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "日期": ["20260616"],
        "證券代號": ["3207"],
        "證券名稱": ["耀勝"],
        "收盤價": [42.5],
    }).to_csv(config.tpex_daily_price_dir / "20260616.csv", index=False, encoding="utf-8-sig")

    result = UpdateService(config).sync_source_to_sqlite("daily_price_files", "2026-06-16", "2026-06-16")

    assert result["success"] is True
    assert result["synced_records"] == 2
    synced = db.execute_query("SELECT 日期, 證券代號, 收盤價 FROM daily_prices ORDER BY 證券代號;")
    assert synced.to_dict(orient="records") == [
        {"日期": "20260616", "證券代號": "2330", "收盤價": 999.0},
        {"日期": "20260616", "證券代號": "3207", "收盤價": 42.5},
    ]


def test_update_tpex_daily_price_writes_csv_via_source(tmp_path):
    config = _sqlite_config(tmp_path)

    service = UpdateService(config)
    service._create_tpex_daily_price_source = lambda: type(
        "FakeTpexSource",
        (),
        {
            "update_for_date": lambda self, date: type(
                "Result",
                (),
                {
                    "success": True,
                    "message": "ok",
                    "row_count": 1,
                    "skipped_count": 2,
                    "diagnostic_count": 0,
                    "source_date": date.replace("-", ""),
                    "output_file": config.tpex_daily_price_dir / f"{date.replace('-', '')}.csv",
                },
            )()
        },
    )()

    result = service.update_tpex_daily_price("2026-06-16")

    assert result["success"] is True
    assert result["tpex_rows"] == 1
    assert result["skipped_rows"] == 2
    assert result["source_date"] == "20260616"


def test_update_tpex_daily_price_reports_source_failure(tmp_path):
    config = _sqlite_config(tmp_path)

    service = UpdateService(config)
    service._create_tpex_daily_price_source = lambda: type(
        "FailingTpexSource",
        (),
        {
            "update_for_date": lambda self, date: type(
                "Result",
                (),
                {
                    "success": False,
                    "message": "TPEX endpoint failed",
                    "row_count": 0,
                    "skipped_count": 0,
                    "diagnostic_count": 1,
                    "source_date": None,
                    "output_file": None,
                },
            )()
        },
    )()

    result = service.update_tpex_daily_price("2026-06-16")

    assert result["success"] is False
    assert "TPEX endpoint failed" in result["message"]


def test_sync_market_and_industry_csv_to_sqlite_replaces_tables(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe("market_indices", pd.DataFrame({
        "日期": ["20260528"],
        "指數名稱": ["加權指數"],
        "收盤指數": [21000.0],
    }), if_exists="append")
    pd.DataFrame({
        "日期": ["2026-05-29"],
        "指數名稱": ["加權指數"],
        "收盤指數": [21100.0],
    }).to_csv(config.market_index_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "日期": ["2026-05-29"],
        "指數名稱": ["半導體"],
        "收盤指數": [500.0],
    }).to_csv(config.industry_index_file, index=False, encoding="utf-8-sig")

    service = UpdateService(config)
    market_result = service.sync_source_to_sqlite("market_index")
    industry_result = service.sync_source_to_sqlite("industry_index")

    assert market_result["success"] is True
    assert industry_result["success"] is True
    market = db.execute_query("SELECT 日期, 指數名稱, 收盤指數 FROM market_indices;")
    industry = db.execute_query("SELECT 日期, 指數名稱, 收盤指數 FROM industry_indices;")
    assert market.to_dict(orient="records") == [
        {"日期": "20260529", "指數名稱": "加權指數", "收盤指數": 21100.0}
    ]
    assert industry.to_dict(orient="records") == [
        {"日期": "20260529", "指數名稱": "半導體", "收盤指數": 500.0}
    ]
    with db.connect() as conn:
        market_pk_cols = [
            row["name"]
            for row in sorted(
                conn.execute("PRAGMA table_info(market_indices);").fetchall(),
                key=lambda row: row["pk"],
            )
            if row["pk"]
        ]
    assert market_pk_cols == ["指數名稱", "日期"]


def test_check_data_status_does_not_repair_or_write_broker_registry(tmp_path):
    config = _config(tmp_path)
    pd.DataFrame({
        "日期": ["2026-05-19"],
        "證券代號": ["2330"],
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({"日期": ["2026-05-19"], "收盤價": [100]}).to_csv(
        config.market_index_file,
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame({"日期": ["2026-05-19"], "指數": [200]}).to_csv(
        config.industry_index_file,
        index=False,
        encoding="utf-8-sig",
    )
    branch_dir = config.broker_flow_dir / "8450_845B"
    (branch_dir / "meta").mkdir(parents=True)
    pd.DataFrame({
        "date": ["2026-05-19"],
        "trade_type": ["buy"],
        "counterparty_broker_code": ["8450"],
    }).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "branch_system_key": ["8450_845B"],
        "branch_broker_code": ["8450"],
        "branch_code": ["845B"],
        "branch_display_name": ["測試分點"],
        "url_param_a": ["8450"],
        "url_param_b": ["38450042"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")
    before = config.broker_branch_registry_file.read_bytes()

    status = UpdateService(config).check_data_status()

    assert status["broker_branch"]["broker_count"] == 1
    assert config.broker_branch_registry_file.read_bytes() == before


def test_broker_branch_status_check_loads_registry_read_only(tmp_path):
    from app_module.broker_branch_update_service import BrokerBranchUpdateService

    config = _config(tmp_path)
    branch_dir = config.broker_flow_dir / "8450_845B"
    (branch_dir / "meta").mkdir(parents=True)
    pd.DataFrame({
        "date": ["2026-05-19"],
        "trade_type": ["buy"],
        "counterparty_broker_code": ["8450"],
    }).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "branch_system_key": ["8450_845B"],
        "branch_broker_code": ["8450"],
        "branch_code": ["845B"],
        "branch_display_name": ["測試分點"],
        "url_param_a": ["8450"],
        "url_param_b": ["38450042"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")
    before = config.broker_branch_registry_file.read_bytes()

    status = BrokerBranchUpdateService(config).check_broker_branch_data_status()

    assert status["broker_count"] == 1
    assert config.broker_branch_registry_file.read_bytes() == before


def test_broker_branch_sqlite_loader_keeps_lots_and_amount_units_separate(tmp_path):
    config = _config(tmp_path)
    branch_dir = config.broker_flow_dir / "8450_845B"
    (branch_dir / "meta").mkdir(parents=True)
    pd.DataFrame([{
        "date": "2026-06-11",
        "trade_type": "買超",
        "branch_system_key": "8450_845B",
        "branch_display_name": "康和-永和",
        "counterparty_broker_code": "00631L",
        "counterparty_broker_name": "元大台灣50正2",
        "buy_lots": 160,
        "sell_lots": 20,
        "net_lots": 140,
        "buy_amount_k_twd": 5291,
        "sell_amount_k_twd": 653,
        "net_amount_k_twd": 4638,
    }]).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")

    loaded = UpdateService(config)._load_broker_branch_csv_for_sqlite()

    assert loaded.loc[0, "買進股數"] == 160000
    assert loaded.loc[0, "賣出股數"] == 20000
    assert loaded.loc[0, "買賣超股數"] == 140000
    assert loaded.loc[0, "買進金額千元"] == 5291
    assert loaded.loc[0, "賣出金額千元"] == 653
    assert loaded.loc[0, "買賣超金額千元"] == 4638


def test_broker_branch_sqlite_loader_preserves_rank_and_trade_type(tmp_path):
    config = _config(tmp_path)
    branch_dir = config.broker_flow_dir / "8450_845B"
    (branch_dir / "meta").mkdir(parents=True)
    pd.DataFrame([{
        "date": "2026-06-11",
        "trade_type": "賣超",
        "branch_system_key": "8450_845B",
        "branch_display_name": "康和-永和",
        "counterparty_broker_code": "2330",
        "counterparty_broker_name": "台積電",
        "buy_lots": None,
        "sell_lots": None,
        "net_lots": None,
        "buy_amount_k_twd": 100,
        "sell_amount_k_twd": 500,
        "net_amount_k_twd": -400,
        "lots_observed": False,
        "amount_observed": True,
        "lots_rank": None,
        "amount_rank": 9,
    }]).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")

    loaded = UpdateService(config)._load_broker_branch_csv_for_sqlite()

    assert loaded.loc[0, "trade_type"] == "賣超"
    assert pd.isna(loaded.loc[0, "lots_rank"])
    assert loaded.loc[0, "amount_rank"] == 9


def test_broker_branch_files_sync_allows_same_key_with_different_trade_type(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    branch_dir = config.broker_flow_dir / "8450_845B"
    (branch_dir / "daily").mkdir(parents=True)
    pd.DataFrame([
        {
            "date": "2026-06-16",
            "trade_type": "買超",
            "branch_system_key": "8450_845B",
            "branch_display_name": "凱基-信義",
            "counterparty_broker_code": "2344",
            "counterparty_broker_name": "華邦電",
            "buy_lots": 100,
            "sell_lots": 0,
            "net_lots": 100,
        },
        {
            "date": "2026-06-16",
            "trade_type": "賣超",
            "branch_system_key": "8450_845B",
            "branch_display_name": "凱基-信義",
            "counterparty_broker_code": "2344",
            "counterparty_broker_name": "華邦電",
            "buy_lots": 0,
            "sell_lots": 40,
            "net_lots": -40,
        },
    ]).to_csv(branch_dir / "daily" / "20260616.csv", index=False, encoding="utf-8-sig")

    result = UpdateService(config).sync_source_to_sqlite("broker_branch_files", "2026-06-16", "2026-06-16")

    assert result["success"] is True
    rows = DBManager(config).execute_query(
        "SELECT 分點名稱, 證券代號, 日期, trade_type FROM broker_flows ORDER BY trade_type"
    )
    assert rows[["分點名稱", "證券代號", "日期", "trade_type"]].to_dict(orient="records") == [
        {"分點名稱": "凱基-信義", "證券代號": "2344", "日期": "20260616", "trade_type": "買超"},
        {"分點名稱": "凱基-信義", "證券代號": "2344", "日期": "20260616", "trade_type": "賣超"},
    ]


def test_broker_branch_sqlite_loader_infers_missing_metric_ranks(tmp_path):
    config = _config(tmp_path)
    branch_dir = config.broker_flow_dir / "8450_845B"
    (branch_dir / "meta").mkdir(parents=True)
    pd.DataFrame([
        {
            "date": "2026-06-11",
            "trade_type": "買超",
            "branch_display_name": "康和-永和",
            "counterparty_broker_code": "2330",
            "counterparty_broker_name": "台積電",
            "buy_lots": 100,
            "sell_lots": 0,
            "net_lots": 100,
            "buy_amount_k_twd": 1000,
            "sell_amount_k_twd": 0,
            "net_amount_k_twd": 1000,
        },
        {
            "date": "2026-06-11",
            "trade_type": "買超",
            "branch_display_name": "康和-永和",
            "counterparty_broker_code": "2317",
            "counterparty_broker_name": "鴻海",
            "buy_lots": 200,
            "sell_lots": 0,
            "net_lots": 200,
            "buy_amount_k_twd": 500,
            "sell_amount_k_twd": 0,
            "net_amount_k_twd": 500,
        },
    ]).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")

    loaded = UpdateService(config)._load_broker_branch_csv_for_sqlite()
    by_code = loaded.set_index("證券代號")

    assert by_code.loc["2317", "lots_rank"] == 1
    assert by_code.loc["2330", "lots_rank"] == 2
    assert by_code.loc["2330", "amount_rank"] == 1
    assert by_code.loc["2317", "amount_rank"] == 2


def test_broker_branch_sqlite_loader_rejects_legacy_b_only_values_as_lots(tmp_path):
    config = _config(tmp_path)
    branch_dir = config.broker_flow_dir / "8450_845B"
    (branch_dir / "meta").mkdir(parents=True)
    pd.DataFrame([{
        "date": "2026-06-11",
        "branch_system_key": "8450_845B",
        "counterparty_broker_code": "00631L",
        "counterparty_broker_name": "元大台灣50正2",
        "buy_qty": 5291,
        "sell_qty": 653,
        "net_qty": 4638,
    }]).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")

    loaded = UpdateService(config)._load_broker_branch_csv_for_sqlite()

    assert pd.isna(loaded.loc[0, "買進股數"])
    assert pd.isna(loaded.loc[0, "買賣超股數"])
    assert loaded.loc[0, "買進金額千元"] == 5291
    assert loaded.loc[0, "買賣超金額千元"] == 4638


def test_check_source_detail_runs_deep_check_and_updates_manifest(tmp_path):
    config = _config(tmp_path)
    branch_dir = config.broker_flow_dir / "9200_1234"
    (branch_dir / "meta").mkdir(parents=True)
    pd.DataFrame({
        "date": ["2026-05-19"],
        "trade_type": ["buy"],
        "counterparty_broker_code": ["9200"],
    }).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "branch_system_key": ["9200_1234"],
        "branch_broker_code": ["9200"],
        "branch_code": ["1234"],
        "branch_display_name": ["測試分點"],
        "url_param_a": ["9200"],
        "url_param_b": ["0000000000001234"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")

    service = UpdateService(config)
    detail = service.check_source_detail("broker_branch")
    manifest = service._read_data_status_manifest()

    assert detail["latest_date"] == "2026-05-19"
    assert detail["broker_count"] == 1
    assert manifest["sources"]["broker_branch"]["latest_date"] == "2026-05-19"


def test_smart_incremental_technical_calculation_replays_warmup_window(tmp_path, monkeypatch):
    config = _config(tmp_path)
    pd.DataFrame({
        "日期": [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
        ],
        "證券代號": ["2330"] * 5,
        "收盤價": [10, 11, 12, 13, 14],
        "開盤價": [10, 11, 12, 13, 14],
        "最高價": [11, 12, 13, 14, 15],
        "最低價": [9, 10, 11, 12, 13],
        "成交股數": [100] * 5,
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "日期": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "證券代號": ["2330"] * 3,
        "RSI": [50, 51, 52],
    }).to_csv(config.technical_dir / "2330_indicators.csv", index=False, encoding="utf-8-sig")

    seen_dates = []

    class FakeCalculator:
        def __init__(self, logger):
            self.logger = logger

        def calculate_and_store_indicators(
            self,
            df,
            stock_id,
            output_dir,
            ignore_existing=False,
        ):
            seen_dates.extend(df["日期"].astype(str).tolist())
            return pd.DataFrame({
                "日期": df["日期"].astype(str),
                "證券代號": df["證券代號"].astype(str),
                "RSI": range(len(df)),
            })

    import analysis_module.technical_analysis.technical_indicators as indicators

    monkeypatch.setattr(indicators, "TechnicalIndicatorCalculator", FakeCalculator)

    result = UpdateService(config).calculate_technical_indicators(
        force_all=False,
        start_date=None,
        incremental_lookback_days=2,
    )

    assert result["success"] is True
    assert "2026-01-02" in seen_dates
    assert "2026-01-05" in seen_dates


def test_process_stock_data_batch_requires_explicit_paths(tmp_path):
    from analysis_module.technical_analysis.technical_indicators import (
        TechnicalIndicatorCalculator,
    )

    calculator = TechnicalIndicatorCalculator()

    assert calculator.process_stock_data_batch(stock_data_path=None) is False


def test_process_stock_data_batch_writes_only_to_explicit_paths(tmp_path):
    from analysis_module.technical_analysis.technical_indicators import (
        TechnicalIndicatorCalculator,
    )

    stock_file = tmp_path / "stock_data_whole.csv"
    output_dir = tmp_path / "technical_analysis"
    merged_file = tmp_path / "meta_data" / "all_stocks_data.csv"
    backup_dir = tmp_path / "meta_data" / "backup"
    dates = pd.date_range("2026-01-01", periods=35, freq="D").strftime("%Y-%m-%d")
    pd.DataFrame({
        "日期": dates,
        "證券代號": ["2330"] * len(dates),
        "收盤價": range(100, 100 + len(dates)),
        "開盤價": range(100, 100 + len(dates)),
        "最高價": range(101, 101 + len(dates)),
        "最低價": range(99, 99 + len(dates)),
        "成交股數": [1000] * len(dates),
    }).to_csv(stock_file, index=False, encoding="utf-8-sig")

    calculator = TechnicalIndicatorCalculator()
    result = calculator.process_stock_data_batch(
        stock_data_path=stock_file,
        output_dir=output_dir,
        merged_output_path=merged_file,
        backup_dir=backup_dir,
    )

    assert result is True
    assert (output_dir / "2330_indicators.csv").exists()
    assert merged_file.exists()
    assert list(backup_dir.glob("all_stocks_data_*.csv"))


def test_market_index_yfinance_fallback_never_uses_future_date(tmp_path, monkeypatch):
    from data_module.config import TWStockConfig
    from data_module.data_loader import DataLoader
    import yfinance

    config = TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="unit",
    )
    loader = DataLoader(config)
    monkeypatch.setattr(loader, "_make_request", lambda url, params: None)

    def fake_download(*args, **kwargs):
        return pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [1000],
            },
            index=pd.to_datetime(["2026-05-29"]),
        ).rename_axis("Date")

    monkeypatch.setattr(yfinance, "download", fake_download)

    result = loader.update_market_index("2026-05-28")

    assert result is False
    assert not config.market_index_file.exists()


def test_etf_code_repair_during_load(tmp_path):
    config = _sqlite_config(tmp_path)
    branch_dir = config.broker_flow_dir / "8450_845B"
    (branch_dir / "meta").mkdir(parents=True)

    pd.DataFrame([{
        "date": "2026-06-11",
        "branch_system_key": "8450_845B",
        "counterparty_broker_code": "ETF",
        "counterparty_broker_name": "元大台灣50",
        "buy_lots": 100,
        "sell_lots": 0,
        "net_lots": 100,
        "buy_amount_k_twd": 15000,
        "sell_amount_k_twd": 0,
        "net_amount_k_twd": 15000,
    }, {
        "date": "2026-06-11",
        "branch_system_key": "8450_845B",
        "counterparty_broker_code": "ETF",
        "counterparty_broker_name": "元大高股息",
        "buy_lots": 50,
        "sell_lots": 0,
        "net_lots": 50,
        "buy_amount_k_twd": 2000,
        "sell_amount_k_twd": 0,
        "net_amount_k_twd": 2000,
    }]).to_csv(branch_dir / "meta" / "merged.csv", index=False, encoding="utf-8-sig")

    service = UpdateService(config)
    loaded = service._load_broker_branch_csv_for_sqlite()

    assert len(loaded) == 2
    row_0050 = loaded[loaded["證券代號"] == "0050"].iloc[0]
    row_0056 = loaded[loaded["證券代號"] == "0056"].iloc[0]
    assert row_0050["買進股數"] == 100000
    assert row_0050["買進金額千元"] == 15000
    assert row_0056["買進股數"] == 50000
    assert row_0056["買進金額千元"] == 2000


def test_deduplicate_and_merge_broker_flows_complementary(tmp_path):
    config = _sqlite_config(tmp_path)
    service = UpdateService(config)

    df = pd.DataFrame([{
        "日期": "20260611",
        "分點名稱": "測試分點",
        "證券代號": "2330",
        "證券名稱": "台積電",
        "買進股數": 1000,
        "賣出股數": 0,
        "買賣超股數": 1000,
        "買進金額千元": 0,
        "賣出金額千元": 0,
        "買賣超金額千元": 0,
    }, {
        "日期": "20260611",
        "分點名稱": "測試分點",
        "證券代號": "2330",
        "證券名稱": "台積電",
        "買進股數": 0,
        "賣出股數": 0,
        "買賣超股數": 0,
        "買進金額千元": 950,
        "賣出金額千元": 0,
        "買賣超金額千元": 950,
    }])

    merged = service._deduplicate_and_merge_broker_flows(df)
    assert len(merged) == 1
    row = merged.iloc[0]
    assert row["買進股數"] == 1000
    assert row["買進金額千元"] == 950
    assert row["買賣超金額千元"] == 950


def test_deduplicate_and_merge_broker_flows_conflict(tmp_path):
    import pytest
    config = _sqlite_config(tmp_path)
    service = UpdateService(config)

    df = pd.DataFrame([{
        "日期": "20260611",
        "分點名稱": "測試分點",
        "證券代號": "2330",
        "證券名稱": "台積電",
        "買進股數": 1000,
        "賣出股數": 0,
        "買賣超股數": 1000,
        "買進金額千元": 900,
        "賣出金額千元": 0,
        "買賣超金額千元": 900,
    }, {
        "日期": "20260611",
        "分點名稱": "測試分點",
        "證券代號": "2330",
        "證券名稱": "台積電",
        "買進股數": 2000,
        "賣出股數": 0,
        "買賣超股數": 2000,
        "買進金額千元": 0,
        "賣出金額千元": 0,
        "買賣超金額千元": 0,
    }])

    with pytest.raises(ValueError, match="唯一鍵衝突"):
        service._deduplicate_and_merge_broker_flows(df)
