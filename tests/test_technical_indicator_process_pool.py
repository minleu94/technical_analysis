from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from app_module.update_service import UpdateService
from app_module.technical_indicator_process_pool import run_bounded_indicator_pool


def _frame(stock_id: str, rows: int = 35) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": [f"2026-01-{index:02d}" for index in range(1, rows + 1)],
            "證券代號": [stock_id] * rows,
            "開盤價": [10 + index for index in range(rows)],
            "最高價": [11 + index for index in range(rows)],
            "最低價": [9 + index for index in range(rows)],
            "收盤價": [10.5 + index for index in range(rows)],
            "成交股數": [1000] * rows,
        }
    )


def test_bounded_indicator_pool_returns_worker_results_without_writes() -> None:
    tasks = [("2330", _frame("2330")), ("2317", _frame("2317"))]

    report = run_bounded_indicator_pool(
        tasks,
        max_workers=2,
        max_in_flight=2,
        max_retries=1,
    )

    assert report["status"] == "completed"
    assert report["worker_writes"] is False
    assert report["sqlite_worker_writes"] is False
    assert report["single_writer_required"] is True
    assert report["max_observed_in_flight"] <= 2
    assert set(report["results"]) == {"2330", "2317"}
    assert all(isinstance(value, pd.DataFrame) for value in report["results"].values())


def test_update_service_pool_path_keeps_parent_storage(monkeypatch, tmp_path) -> None:
    data_root = tmp_path / "FA_Data"
    meta_dir = data_root / "meta_data"
    technical_dir = data_root / "technical_analysis"
    for path in (meta_dir, technical_dir, data_root / "broker_flow", data_root / "daily_price", data_root / "daily_price_tpex"):
        path.mkdir(parents=True)
    stock_data_file = meta_dir / "stock_data_whole.csv"
    _frame("2330", rows=2).to_csv(stock_data_file, index=False, encoding="utf-8-sig")
    config = SimpleNamespace(
        data_dir=data_root,
        daily_price_dir=data_root / "daily_price",
        tpex_daily_price_dir=data_root / "daily_price_tpex",
        meta_data_dir=meta_dir,
        technical_dir=technical_dir,
        log_dir=data_root / "logs",
        db_file=data_root / "sqlite" / "twstock.db",
        use_sqlite=False,
        broker_flow_dir=data_root / "broker_flow",
        stock_data_file=stock_data_file,
        market_index_file=meta_dir / "market_index.csv",
        industry_index_file=meta_dir / "industry_index.csv",
        all_stocks_data_file=meta_dir / "all_stocks_data.csv",
        broker_branch_registry_file=meta_dir / "broker_branch_registry.csv",
        min_data_days=1,
        create_backup=lambda _path: None,
        technical_process_pool_enabled=True,
        technical_process_pool_workers=2,
        technical_process_pool_max_in_flight=2,
        technical_process_pool_max_retries=1,
    )
    stored: list[str] = []

    class FakeCalculator:
        def __init__(self, logger=None):
            self.logger = logger

        def calculate_and_store_indicators(
            self,
            df,
            stock_id,
            output_dir,
            ignore_existing=False,
            precomputed_result=None,
        ):
            assert isinstance(precomputed_result, pd.DataFrame)
            stored.append(stock_id)
            return precomputed_result.copy()

    import analysis_module.technical_analysis.technical_indicators as indicators

    monkeypatch.setattr(indicators, "TechnicalIndicatorCalculator", FakeCalculator)
    pool_result = _frame("2330", rows=2)
    monkeypatch.setattr(
        "app_module.technical_indicator_process_pool.run_bounded_indicator_pool",
        lambda tasks, **kwargs: {
            "schema_version": "technical-indicator-production-pool.v1",
            "status": "completed",
            "results": {"2330": pool_result},
            "failed_ids": [],
            "cancelled_ids": [],
            "worker_writes": False,
            "sqlite_worker_writes": False,
            "single_writer_required": True,
            "observed_worker_count": 1,
            "max_observed_in_flight": 1,
        },
    )

    result = UpdateService(config).calculate_technical_indicators(
        force_all=True,
        technical_process_pool=True,
    )

    assert result["success"] is True
    assert result["success_count"] == 1
    assert stored == ["2330"]
    assert result["technical_process_pool"]["parent_single_writer"] is True
    assert result["technical_process_pool"]["production_worker_enabled"] is True
    assert result["technical_process_pool"]["worker_writes"] is False

