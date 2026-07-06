from __future__ import annotations

from pathlib import Path

from app_module.agent_evidence_access_service import (
    AgentEvidenceAccessService,
    build_agent_permission_model,
    build_ai_report_template,
)
from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
)
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.live_research_gap_dtos import LiveResearchGapObservation
from app_module.live_research_gap_repository import LiveResearchGapRepository
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_repository import ResearchRunRepository
from app_module.strategy_lifecycle_repository import (
    LifecycleEvidenceRepository,
    LifecycleEvidenceStatus,
)
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.use_sqlite = True
    return config


def _event() -> EvidenceEvent:
    return EvidenceEvent(
        event_id="evt-001",
        event_hash="sha256:evt-001",
        event_date="2026-07-06",
        decision_date="2026-07-06",
        symbol="2330",
        event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
        event_family="recommendation",
        source_type="recommendation_result",
        source_id="rec-001",
        source_snapshot_id="snapshot-001",
        strategy_version_id="strategy-v1",
        profile_id="profile-default",
        run_id="run-001",
        reason_codes=("score_threshold_pass",),
        risk_codes=("liquidity_ok",),
        score_bp=8200,
        score_percentile_bp=9100,
        regime="trend",
        sector="semiconductor",
        liquidity_state="normal",
        data_quality=EvidenceDataQuality.OBSERVED,
        warnings=(),
        as_of_date="2026-07-06",
        available_date="2026-07-06",
        source_version="test-fixture",
        benchmark_id="TAIEX",
        industry_benchmark_id="semiconductor",
        metadata={"return_basis": "close_to_close_event_date"},
    )


def _outcome(event_id: str) -> EvidenceOutcome:
    return EvidenceOutcome(
        outcome_id="out-001",
        event_id=event_id,
        window_days=5,
        event_price_date="2026-07-06",
        event_close="100.00",
        outcome_price_date="2026-07-13",
        outcome_close="102.50",
        forward_return_bp=250,
        benchmark_return_bp=100,
        benchmark_excess_bp=150,
        industry_return_bp=90,
        industry_excess_bp=160,
        tradable_flag=True,
        outcome_status=EvidenceOutcomeStatus.READY,
        data_quality=EvidenceDataQuality.OBSERVED,
        warnings=(),
        calculated_at="2026-07-13T16:00:00",
        data_as_of_date="2026-07-13",
        metadata={"source": "unit-test"},
    )


def _metadata(run_id: str = "run-001") -> ResearchRunMetadataDTO:
    return ResearchRunMetadataDTO(
        run_id=run_id,
        run_name="V1.9 fixture run",
        run_type="single_backtest",
        strategy_id="baseline_score",
        strategy_version="1.0.0",
        parameter_contract_version="v1",
        normalized_params={"buy_score": 70, "sell_score": 40},
        universe=["2330"],
        start_date="2026-01-02",
        end_date="2026-03-31",
        data_cutoff_date="2025-12-31",
        data_fingerprint="sha256:data",
        fingerprint_algorithm="sha256",
        data_manifest={"factor_snapshot": {"records": [{"quality": "observed"}]}},
        capital_cents=1_000_000_00,
        fee_bp_x100=1425,
        slippage_bp_x100=500,
        execution_price="next_open",
        sizing_mode="fixed_amount",
        metrics={
            "total_return": "0.08",
            "sharpe_ratio": "1.20",
            "max_drawdown": "0.03",
            "win_rate": "0.60",
            "total_trades": 24,
        },
        regime_breakdown={"trend": {"trades": 24}},
        benchmark_results={"taiex": {"excess_return_bp": 300}},
        payload_hash=f"sha256:{run_id}",
        equity_path="parquet/run-001_equity.parquet",
        trades_path="parquet/run-001_trades.parquet",
        created_at="2026-07-06T12:00:00",
    )


