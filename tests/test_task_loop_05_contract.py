"""Registry/evidence 行為契約：離線 tmp_path fixture，沒有正式信用或權限寫入。"""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

from app_module.evidence_event_dtos import EvidenceOutcome, EvidenceOutcomeStatus
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.forward_performance_service import ForwardPerformanceService
from app_module.research_run_comparison_service import ComparabilityStatus, ResearchRunComparisonService
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_repository import ResearchRunConflictError, ResearchRunRepositoryError
from app_module.research_run_service import InjectedResearchRunFailure, ResearchRunIntegrityError, ResearchRunService
from data_module.config import TWStockConfig
from ui_qt.views.backtest.research_run_metadata import build_recommendation_portfolio_metadata, build_single_backtest_metadata

NEXT = "next-session-open.v2"
LEGACY = "legacy-same-day-close.v1"
FAILURES = ("after_staging_row", "after_temp_write", "after_hash", "after_first_rename", "after_second_rename", "before_final_commit")


@pytest.fixture
def config(tmp_path):
    return TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "artifacts")


def metadata(run_id="contract"):
    return ResearchRunMetadataDTO(run_id, run_id, "single_backtest", execution_price=NEXT,
                                  payload_hash="sha256:declared", benchmark_results={"frozen": {"return_bp": 120}},
                                  created_at="2026-01-06T12:00:00")


def frames():
    return (pd.DataFrame({"date": ["2026-01-02", "2026-01-05"], "portfolio_value": [100000, 100500]}),
            pd.DataFrame({"date": ["2026-01-05"], "shares": [1000], "price_cents": [10000]}))


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


@pytest.mark.parametrize("stage", FAILURES)
def test_query_never_recovers_failure_and_explicit_owner_recovers(config, stage):
    service = ResearchRunService(config)
    with pytest.raises(InjectedResearchRunFailure):
        service.save_run(metadata(stage), *frames(), fail_at=stage)
    before = file_hash(config.research_run_db_file)
    query = ResearchRunService(config)
    assert query.list_runs() == []
    with pytest.raises(ResearchRunIntegrityError):
        query.load_run_data(stage)
    assert file_hash(config.research_run_db_file) == before
    query.reconcile_incomplete_saves()
    row = query.repository.get_raw_metadata_row(stage)
    expected = "failed" if stage in FAILURES[:2] else "committed"
    assert row["storage_state"] == expected
    if expected == "committed":
        assert query.load_run_data(stage).equity.equals(frames()[0])
    else:
        with pytest.raises(ResearchRunIntegrityError):
            query.load_run_data(stage)


def test_empty_registry_and_evidence_queries_create_no_database(config):
    assert ResearchRunService(config).list_runs() == []
    repo = EvidenceEventRepository(config)
    assert repo.list_events() == repo.list_outcomes() == []
    assert ForwardPerformanceService(config).calculate().events_scanned == 0
    assert not config.research_run_db_file.exists()
    assert not config.db_file.exists()


def test_same_declared_hash_cannot_hide_payload_or_metadata_change(config):
    service = ResearchRunService(config)
    saved = service.save_run(metadata(), *frames())
    before = file_hash(config.research_run_db_file)
    assert service.save_run(metadata(), *frames()) == saved
    assert file_hash(config.research_run_db_file) == before
    equity, trades = frames()
    equity.loc[1, "portfolio_value"] = 999999
    with pytest.raises(ResearchRunConflictError):
        service.save_run(metadata(), equity, trades)
    with pytest.raises(ResearchRunConflictError):
        service.save_run(replace(metadata(), benchmark_results={"changed": True}), *frames())
    assert file_hash(config.research_run_db_file) == before


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_load_and_idempotent_retry_reject_damaged_payload(config, damage):
    service = ResearchRunService(config)
    saved = service.save_run(metadata(), *frames())
    if damage == "missing":
        Path(saved.trades_path).unlink()
    else:
        Path(saved.trades_path).write_bytes(b"corrupt fixture")
    for operation in (lambda: service.load_run_data(saved.run_id), lambda: service.save_run(metadata(), *frames())):
        with pytest.raises(ResearchRunIntegrityError):
            operation()


