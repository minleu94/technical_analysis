from types import SimpleNamespace

import pandas as pd

from app_module.update_service import UpdateService


def _config(tmp_path):
    data_root = tmp_path / "FA_Data"
    meta_dir = data_root / "meta_data"
    technical_dir = data_root / "technical_analysis"
    broker_flow_dir = data_root / "broker_flow"
    meta_dir.mkdir(parents=True)
    technical_dir.mkdir(parents=True)
    broker_flow_dir.mkdir(parents=True)

    return SimpleNamespace(
        data_dir=data_root,
        meta_data_dir=meta_dir,
        technical_dir=technical_dir,
        broker_flow_dir=broker_flow_dir,
        stock_data_file=meta_dir / "stock_data_whole.csv",
        market_index_file=meta_dir / "market_index.csv",
        industry_index_file=meta_dir / "industry_index.csv",
        all_stocks_data_file=meta_dir / "all_stocks_data.csv",
        broker_branch_registry_file=meta_dir / "broker_branch_registry.csv",
        min_data_days=1,
        create_backup=lambda path: None,
    )


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
