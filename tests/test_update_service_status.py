from types import SimpleNamespace
import warnings
import sqlite3

import pandas as pd
import pytest
from pandas.errors import DtypeWarning

from app_module.update_service import UpdateService
from scripts.batch_update_daily_data import get_trading_days


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


def test_batch_daily_trading_days_include_start_date():
    assert get_trading_days("2026-06-18", "2026-06-22") == [
        "2026-06-18",
        "2026-06-19",
        "2026-06-22",
    ]


def test_update_daily_checks_selected_start_date_when_file_missing(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    captured = {}

    def fake_run(args, stdout=None, stderr=None, text=None, encoding=None):
        captured["args"] = list(args)
        if stdout is not None:
            stdout.write("[UPDATE_SUMMARY] SUCCESS: 0 days, FAILED: 0 days\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = UpdateService(config).update_daily("2026-06-18", "2026-06-22", delay_seconds=0)

    assert result["success"] is True
    start_index = captured["args"].index("--start-date") + 1
    assert captured["args"][start_index] == "2026-06-18"


def test_update_daily_returns_failure_when_batch_reports_failed_dates(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    def fake_run(args, stdout=None, stderr=None, text=None, encoding=None):
        if stdout is not None:
            stdout.write("2026-07-02 更新失敗：無法獲取數據\n")
            stdout.write("[UPDATE_SUMMARY] SUCCESS: 0 days, FAILED: 1 days\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = UpdateService(config).update_daily("2026-07-02", "2026-07-02", delay_seconds=0)

    assert result["success"] is False
    assert result["failed_dates"]


def test_update_daily_preserves_missing_date_when_batch_output_is_empty(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    def fake_run(args, stdout=None, stderr=None, text=None, encoding=None):
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = UpdateService(config).update_daily("2026-07-10", "2026-07-10", delay_seconds=0)

    assert result["success"] is False
    assert result["failed_dates"] == ["2026-07-10"]
    assert result["diagnostic_codes"] == ["batch_output_missing"]


def test_update_daily_streams_date_progress_when_callback_is_supplied(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    class _Stdout:
        def __init__(self):
            self._lines = iter(
                [
                    "[1/2] 正在更新 2026-07-02 的數據...\n",
                    "2026-07-02 更新成功：1 筆記錄\n",
                    "[2/2] 正在更新 2026-07-03 的數據...\n",
                    "2026-07-03 更新成功：1 筆記錄\n",
                    "[UPDATE_SUMMARY] SUCCESS: 2 days, FAILED: 0 days\n",
                ]
            )

        def readline(self):
            return next(self._lines, "")

    class _Process:
        def __init__(self):
            self.stdout = _Stdout()
            self.returncode = 0

        def wait(self):
            return self.returncode

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: _Process())
    progress = []

    result = UpdateService(config).update_daily(
        "2026-07-02",
        "2026-07-03",
        delay_seconds=0,
        progress_callback=lambda message, percentage: progress.append(
            (message, percentage)
        ),
    )

    assert result["success"] is True
    assert result["updated_dates"] == ["2026-07-02", "2026-07-03"]
    assert progress[0] == ("檢查 TWSE 每日股價缺漏", 0)
    assert ("TWSE API 下載 2026-07-02（1/2）", 50) in progress
    assert ("TWSE API 下載 2026-07-03（2/2）", 100) in progress
    assert progress[-1] == ("TWSE API 下載完成，正在解析日期結果", 100)


def test_update_daily_can_cancel_before_start_without_spawning_batch_process(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    spawned = []
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: spawned.append(True))

    result = UpdateService(config).update_daily(
        "2026-07-02",
        "2026-07-02",
        delay_seconds=0,
        cancel_callback=lambda: True,
    )

    assert result["success"] is False
    assert result["cancelled"] is True
    assert spawned == []


def test_update_daily_marks_cancel_after_current_streaming_request_is_drained(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    cancellation = {"requested": False}

    class _Stdout:
        def __init__(self):
            self._lines = iter(
                [
                    "[1/2] 正在更新 2026-07-02 的數據...\n",
                    "2026-07-02 更新成功：1 筆記錄\n",
                    "[2/2] 正在更新 2026-07-03 的數據...\n",
                    "2026-07-03 更新成功：1 筆記錄\n",
                    "[UPDATE_SUMMARY] SUCCESS: 2 days, FAILED: 0 days\n",
                ]
            )

        def readline(self):
            return next(self._lines, "")

    class _Process:
        def __init__(self):
            self.stdout = _Stdout()
            self.returncode = 0

        def wait(self):
            return self.returncode

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: _Process())

    def progress(message, _percentage):
        if "2026-07-02" in message:
            cancellation["requested"] = True

    result = UpdateService(config).update_daily(
        "2026-07-02",
        "2026-07-03",
        delay_seconds=0,
        progress_callback=progress,
        cancel_callback=lambda: cancellation["requested"],
    )

    assert result["success"] is False
    assert result["cancelled"] is True
    assert "安全收尾" in result["message"]


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


def test_sqlite_status_marks_date_aligned_sources_lagging_in_global_check(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe(
        "daily_prices",
        pd.DataFrame(
            {
                "日期": ["20260529"],
                "證券代號": ["2330"],
                "收盤價": [100.0],
            }
        ),
        if_exists="append",
    )
    db.write_dataframe(
        "market_indices",
        pd.DataFrame({"日期": ["20260528"], "收盤價": [100.0]}),
        if_exists="append",
    )
    db.write_dataframe(
        "industry_indices",
        pd.DataFrame({"日期": ["20260528"], "指數": [100.0]}),
        if_exists="append",
    )
    db.write_dataframe(
        "technical_indicators",
        pd.DataFrame({"日期": ["20260528"], "證券代號": ["2330"], "RSI": [55.0]}),
        if_exists="append",
    )

    status = UpdateService(config).check_data_status()

    assert status["daily_data"]["freshness_status"] == "reference"
    assert status["market_index"]["status"] == "lagging"
    assert status["industry_index"]["status"] == "lagging"
    assert status["technical_indicators"]["status"] == "lagging"


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


def test_sqlite_status_reads_are_query_only_and_do_not_construct_db_manager(tmp_path, monkeypatch):
    from app_module.sqlite_read_only import ReadOnlySQLiteManager
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe(
        "daily_prices",
        pd.DataFrame({"日期": ["20260529"], "證券代號": ["2330"], "收盤價": [100.0]}),
        if_exists="append",
    )

    class ExplodingDBManager:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("status reads must not construct writable DBManager")

    monkeypatch.setattr("data_module.db_manager.DBManager", ExplodingDBManager)

    overview = UpdateService(config).check_data_overview()
    assert overview["daily_data"]["latest_date"] == "2026-05-29"

    read_only = ReadOnlySQLiteManager(config.db_file)
    with read_only.connect() as conn:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE should_not_be_created (value TEXT)")

    assert not (config.db_file.parent / "should_not_be_created").exists()


def test_sqlite_status_missing_db_is_fail_soft_and_does_not_create_file(tmp_path):
    config = _sqlite_config(tmp_path)
    assert not config.db_file.exists()

    overview = UpdateService(config).check_data_overview()

    assert not config.db_file.exists()
    assert overview["daily_data"]["status"] == "unavailable"
    assert overview["daily_data"]["is_overview"] is True
    assert "不存在" in overview["daily_data"]["message"]
    assert overview["technical_indicators"]["status"] == "unavailable"


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


def test_check_source_detail_reads_candidate_domains_without_writing_manifest(tmp_path, monkeypatch):
    config = _config(tmp_path)
    candidate_db = tmp_path / "candidate" / "phase3c_candidate.db"
    candidate_db.parent.mkdir(parents=True)
    with sqlite3.connect(candidate_db) as conn:
        conn.executescript(
            """
            CREATE TABLE institutional_flows (
                stock_code TEXT,
                decision_date TEXT
            );
            CREATE TABLE credit_transactions (
                stock_code TEXT,
                decision_date TEXT
            );
            CREATE TABLE tdcc_shareholding (
                stock_code TEXT,
                decision_date TEXT
            );
            CREATE TABLE phase3c_backfill_checkpoints (
                source TEXT,
                decision_date TEXT,
                status TEXT
            );
            INSERT INTO institutional_flows VALUES ('2330', '2026-08-27');
            INSERT INTO credit_transactions VALUES ('2330', '2026-08-27');
            INSERT INTO tdcc_shareholding VALUES ('2330', '2026-08-23');
            INSERT INTO phase3c_backfill_checkpoints VALUES ('institutional', '2026-08-27', 'SUCCESS');
            INSERT INTO phase3c_backfill_checkpoints VALUES ('credit', '2026-08-27', 'SUCCESS');
            INSERT INTO phase3c_backfill_checkpoints VALUES ('tdcc', '2026-08-23', 'SUCCESS');
            """
        )
    monkeypatch.setenv("PHASE3C_CANDIDATE_DB_PATH", str(candidate_db))

    service = UpdateService(config)
    institutional = service.check_source_detail("institutional_flow")
    credit = service.check_source_detail("credit_transaction")
    tdcc = service.check_source_detail("tdcc_shareholding")

    assert institutional["status"] == "CANDIDATE_AVAILABLE"
    assert institutional["candidate_records"] == 1
    assert credit["status"] == "CANDIDATE_AVAILABLE"
    assert tdcc["status"] == "CANDIDATE_AVAILABLE"
    assert not service.status_manifest_file.exists()


def test_check_source_detail_reads_scheduler_artifacts_read_only(tmp_path):
    config = _config(tmp_path)
    config.output_root = tmp_path / "output"
    status_path = config.output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text('{"status": "passed"}', encoding="utf-8")

    detail = UpdateService(config).check_source_detail("scheduler_status")

    assert detail["status"] == "attention"
    assert detail["scheduler_state"] == "attention"
    assert detail["core_job_count"] == 6
    assert detail["operation_count"] >= 9
    assert detail["read_only"] is True
    assert any("latest_status_missing" in item for item in detail["warnings"])
    assert not (config.output_root / "scheduled" / "data_freshness" / "latest_status.json").exists()


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


def test_sync_daily_price_files_to_sqlite_preserves_zero_padded_stock_codes(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    pd.DataFrame({
        "證券代號": ["0050"],
        "證券名稱": ["元大台灣50"],
        "收盤價": [107.15],
    }).to_csv(config.daily_price_dir / "20260624.csv", index=False, encoding="utf-8-sig")

    result = UpdateService(config).sync_source_to_sqlite("daily_price_files", "2026-06-24", "2026-06-24")

    assert result["success"] is True
    synced = db.execute_query('SELECT "日期", "證券代號", "證券名稱", "收盤價" FROM daily_prices;')
    assert synced.to_dict(orient="records") == [
        {"日期": "20260624", "證券代號": "0050", "證券名稱": "元大台灣50", "收盤價": 107.15},
    ]


def test_sync_daily_price_files_normalizes_declared_alias_columns(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    pd.DataFrame({
        "date": ["2026-06-24"],
        "stock_code": [50.0],
        "stock_name": ["元大台灣50"],
        "收盤價": [107.15],
    }).to_csv(config.daily_price_dir / "20260624.csv", index=False, encoding="utf-8-sig")

    result = UpdateService(config).sync_source_to_sqlite("daily_price_files")

    assert result["success"] is True
    synced = DBManager(config).execute_query(
        'SELECT "日期", "證券代號", "證券名稱", "收盤價" FROM daily_prices;'
    )
    assert synced.to_dict(orient="records") == [
        {"日期": "20260624", "證券代號": "0050", "證券名稱": "元大台灣50", "收盤價": 107.15}
    ]


def test_sync_daily_price_files_skips_invalid_schema_and_weekend_without_evidence(tmp_path, monkeypatch):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    pd.DataFrame({
        "Date": ["2024-01-06"],
        "Open": [1.0],
        "High": [2.0],
        "Low": [1.0],
        "Close": [1.5],
        "Volume": [100],
    }).to_csv(config.daily_price_dir / "20240106.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "證券代號": ["2330"],
        "收盤價": [900.0],
    }).to_csv(config.daily_price_dir / "20260624.csv", index=False, encoding="utf-8-sig")
    monkeypatch.setattr("app_module.update_service.official_twse_session_exists", lambda _: False)

    result = UpdateService(config).sync_source_to_sqlite("daily_price_files")

    assert result["success"] is True
    synced = DBManager(config).execute_query('SELECT "日期", "證券代號" FROM daily_prices;')
    assert synced.to_dict(orient="records") == [{"日期": "20260624", "證券代號": "2330"}]


def test_sync_daily_price_files_accepts_weekend_only_with_official_session_evidence(tmp_path, monkeypatch):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    pd.DataFrame({
        "證券代號": ["2330"],
        "收盤價": [900.0],
    }).to_csv(config.daily_price_dir / "20240106.csv", index=False, encoding="utf-8-sig")
    monkeypatch.setattr("app_module.update_service.official_twse_session_exists", lambda _: True)

    result = UpdateService(config).sync_source_to_sqlite("daily_price_files")

    assert result["success"] is True
    synced = DBManager(config).execute_query('SELECT "日期", "證券代號" FROM daily_prices;')
    assert synced.to_dict(orient="records") == [{"日期": "20240106", "證券代號": "2330"}]


def test_sync_daily_data_to_sqlite_preserves_zero_padded_stock_codes(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    pd.DataFrame({
        "日期": ["20260624"],
        "證券代號": ["0050"],
        "證券名稱": ["元大台灣50"],
        "收盤價": [107.15],
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")

    result = UpdateService(config).sync_source_to_sqlite("daily_data")

    assert result["success"] is True
    synced = db.execute_query('SELECT "日期", "證券代號", "證券名稱", "收盤價" FROM daily_prices;')
    assert synced.to_dict(orient="records") == [
        {"日期": "20260624", "證券代號": "0050", "證券名稱": "元大台灣50", "收盤價": 107.15},
    ]


def test_merge_daily_data_includes_tpex_daily_price_dir(tmp_path):
    from scripts.merge_daily_data import merge_daily_data

    config = _sqlite_config(tmp_path)
    pd.DataFrame({
        "日期": ["20260617"],
        "證券代號": ["2330"],
        "證券名稱": ["台積電"],
        "收盤價": [900.0],
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "證券代號": ["3207"],
        "證券名稱": ["耀勝"],
        "收盤價": [42.5],
    }).to_csv(config.tpex_daily_price_dir / "20260618.csv", index=False, encoding="utf-8-sig")

    merge_daily_data(force_all=False, config=config)

    merged = pd.read_csv(config.stock_data_file, encoding="utf-8-sig", dtype={"日期": str, "證券代號": str})
    assert merged["日期"].max() == "20260618"
    assert {
        "日期": "20260618",
        "證券代號": "3207",
        "證券名稱": "耀勝",
        "收盤價": 42.5,
    } in merged[["日期", "證券代號", "證券名稱", "收盤價"]].to_dict(orient="records")


def test_update_service_merge_daily_data_forwards_progress(tmp_path):
    config = _config(tmp_path)
    pd.DataFrame(
        {
            "證券代號": ["2330"],
            "證券名稱": ["台積電"],
            "收盤價": [900.0],
        }
    ).to_csv(
        config.daily_price_dir / "20260618.csv",
        index=False,
        encoding="utf-8-sig",
    )
    progress: list[tuple[str, int]] = []

    result = UpdateService(config).merge_daily_data(
        force_all=True,
        progress_callback=lambda message, percentage: progress.append((message, percentage)),
    )

    assert result["success"] is True
    assert progress[0] == ("準備合併每日資料", 0)
    assert progress[-1] == ("每日資料合併完成", 100)


def test_export_table_to_csv_is_query_only_and_atomic(tmp_path, monkeypatch):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe(
        "daily_prices",
        pd.DataFrame(
            {
                "日期": ["20260529", "20260530"],
                "證券代號": ["2330", "0050"],
                "證券名稱": ["台積電", "元大台灣50"],
                "收盤價": [900.0, 100.0],
            }
        ),
        if_exists="append",
    )
    target = tmp_path / "exports" / "daily.csv"
    target.parent.mkdir(parents=True)
    target.write_text("sentinel\n", encoding="utf-8")

    class ExplodingDBManager:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("CSV export must not construct writable DBManager")

    monkeypatch.setattr("data_module.db_manager.DBManager", ExplodingDBManager)

    result = UpdateService(config).export_table_to_csv(
        "daily_prices",
        target,
        start_date="2026-05-29",
        end_date="2026-05-29",
    )

    assert result["success"] is True
    assert result["total_records"] == 1
    assert result["read_mode"] == "normal"
    exported = pd.read_csv(target, encoding="utf-8-sig", dtype={"證券代號": str})
    assert exported[["日期", "證券代號"]].to_dict(orient="records") == [
        {"日期": "2026-05-29", "證券代號": "2330"},
    ]
    assert not list(target.parent.glob(".daily.csv.*.part"))


def test_export_table_to_csv_missing_db_does_not_initialize_sqlite(tmp_path):
    config = _sqlite_config(tmp_path)
    target = tmp_path / "exports" / "missing.csv"

    result = UpdateService(config).export_table_to_csv("daily_prices", target)

    assert result["success"] is False
    assert "匯出失敗" in result["message"]
    assert not config.db_file.exists()
    assert not target.exists()


def test_export_table_to_csv_cancellation_preserves_existing_target(tmp_path, monkeypatch):
    config = _sqlite_config(tmp_path)
    target = tmp_path / "exports" / "daily.csv"
    target.parent.mkdir(parents=True)
    target.write_text("old-content\n", encoding="utf-8")

    chunks = [
        pd.DataFrame({"日期": ["20260529"], "證券代號": ["2330"]}),
        pd.DataFrame({"日期": ["20260530"], "證券代號": ["0050"]}),
    ]

    def fake_iter_query(*_args, **_kwargs):
        yield from chunks

    monkeypatch.setattr(
        "app_module.update_service.ReadOnlySQLiteManager.iter_query",
        fake_iter_query,
    )
    callback_calls = 0

    def cancel_after_first_chunk():
        nonlocal callback_calls
        callback_calls += 1
        return callback_calls >= 3

    result = UpdateService(config).export_table_to_csv(
        "daily_prices",
        target,
        cancel_callback=cancel_after_first_chunk,
    )

    assert result["success"] is False
    assert result["cancelled"] is True
    assert result["target_preserved"] is True
    assert target.read_text(encoding="utf-8") == "old-content\n"
    assert not list(target.parent.glob(".daily.csv.*.part"))


def test_export_table_to_csv_reports_determinate_progress(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe(
        "daily_prices",
        pd.DataFrame(
            {
                "日期": ["20260529", "20260530"],
                "證券代號": ["2330", "0050"],
                "證券名稱": ["台積電", "元大台灣50"],
                "收盤價": [900.0, 100.0],
            }
        ),
        if_exists="append",
    )
    progress: list[tuple[str, int]] = []

    result = UpdateService(config).export_table_to_csv(
        "daily_prices",
        tmp_path / "exports" / "daily.csv",
        progress_callback=lambda message, percentage: progress.append((message, percentage)),
    )

    assert result["success"] is True
    assert progress[0][1] == 0
    assert progress[-1][1] == 100
    assert any("預估 2 筆" in message for message, _ in progress)
    assert any("已處理 2 筆" in message for message, _ in progress)
    assert [percentage for _, percentage in progress] == sorted(
        percentage for _, percentage in progress
    )


def test_merge_daily_data_cancellation_preserves_existing_output(tmp_path):
    from scripts.merge_daily_data import merge_daily_data

    config = _config(tmp_path)
    original = pd.DataFrame(
        {
            "日期": ["20260617"],
            "證券代號": ["2330"],
            "證券名稱": ["台積電"],
            "收盤價": [900.0],
        }
    )
    original.to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "證券代號": ["3207"],
            "證券名稱": ["耀勝"],
            "收盤價": [42.5],
        }
    ).to_csv(
        config.daily_price_dir / "20260618.csv",
        index=False,
        encoding="utf-8-sig",
    )
    before = config.stock_data_file.read_bytes()
    callback_calls = 0

    def cancel_during_output():
        nonlocal callback_calls
        callback_calls += 1
        return callback_calls >= 6

    result = merge_daily_data(
        force_all=True,
        config=config,
        cancel_callback=cancel_during_output,
    )

    assert result["success"] is False
    assert result["cancelled"] is True
    assert config.stock_data_file.read_bytes() == before
    assert not list(config.stock_data_file.parent.glob(".stock_data_whole.csv.*.part"))


def test_merge_daily_data_cancellation_stops_inside_file_read_batch(tmp_path, monkeypatch):
    import importlib

    merge_module = importlib.import_module("scripts.merge_daily_data")
    config = _config(tmp_path)
    source_file = config.daily_price_dir / "20260618.csv"
    source_file.write_text("stub\n", encoding="utf-8")

    chunk_values = [
        pd.DataFrame(
            {
                "證券代號": ["2330"],
                "證券名稱": ["台積電"],
                "收盤價": [900.0],
            }
        ),
        pd.DataFrame(
            {
                "證券代號": ["0050"],
                "證券名稱": ["元大台灣50"],
                "收盤價": [100.0],
            }
        ),
    ]

    class FakeReader:
        def __init__(self):
            self._iterator = iter(chunk_values)
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._iterator)

        def close(self):
            self.closed = True

    reader = FakeReader()

    def fake_read_csv(_path, **kwargs):
        assert kwargs["chunksize"] == 50_000
        return reader

    monkeypatch.setattr(merge_module.pd, "read_csv", fake_read_csv)
    callback_calls = 0

    def cancel_on_second_batch():
        nonlocal callback_calls
        callback_calls += 1
        return callback_calls >= 6

    result = merge_module.merge_daily_data(
        force_all=True,
        config=config,
        cancel_callback=cancel_on_second_batch,
    )

    assert result["success"] is False
    assert result["cancelled"] is True
    assert "讀取批次" in result["message"]
    assert reader.closed is True
    assert not config.stock_data_file.exists()
    assert not list(config.stock_data_file.parent.glob(".stock_data_whole.csv.*.part"))


def test_merge_daily_data_reports_file_and_chunk_progress(tmp_path):
    from scripts.merge_daily_data import merge_daily_data

    config = _config(tmp_path)
    for date_key, stock_code in (("20260618", "2330"), ("20260619", "0050")):
        pd.DataFrame(
            {
                "證券代號": [stock_code],
                "證券名稱": ["測試股票"],
                "收盤價": [100.0],
            }
        ).to_csv(
            config.daily_price_dir / f"{date_key}.csv",
            index=False,
            encoding="utf-8-sig",
        )
    progress: list[tuple[str, int]] = []

    result = merge_daily_data(
        force_all=True,
        config=config,
        progress_callback=lambda message, percentage: progress.append((message, percentage)),
    )

    assert result["success"] is True
    assert progress[0][1] == 0
    assert progress[-1][1] == 100
    assert any("讀取每日檔案" in message for message, _ in progress)
    assert any("寫入每日整合檔" in message for message, _ in progress)
    assert [percentage for _, percentage in progress] == sorted(
        percentage for _, percentage in progress
    )


def test_merge_daily_data_returns_structured_no_op_when_all_csv_are_already_merged(tmp_path):
    from scripts.merge_daily_data import merge_daily_data

    config = _config(tmp_path)
    existing = pd.DataFrame(
        {
            "日期": ["20260618"],
            "證券代號": ["2330"],
            "證券名稱": ["測試股票"],
            "收盤價": [100.0],
        }
    )
    existing.to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    # Raw 檔日期不晚於整合檔，增量模式應明確回報 no-op，而不是 None。
    existing.drop(columns=["日期"]).to_csv(
        config.daily_price_dir / "20260618.csv",
        index=False,
        encoding="utf-8-sig",
    )

    result = merge_daily_data(force_all=False, config=config)

    assert result["success"] is True
    assert result["cancelled"] is False
    assert result["no_op"] is True
    assert result["merged_files"] == 0
    assert result["total_records"] == 1
    assert "沒有新資料需要合併" in result["message"]
    assert result["latest_date"] == "20260618"
    assert not (config.meta_data_dir / "backup").exists()



def test_sync_daily_data_to_sqlite_preserves_tpex_rows_from_daily_price_dir(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    date_col = "日期"
    code_col = "證券代號"
    name_col = "證券名稱"
    close_col = "收盤價"

    pd.DataFrame({
        date_col: ["2026-06-16"],
        code_col: ["2330"],
        name_col: ["台積電"],
        close_col: [999.0],
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({
        date_col: ["20260616"],
        code_col: ["3207"],
        name_col: ["耀勝"],
        close_col: [42.5],
    }).to_csv(config.tpex_daily_price_dir / "20260616.csv", index=False, encoding="utf-8-sig")

    result = UpdateService(config).sync_source_to_sqlite("daily_data")

    assert result["success"] is True
    synced = db.execute_query(
        f'SELECT "{date_col}", "{code_col}", "{close_col}" FROM daily_prices ORDER BY "{code_col}";'
    )
    assert synced.to_dict(orient="records") == [
        {date_col: "20260616", code_col: "2330", close_col: 999.0},
        {date_col: "20260616", code_col: "3207", close_col: 42.5},
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


def test_update_tpex_daily_price_range_fails_when_current_tpex_date_is_missing(tmp_path):
    config = _sqlite_config(tmp_path)
    (config.tpex_daily_price_dir / "20260703.csv").write_text(
        "日期,證券代號,證券名稱,收盤價\n20260703,3207,耀勝,42.5\n",
        encoding="utf-8-sig",
    )

    class FailingTpexSource:
        def update_for_date(self, date):
            assert date == "20260706"
            return SimpleNamespace(
                success=False,
                message="remote disconnected",
                row_count=0,
                skipped_count=0,
                diagnostic_count=1,
                source_date=None,
                output_file=None,
            )

    service = UpdateService(config)
    service._create_tpex_daily_price_source = lambda: FailingTpexSource()

    result = service.update_tpex_daily_price_range(
        "2026-07-03",
        "2026-07-06",
        force_refresh=False,
        sync_to_sqlite=False,
        break_on_repeated_source_date=False,
    )

    assert result["success"] is False
    assert result["skipped_dates"] == ["20260703"]
    assert result["failed_dates"] == ["20260706"]
    assert result["warnings"] == ["TPEX 每日股價缺少日期：20260706"]


def test_update_tpex_daily_price_range_streams_date_progress(tmp_path):
    config = _sqlite_config(tmp_path)

    class TpexSource:
        def update_for_date(self, date):
            return SimpleNamespace(
                success=True,
                message="ok",
                row_count=1,
                skipped_count=0,
                diagnostic_count=0,
                source_date=date,
                output_file=config.tpex_daily_price_dir / f"{date.replace('-', '')}.csv",
            )

    service = UpdateService(config)
    service._create_tpex_daily_price_source = lambda: TpexSource()
    progress = []

    result = service.update_tpex_daily_price_range(
        "2026-07-02",
        "2026-07-03",
        delay_seconds=0,
        force_refresh=True,
        sync_to_sqlite=False,
        break_on_repeated_source_date=False,
        progress_callback=lambda message, percentage: progress.append(
            (message, percentage)
        ),
    )

    assert result["success"] is True
    assert ("TPEX API 下載 20260702（1/2）", 50) in progress
    assert ("TPEX API 下載 20260703（2/2）", 100) in progress
    assert progress[-1] == ("TPEX API 下載完成，正在整理日期結果", 100)


def test_update_tpex_daily_price_range_stops_at_date_boundary_when_cancelled(tmp_path):
    config = _sqlite_config(tmp_path)
    calls = []

    class TpexSource:
        def update_for_date(self, date):
            calls.append(date)
            return SimpleNamespace(
                success=True,
                message="ok",
                row_count=1,
                skipped_count=0,
                diagnostic_count=0,
                source_date=date,
                output_file=config.tpex_daily_price_dir / f"{date.replace('-', '')}.csv",
            )

    service = UpdateService(config)
    service._create_tpex_daily_price_source = lambda: TpexSource()
    cancellation = {"requested": False}

    def progress(message, _percentage):
        if "20260702" in message:
            cancellation["requested"] = True

    result = service.update_tpex_daily_price_range(
        "2026-07-02",
        "2026-07-03",
        delay_seconds=0,
        force_refresh=True,
        sync_to_sqlite=False,
        break_on_repeated_source_date=False,
        progress_callback=progress,
        cancel_callback=lambda: cancellation["requested"],
    )

    assert result["success"] is False
    assert result["cancelled"] is True
    assert calls == ["20260702"]


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


def test_sync_market_index_normalizes_single_series_csv_to_taiex(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    pd.DataFrame({
        "日期": ["2026-05-29"],
        "收盤價": [21100.0],
    }).to_csv(config.market_index_file, index=False, encoding="utf-8-sig")

    result = UpdateService(config).sync_source_to_sqlite("market_index")

    assert result["success"] is True
    market = DBManager(config).execute_query('SELECT "日期", "指數名稱", "收盤指數" FROM market_indices;')
    assert market.to_dict(orient="records") == [
        {"日期": "20260529", "指數名稱": "TAIEX", "收盤指數": 21100.0}
    ]


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


def test_smart_incremental_technical_calculation_skips_when_indicator_is_current(tmp_path, monkeypatch):
    config = _config(tmp_path)
    pd.DataFrame({
        "日期": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "證券代號": ["2330"] * 3,
        "收盤價": [10, 11, 12],
        "開盤價": [10, 11, 12],
        "最高價": [11, 12, 13],
        "最低價": [9, 10, 11],
        "成交股數": [100] * 3,
    }).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "日期": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "證券代號": ["2330"] * 3,
        "RSI": [50, 51, 52],
    }).to_csv(config.technical_dir / "2330_indicators.csv", index=False, encoding="utf-8-sig")

    class FailIfCalledCalculator:
        def __init__(self, logger):
            self.logger = logger

        def calculate_and_store_indicators(self, *args, **kwargs):
            raise AssertionError("current indicators should be skipped")

    import analysis_module.technical_analysis.technical_indicators as indicators

    monkeypatch.setattr(indicators, "TechnicalIndicatorCalculator", FailIfCalledCalculator)

    result = UpdateService(config).calculate_technical_indicators(
        force_all=False,
        start_date=None,
        incremental_lookback_days=120,
    )

    assert result["success"] is True
    assert result["success_count"] == 0
    assert result["updated_stocks"] == []


def test_technical_latest_coverage_detects_missing_latest_stock_indicators(tmp_path):
    from data_module.db_manager import DBManager

    config = _sqlite_config(tmp_path)
    db = DBManager(config)
    db.write_dataframe("daily_prices", pd.DataFrame({
        "日期": ["20260705", "20260706", "20260705", "20260706"],
        "證券代號": ["2330", "2330", "3207", "3207"],
        "證券名稱": ["台積電", "台積電", "耀勝", "耀勝"],
        "收盤價": [900.0, 901.0, 63.5, 63.7],
    }), if_exists="append")
    db.write_dataframe("technical_indicators", pd.DataFrame({
        "日期": ["20260706"],
        "證券代號": ["2330"],
        "RSI": [55.0],
    }), if_exists="append")

    service = UpdateService(config)
    lagging = service.check_technical_indicator_latest_coverage()

    assert lagging["success"] is True
    assert lagging["is_current"] is False
    assert lagging["eligible_stock_count"] == 2
    assert lagging["covered_stock_count"] == 1
    assert lagging["missing_stock_count"] == 1

    db.write_dataframe("technical_indicators", pd.DataFrame({
        "日期": ["20260706"],
        "證券代號": ["3207"],
        "RSI": [44.0],
    }), if_exists="append")

    current = service.check_technical_indicator_latest_coverage()

    assert current["is_current"] is True
    assert current["eligible_stock_count"] == 2
    assert current["covered_stock_count"] == 2


def test_process_stock_data_batch_requires_explicit_paths(tmp_path):
    from analysis_module.technical_analysis.technical_indicators import (
        TechnicalIndicatorCalculator,
    )

    calculator = TechnicalIndicatorCalculator()

    assert calculator.process_stock_data_batch(stock_data_path=None) is False


def test_calculate_and_store_indicators_normalizes_date_before_merging(tmp_path, monkeypatch):
    from analysis_module.technical_analysis.technical_indicators import (
        TechnicalIndicatorCalculator,
    )

    output_dir = tmp_path / "technical_analysis"
    output_dir.mkdir()
    pd.DataFrame({
        "日期": ["2026-01-01", "2026-01-02"],
        "證券代號": ["2330", "2330"],
        "RSI": [50, 51],
    }).to_csv(output_dir / "2330_indicators.csv", index=False, encoding="utf-8-sig")

    calculator = TechnicalIndicatorCalculator()

    def fake_calculate_all_indicators(df, stock_id):
        return pd.DataFrame({
            "Date": ["2026-01-02", "2026-01-03"],
            "證券代號": ["2330", "2330"],
            "RSI": [61, 62],
        })

    monkeypatch.setattr(calculator, "calculate_all_indicators", fake_calculate_all_indicators)

    result = calculator.calculate_and_store_indicators(
        pd.DataFrame({"日期": ["2026-01-02", "2026-01-03"]}),
        "2330",
        output_dir=output_dir,
    )

    assert result is not None
    saved = pd.read_csv(output_dir / "2330_indicators.csv", encoding="utf-8-sig")
    assert saved["日期"].tolist() == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert saved["RSI"].tolist() == [50, 61, 62]


def test_calculate_and_store_indicators_does_not_concat_when_dates_unavailable(tmp_path, monkeypatch):
    from analysis_module.technical_analysis.technical_indicators import (
        TechnicalIndicatorCalculator,
    )

    output_dir = tmp_path / "technical_analysis"
    output_dir.mkdir()
    pd.DataFrame({
        "證券代號": ["2330", "2330"],
        "RSI": [50, 51],
    }).to_csv(output_dir / "2330_indicators.csv", index=False, encoding="utf-8-sig")

    calculator = TechnicalIndicatorCalculator()

    def fake_calculate_all_indicators(df, stock_id):
        return pd.DataFrame({
            "證券代號": ["2330"],
            "RSI": [62],
        })

    monkeypatch.setattr(calculator, "calculate_all_indicators", fake_calculate_all_indicators)

    result = calculator.calculate_and_store_indicators(
        pd.DataFrame({"證券代號": ["2330"]}),
        "2330",
        output_dir=output_dir,
    )

    assert result is not None
    saved = pd.read_csv(output_dir / "2330_indicators.csv", encoding="utf-8-sig")
    assert len(saved) == 1
    assert saved["RSI"].tolist() == [62]


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


def test_stock_name_to_code_map_ignores_mixed_type_columns_without_dtype_warning(tmp_path):
    config = _config(tmp_path)
    row_count = 300_000
    with config.stock_data_file.open("w", encoding="utf-8-sig", newline="") as handle:
        handle.write("日期,證券代號,證券名稱,成交股數,混合欄\n")
        for index in range(row_count):
            mixed_value = index if index < row_count // 2 else f"註記{index}"
            handle.write(f"20260706,0050,元大台灣50,100,{mixed_value}\n")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mapping = UpdateService(config)._get_stock_name_to_code_map()

    assert not any(isinstance(item.message, DtypeWarning) for item in caught)
    assert mapping["元大台灣50"] == "0050"


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