def _gap_observation() -> LiveResearchGapObservation:
    return LiveResearchGapObservation(
        gap_id="gap-001",
        gap_hash="sha256:gap-001",
        observation_date="2026-07-06",
        position_id="simulated:2330",
        symbol="2330",
        portfolio_mode="simulated",
        source_type="research_run",
        source_id="run-001",
        research_run_id="run-001",
        strategy_version_id="strategy-v1",
        evidence_event_id="evt-001",
        evidence_outcome_id="out-001",
        entry_date="2026-07-01",
        entry_price="100.00",
        current_price_date="2026-07-06",
        current_price="101.00",
        holding_days=3,
        portfolio_return_bp=100,
        research_expected_return_bp=250,
        forward_evidence_return_bp=250,
        benchmark_excess_bp=80,
        gap_vs_research_bp=-150,
        gap_vs_forward_evidence_bp=-150,
        gap_vs_benchmark_bp=20,
        condition_status="valid",
        chip_risk_level="neutral",
        regime_at_entry="trend",
        regime_current="trend",
        data_quality="observed",
        warnings_json=[],
        attribution_json=[{"category": "execution_gap", "confidence": "low"}],
        metadata_json={"event_type": "recommendation_included"},
    )


def test_permission_model_is_read_only_and_denies_trading_actions() -> None:
    model = build_agent_permission_model()
    template = build_ai_report_template()

    assert model["access_mode"] == "read_only"
    assert "write_database" in model["denied_actions"]
    assert "modify_strategy" in model["denied_actions"]
    assert "place_order" in model["denied_actions"]
    assert "evidence_rows" in template["required_sections"]
    assert any("不是買賣建議" in item for item in template["limitations"])


def test_evidence_query_returns_events_outcomes_and_source_trace(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repository = EvidenceEventRepository(config)
    saved_event = repository.insert_event(_event())
    repository.upsert_outcome(_outcome(saved_event.event_id))

    service = AgentEvidenceAccessService(config, evidence_db_path=config.db_file)
    payload = service.query_evidence_events(symbol="2330", include_outcomes=True)
    summary = service.summarize_forward_evidence(
        group_by="event_type",
        window_days=5,
        min_sample_size=1,
        symbol="2330",
    )

    assert payload["access_boundary"]["mode"] == "read_only"
    assert payload["events_count"] == 1
    row = payload["events"][0]
    assert row["event_id"] == saved_event.event_id
    assert row["data_quality"] == "observed"
    assert row["source_trace"]["source_type"] == "recommendation_result"
    assert row["source_trace"]["source_id"] == "rec-001"
    assert row["outcomes"][0]["forward_return_bp"] == 250
    assert summary["rows"][0]["group_key"] == "recommendation_included"
    assert summary["rows"][0]["sample_size"] == 1


def test_research_run_query_reads_metadata_and_missing_db_does_not_create_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ResearchRunRepository(config).insert_metadata(_metadata())

    service = AgentEvidenceAccessService(config, research_db_path=config.research_run_db_file)
    payload = service.query_research_runs(run_type="single_backtest", strategy_id="baseline_score")
    missing_path = tmp_path / "missing" / "research_runs.db"
    missing_payload = AgentEvidenceAccessService(config, research_db_path=missing_path).query_research_runs()

    assert payload["access_boundary"]["mode"] == "read_only"
    assert payload["runs_count"] == 1
    assert payload["runs"][0]["run_id"] == "run-001"
    assert payload["runs"][0]["source_trace"]["payload_hash"] == "sha256:run-001"
    assert missing_payload["runs"] == []
    assert missing_payload["diagnostics"]
    assert not missing_path.exists()


def test_portfolio_review_query_reads_saved_gap_and_lifecycle_evidence(tmp_path: Path) -> None:
    config = _config(tmp_path)
    run = ResearchRunRepository(config).insert_metadata(_metadata())
    LiveResearchGapRepository(config).save_observation(_gap_observation())
    LifecycleEvidenceRepository(config).record_decision(
        run=run,
        version_id="strategy-v1",
        status=LifecycleEvidenceStatus.PROPOSED,
        reason="fixture proposal",
    )

    service = AgentEvidenceAccessService(
        config,
        evidence_db_path=config.db_file,
        research_db_path=config.research_run_db_file,
    )
    payload = service.query_portfolio_review_evidence(
        symbol="2330",
        run_id="run-001",
        strategy_version_id="strategy-v1",
    )

    assert payload["portfolio_review_scope"] == "saved_evidence_only"
    assert payload["live_research_gap_observations_count"] == 1
    assert payload["live_research_gap_observations"][0]["gap_id"] == "gap-001"
    assert payload["strategy_lifecycle_evidence_count"] == 1
    assert payload["strategy_lifecycle_evidence"][0]["run_id"] == "run-001"
    assert any("Portfolio Review snapshot" in item for item in payload["limitations"])