def test_unknown_schema_is_not_downgraded_or_queried(config):
    service = ResearchRunService(config)
    service.save_run(metadata(), *frames())
    with sqlite3.connect(config.research_run_db_file) as conn:
        conn.execute("UPDATE schema_version SET version=999")
    before = file_hash(config.research_run_db_file)
    with pytest.raises(ResearchRunRepositoryError):
        service.list_runs()
    with pytest.raises(ResearchRunRepositoryError):
        service.repository.ensure_schema()
    assert file_hash(config.research_run_db_file) == before


def test_execution_contract_is_preserved_and_unknown_version_rejected(config):
    service = ResearchRunService(config)
    saved = service.save_run(metadata(), *frames())
    assert saved.data_manifest["execution_contract"] == NEXT
    comparison = ResearchRunComparisonService()
    for other in (replace(saved, execution_price=LEGACY, data_manifest={"execution_contract": LEGACY}),
                  replace(saved, execution_price="next_open", data_manifest={}),
                  replace(saved, data_manifest={"execution_contract": "future.v99"}),
                  replace(saved, metrics={"status": "cancelled"})):
        assert comparison.evaluate_comparability([saved, other]).status == ComparabilityStatus.INCOMPATIBLE
    with pytest.raises(ResearchRunIntegrityError):
        service.save_run(replace(metadata("unknown"), execution_price="future.v99"), *frames())
    with pytest.raises(ResearchRunIntegrityError):
        service.save_run(replace(metadata("conflict"), data_manifest={"execution_contract": LEGACY}), *frames())


def test_frozen_data_and_benchmark_unchanged_by_future_market_append(config):
    service = ResearchRunService(config)
    saved = service.save_run(metadata(), *frames())
    before = (file_hash(config.research_run_db_file), file_hash(saved.equity_path), file_hash(saved.trades_path))
    with sqlite3.connect(config.db_file) as conn:
        conn.execute("CREATE TABLE future_prices (date TEXT, close_cents INTEGER)")
        conn.execute("INSERT INTO future_prices VALUES ('2027-01-01', 999999)")
    loaded = ResearchRunService(config).load_run_data(saved.run_id)
    assert loaded.metadata.benchmark_results == {"frozen": {"return_bp": 120}}
    assert before == (file_hash(config.research_run_db_file), file_hash(saved.equity_path), file_hash(saved.trades_path))


def record(service, tier):
    return service.record_event(event_date="2026-01-02", decision_date="2026-01-02", symbol="2330",
        event_type="recommendation_included", event_family="recommendation", source_type="fixture",
        source_id=f"source-{tier}", source_snapshot_id=f"recommendation-{tier}", run_id="contract",
        as_of_date="2026-01-02", available_date="2026-01-02", evidence_tier=tier)


def test_review_preserves_separate_tiers_and_never_grants_credit(config):
    ResearchRunService(config).save_run(metadata(), *frames())
    repo = EvidenceEventRepository(config)
    service = EvidenceEventService(repo)
    for tier in ("replay", "forward", "paper", "live"):
        event = record(service, tier)
        repo.upsert_outcome(EvidenceOutcome(outcome_id=f"outcome-{tier}", event_id=event.event_id,
            window_days=5, forward_return_bp=100, outcome_status=EvidenceOutcomeStatus.READY))
    before = file_hash(config.db_file)
    proposal = service.build_review_proposal("contract", reviewer="Fixture reviewer", review_notes="僅隔離驗證",
                                             next_research_question="下一輪控制交易成本敏感度")
    assert {item["declared_tier"] for item in proposal.evidence} == {"replay", "forward", "paper", "live"}
    assert all(item["source_snapshot_id"] and item["outcomes"][0]["outcome_id"] for item in proposal.evidence)
    assert proposal.formal_credit_granted is proposal.promotion_allowed is False
    assert proposal.proposal_only is True
    assert "real_time_producer_acceptance_required" in proposal.missing_requirements
    assert file_hash(config.db_file) == before


