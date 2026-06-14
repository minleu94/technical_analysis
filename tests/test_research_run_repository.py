import json
import sqlite3

import pytest

from data_module.config import TWStockConfig


def test_config_exposes_research_run_storage_paths(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")

    assert config.research_run_db_file == tmp_path / "output" / "research_runs" / "research_runs.db"
    assert config.research_run_parquet_dir == tmp_path / "output" / "research_runs" / "parquet"
    assert config.research_run_staging_dir == tmp_path / "output" / "research_runs" / "staging"
    assert config.research_run_db_file.parent.exists()
    assert config.research_run_parquet_dir.exists()
    assert config.research_run_staging_dir.exists()


def test_research_run_repository_initializes_versioned_schema(tmp_path):
    from app_module.research_run_repository import ResearchRunRepository

    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    repository = ResearchRunRepository(config)
    repository.ensure_schema()
    repository.ensure_schema()

    with sqlite3.connect(config.research_run_db_file) as conn:
        schema_version = conn.execute(
            "SELECT version FROM schema_version WHERE name = ?",
            ("research_runs",),
        ).fetchone()
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(research_runs)").fetchall()
        }

    assert schema_version == (1,)
    assert {
        "run_id",
        "run_name",
        "run_type",
        "payload_hash",
        "data_manifest_json",
        "metrics_json",
        "regime_breakdown_json",
        "benchmark_results_json",
        "is_archived",
        "promotion_reconciliation_status",
    }.issubset(columns)


def test_research_run_metadata_round_trip_preserves_json_fields(tmp_path):
    from app_module.research_run_dtos import ResearchRunMetadataDTO
    from app_module.research_run_repository import ResearchRunRepository

    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    repository = ResearchRunRepository(config)
    metadata = ResearchRunMetadataDTO(
        run_id="run-001",
        run_name="固定門檻 OOS",
        run_type="single_backtest",
        strategy_id="baseline_score",
        strategy_version="v1",
        parameter_contract_version="m2-a-v1",
        original_input={"stock_code": "2330", "notes": ["原始", "輸入"]},
        normalized_params={"buy_score": 55, "sell_score": 45},
        fallback_reason={"config_schema_version": "legacy_v0"},
        universe=["2330", "2317"],
        start_date="2026-01-01",
        end_date="2026-03-31",
        data_cutoff_date="2025-12-31",
        data_fingerprint="sha256:data",
        fingerprint_algorithm="sha256",
        data_manifest={"daily_prices": {"max_date": "2025-12-31", "rows": 100}},
        capital_cents=1_000_000_00,
        fee_bp_x100=1425,
        slippage_bp_x100=500,
        stop_loss_bp=1000,
        take_profit_bp=2000,
        execution_price="next_open",
        sizing_mode="all_in",
        metrics={"total_return_bp": 1234, "sharpe": "1.23"},
        regime_breakdown={"Trend": {"trades": 3}},
        benchmark_results={"TAIEX": {"excess_return_bp": 234}},
        payload_hash="sha256:payload",
        equity_path="parquet/run-001_equity.parquet",
        equity_parquet_hash="sha256:equity",
        trades_path="parquet/run-001_trades.parquet",
        trades_parquet_hash="sha256:trades",
        created_at="2026-06-14T12:00:00",
    )

    repository.insert_metadata(metadata)
    loaded = repository.get_metadata("run-001")

    assert loaded == metadata
    raw = repository.get_raw_metadata_row("run-001")
    assert json.loads(raw["original_input_json"]) == metadata.original_input
    assert raw["is_archived"] == 0
    assert raw["promotion_reconciliation_status"] == "none"


def test_research_run_repository_rejects_duplicate_payload_mismatch(tmp_path):
    from app_module.research_run_dtos import ResearchRunMetadataDTO
    from app_module.research_run_repository import (
        ResearchRunConflictError,
        ResearchRunRepository,
    )

    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    repository = ResearchRunRepository(config)
    metadata = ResearchRunMetadataDTO(
        run_id="run-001",
        run_name="Run",
        run_type="single_backtest",
        payload_hash="sha256:a",
        created_at="2026-06-14T12:00:00",
    )
    repository.insert_metadata(metadata)

    with pytest.raises(ResearchRunConflictError):
        repository.insert_metadata(
            ResearchRunMetadataDTO(
                run_id="run-001",
                run_name="Run",
                run_type="single_backtest",
                payload_hash="sha256:b",
                created_at="2026-06-14T12:00:00",
            )
        )
