"""TASK-LOOP-01 資料更新閉環的隔離契約測試。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from app_module.dtos.update_loop_dtos import UpdateSourceStatusDTO
from app_module.update_service import UpdateService
from data_module.config import TWStockConfig
from data_module.db_manager import DBManager


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "artifacts",
        profile="task_loop_01",
    )
    config.use_sqlite = True
    config.min_data_days = 5
    config.technical_process_pool_enabled = False
    return config


def _daily_row(date_key: str, stock_code: str = "2330") -> dict[str, object]:
    close = 100 + int(date_key[-2:])
    return {
        "日期": date_key,
        "證券代號": stock_code,
        "證券名稱": "台積電",
        "成交股數": 1000,
        "成交筆數": 10,
        "成交金額": 100000,
        "開盤價": close - 1,
        "最高價": close + 1,
        "最低價": close - 2,
        "收盤價": close,
        "漲跌": "+",
        "漲跌價差": 1,
        "最後揭示買價": close - 1,
        "最後揭示買量": 10,
        "最後揭示賣價": close + 1,
        "最後揭示賣量": 10,
        "本益比": 20,
    }


def _write_daily_files(config: TWStockConfig, count: int = 12) -> list[str]:
    dates = pd.bdate_range("2026-07-01", periods=count)
    keys: list[str] = []
    for timestamp in dates:
        key = timestamp.strftime("%Y%m%d")
        keys.append(key)
        pd.DataFrame([_daily_row(key)]).to_csv(
            config.daily_price_dir / f"{key}.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return keys


def test_status_dto_preserves_source_actual_date_quality_and_warnings() -> None:
    dto = UpdateSourceStatusDTO.from_mapping(
        "daily_data",
        {
            "status": "lagging",
            "latest_date": "20260703",
            "total_records": 4,
            "warnings": ["來源日期落後", "來源日期落後"],
        },
    )

    assert dto.source_id == "daily_data"
    assert dto.latest_date == "2026-07-03"
    assert dto.actual_date == "2026-07-03"
    assert dto.quality == "degraded"
    assert dto.warnings == ("來源日期落後",)
    assert dto.to_dict()["warnings"] == ["來源日期落後"]

    availability_dto = UpdateSourceStatusDTO.from_mapping(
        "monthly_revenue",
        {
            "status": "ok",
            "latest_date": "2026-06-30",
            "latest_available_date": "2026-07-16",
            "total_records": 1,
        },
    )
    assert availability_dto.actual_date == "2026-07-16"


def test_data_pipeline_sync_is_idempotent_and_keeps_broker_identity_keys(tmp_path: Path) -> None:
    config = _config(tmp_path)
    keys = _write_daily_files(config)
    broker_daily = config.broker_flow_dir / "9200_1234" / "daily"
    broker_daily.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "date": keys[-1],
                "trade_type": "買超",
                "counterparty_broker_code": "2330",
                "counterparty_broker_name": "台積電",
                "buy_lots": 10,
                "sell_lots": 1,
                "net_lots": 9,
                "branch_display_name": "測試分點",
            },
            {
                "date": keys[-1],
                "trade_type": "賣超",
                "counterparty_broker_code": "2330",
                "counterparty_broker_name": "台積電",
                "buy_lots": 1,
                "sell_lots": 10,
                "net_lots": -9,
                "branch_display_name": "測試分點",
            },
        ]
    ).to_csv(broker_daily / f"{keys[-1]}.csv", index=False, encoding="utf-8-sig")

    service = UpdateService(config)
    first = service.sync_source_to_sqlite("daily_price_files")
    second = service.sync_source_to_sqlite("daily_price_files")
    broker = service.sync_source_to_sqlite("broker_branch_files")

    assert first["success"] is True
    assert second["success"] is True
    assert broker["success"] is True

    with sqlite3.connect(config.db_file) as conn:
        daily_count = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
        broker_count = conn.execute("SELECT COUNT(*) FROM broker_flows").fetchone()[0]
        trade_types = {
            row[0]
            for row in conn.execute(
                "SELECT trade_type FROM broker_flows ORDER BY trade_type"
            ).fetchall()
        }
    assert daily_count == len(keys)
    assert broker_count == 2
    assert trade_types == {"買超", "賣超"}

    status = service.check_data_status()
    assert status["daily_data"]["actual_date"] == "2026-07-16"
    assert status["daily_data"]["quality"] == "observed"
    assert service.check_data_status_dto().sources["daily_data"].actual_date == "2026-07-16"


def test_weekend_daily_file_is_rejected_without_official_session_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    weekend = "20260704"
    pd.DataFrame([_daily_row(weekend)]).to_csv(
        config.daily_price_dir / f"{weekend}.csv",
        index=False,
        encoding="utf-8-sig",
    )
    monkeypatch.setattr("app_module.update_service.official_twse_session_exists", lambda _: False)

    result = UpdateService(config).sync_source_to_sqlite("daily_price_files")

    assert result["success"] is True
    assert result["synced_records"] == 0
    assert not config.db_file.exists()


def test_technical_indicator_incremental_path_uses_parent_single_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    _write_daily_files(config, count=12)
    service = UpdateService(config)
    assert service.sync_source_to_sqlite("daily_price_files")["success"] is True

    class FakeCalculator:
        def __init__(self, logger=None):
            self.logger = logger

        def calculate_and_store_indicators(
            self,
            frame: pd.DataFrame,
            stock_id: str,
            output_dir: Path,
            ignore_existing: bool = False,
            precomputed_result: pd.DataFrame | None = None,
        ) -> pd.DataFrame:
            source = precomputed_result if precomputed_result is not None else frame
            return pd.DataFrame(
                {
                    "日期": source["日期"].astype(str),
                    "證券代號": str(stock_id),
                    "RSI": range(len(source)),
                }
            )

    monkeypatch.setattr(
        "analysis_module.technical_analysis.technical_indicators.TechnicalIndicatorCalculator",
        FakeCalculator,
    )

    result = service.calculate_technical_indicators(force_all=True)

    assert result["success"] is True
    assert result["success_count"] == 1
    assert result["technical_process_pool"]["parent_single_writer"] is True
    with sqlite3.connect(config.db_file) as conn:
        assert conn.execute("SELECT COUNT(*) FROM technical_indicators").fetchone()[0] == 12


def test_status_queries_are_read_only_when_database_is_missing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = UpdateService(config)

    status = service.check_data_status()
    detail = service.check_source_detail("daily_data")

    assert not config.db_file.exists()
    assert not service.status_manifest_file.exists()
    assert status["daily_data"]["status"] == "unavailable"
    assert status["daily_data"]["quality"] == "unavailable"
    assert detail["source_id"] == "daily_data"