def test_forward_outcome_keeps_replay_lineage_and_dry_run_is_read_only(config):
    repo = EvidenceEventRepository(config)
    event = record(EvidenceEventService(repo), "replay")
    with sqlite3.connect(config.db_file) as conn:
        conn.execute('CREATE TABLE daily_prices (日期 TEXT, 證券代號 TEXT, 收盤價 INTEGER)')
        conn.executemany('INSERT INTO daily_prices VALUES (?, ?, ?)',
                         [("2026-01-02", "2330", 100), ("2026-01-05", "2330", 102)])
    before = file_hash(config.db_file)
    calculator = ForwardPerformanceService(config)
    calculator.calculate(windows=(1,), dry_run=True, data_as_of_date="2026-01-05")
    assert file_hash(config.db_file) == before
    calculator.calculate(windows=(1,), dry_run=False, data_as_of_date="2026-01-05")
    outcome = repo.get_outcome(event.event_id, 1)
    assert outcome.metadata["evidence_lineage"]["declared_tier"] == "replay"
    assert outcome.metadata["evidence_lineage"]["run_id"] == "contract"
    assert outcome.metadata["is_execution_pnl"] is False


def test_ui_metadata_uses_frozen_version_and_cancelled_status():
    single = build_single_backtest_metadata(run_id="s", run_name="s", notes="", params={"execution_price": "close"},
        details={"execution_contract": NEXT}, report=SimpleNamespace(validation_status=None), created_at="now")
    assert single.execution_price == single.data_manifest["execution_contract"] == NEXT
    portfolio = build_recommendation_portfolio_metadata(run_id="p", run_name="p", notes="", config={},
        run_params={}, details={}, metrics={"execution_contract": NEXT, "status": "cancelled"}, created_at="now")
    assert portfolio.execution_price == NEXT
    assert portfolio.data_manifest["run_status"] == "cancelled"
    with pytest.raises(ValueError, match="不一致"):
        build_recommendation_portfolio_metadata(run_id="p", run_name="p", notes="", config={}, run_params={},
            details={"execution_contract": LEGACY}, metrics={"execution_contract": NEXT}, created_at="now")


def test_recommendation_metadata_preserves_actual_costs_lot_and_ratio_units():
    details = {"execution_contract": NEXT, "portfolio_credibility": {
        "execution_costs": {"fee_bps": "14.25", "slippage_bps": "5", "tax_bps": "30"},
        "share_sizing": {"lot_size": 1000}, "terminal_policy": "mark_open_positions_without_synthetic_liquidation"}}
    saved = build_recommendation_portfolio_metadata(run_id="p", run_name="p", notes="", config={},
        run_params={"fee_bps": "999", "stop_loss_pct": "0.10", "take_profit_pct": "0.25"},
        details=details, metrics={}, created_at="now")
    assert (saved.fee_bp_x100, saved.slippage_bp_x100, saved.stop_loss_bp, saved.take_profit_bp) == (1425, 500, 1000, 2500)
    assert saved.data_manifest["execution_assumptions"]["share_sizing"]["lot_size"] == 1000
    changed = replace(saved, data_manifest={**saved.data_manifest, "execution_assumptions": {
        **details["portfolio_credibility"], "execution_costs": {"fee_bps": "14.25", "slippage_bps": "5", "tax_bps": "10"}}})
    result = ResearchRunComparisonService().evaluate_comparability([saved, changed])
    assert result.status == ComparabilityStatus.CAUTION
    assert "交易成本模型不同" in result.reasons


def test_recovery_rejects_corrupt_files_ready_without_committing(config):
    service = ResearchRunService(config)
    with pytest.raises(InjectedResearchRunFailure):
        service.save_run(metadata(), *frames(), fail_at="after_hash")
    next(service.staging_dir.glob("*_trades.tmp.parquet")).write_bytes(b"corrupt staged fixture")
    service.reconcile_incomplete_saves()
    assert service.repository.get_raw_metadata_row("contract")["storage_state"] == "failed"
    assert service.list_runs() == []
