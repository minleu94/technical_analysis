from __future__ import annotations

from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.evidence_event_dtos import EvidenceDataQuality, EvidenceOutcomeStatus
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.live_research_gap_repository import LiveResearchGapRepository
from app_module.live_research_gap_service import LiveResearchGapService
from data_module.config import TWStockConfig


def _config(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "gap.db"
    config.use_sqlite = True
    return config


def _position(**overrides) -> PositionDTO:
    base = {
        "position_id": "default:2330",
        "portfolio_id": "default",
        "stock_code": "2330",
        "stock_name": "TSMC",
        "quantity": 1000.0,
        "average_cost": 100.0,
        "invested_amount": 100000.0,
        "opened_at": "2026-07-01",
        "last_trade_date": "2026-07-01",
        "source_type": "research_run",
        "source_id": "run-001",
        "source_snapshot_hash": "sha256:source",
        "source_summary": {
            "research_run_id": "run-001",
            "strategy_version_id": "strategy-v1",
            "expected_return_bp": 500,
            "entry_price": "98",
            "regime": "bull",
            "current_regime": "bear",
            "portfolio_mode": "simulated",
        },
        "trade_ids": ["trade-001"],
        "current_price": 103.0,
    }
    base.update(overrides)
    return PositionDTO(**base)


def _seed_event_and_outcome(config):
    event_repo = EvidenceEventRepository(config)
    event = EvidenceEventService(event_repo).record_event(
        event_date="2026-07-01",
        decision_date="2026-07-01",
        symbol="2330",
        event_type="recommendation_included",
        event_family="recommendation",
        source_type="research_run",
        source_id="run-001",
        run_id="run-001",
        strategy_version_id="strategy-v1",
        regime="bull",
        liquidity_state="normal",
        data_quality=EvidenceDataQuality.OBSERVED,
        as_of_date="2026-07-01",
        available_date="2026-07-01",
        metadata={"source_result_id": "run-001"},
    )
    event_repo.upsert_outcome(
        event_repo._row_to_outcome(
            {
                "outcome_id": "out-001",
                "event_id": event.event_id,
                "window_days": 5,
                "window_type": "trading_days",
                "return_basis": "close_to_close_event_date",
                "event_price_date": "2026-07-01",
                "event_close": "100",
                "outcome_price_date": "2026-07-08",
                "outcome_close": "104",
                "forward_return_bp": 400,
                "benchmark_return_bp": 300,
                "benchmark_excess_bp": 100,
                "industry_return_bp": 350,
                "industry_excess_bp": 50,
                "max_adverse_excursion_bp": -150,
                "max_favorable_excursion_bp": 450,
                "tradable_flag": 1,
                "limit_up_down_flag": 0,
                "suspended_flag": 0,
                "liquidity_cost_bp": 20,
                "outcome_status": EvidenceOutcomeStatus.READY.value,
                "data_quality": EvidenceDataQuality.OBSERVED.value,
                "warnings_json": "[]",
                "calculated_at": "2026-07-08T00:00:00",
                "data_as_of_date": "2026-07-08",
                "metadata_json": "{}",
            }
        )
    )
    return event


def test_build_gap_for_position_links_source_trace_and_evidence(tmp_path):
    config = _config(tmp_path)
    event = _seed_event_and_outcome(config)
    service = LiveResearchGapService(config)

    observation = service.build_gap_for_position(_position(), observation_date="2026-07-08")

    assert observation.evidence_event_id == event.event_id
    assert observation.evidence_outcome_id == "out-001"
    assert observation.research_run_id == "run-001"
    assert observation.portfolio_mode == "simulated"
    assert observation.portfolio_return_bp == 300
    assert observation.forward_evidence_return_bp == 400
    assert observation.gap_vs_forward_evidence_bp == -100
    categories = {item["category"] for item in observation.attribution_json}
    assert {"execution_gap", "market_regime_gap", "signal_gap"}.issubset(categories)
    assert observation.metadata_json["match_confidence"] == "high"


def test_missing_research_run_and_evidence_outcome_become_diagnostics(tmp_path):
    config = _config(tmp_path)
    service = LiveResearchGapService(config)

    observation = service.build_gap_for_position(
        _position(source_id="", source_type="", source_summary={}, current_price=101.0),
        observation_date="2026-07-08",
    )

    categories = {item["category"] for item in observation.attribution_json}
    assert "source_trace_gap" in categories
    assert "insufficient_evidence" in categories
    assert observation.research_run_id == ""
    assert observation.evidence_event_id == ""
    assert observation.portfolio_mode == "unknown"
    assert "source_trace_missing" in observation.warnings_json


def test_confirm_persists_but_dry_run_does_not(tmp_path):
    config = _config(tmp_path)
    _seed_event_and_outcome(config)
    service = LiveResearchGapService(config)
    repo = LiveResearchGapRepository(config)

    dry = service.save_gap_observation(
        service.build_gap_for_position(_position(), observation_date="2026-07-08"),
        confirm=False,
    )
    assert dry.saved is False
    assert repo.list_observations() == []

    confirmed = service.save_gap_observation(dry.observation, confirm=True)
    assert confirmed.saved is True
    assert len(repo.list_observations()) == 1
