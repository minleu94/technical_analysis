from __future__ import annotations

from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.evidence_event_dtos import EvidenceDataQuality
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.live_research_gap_service import LiveResearchGapService
from data_module.config import TWStockConfig


def _config(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "gap.db"
    config.use_sqlite = True
    return config


def test_symbol_date_candidate_is_low_confidence_and_not_confirmed_link(tmp_path):
    config = _config(tmp_path)
    event_repo = EvidenceEventRepository(config)
    event = EvidenceEventService(event_repo).record_event(
        event_date="2026-07-01",
        decision_date="2026-07-01",
        symbol="2330",
        event_type="recommendation_included",
        event_family="recommendation",
        source_type="recommendation",
        source_id="rec-001",
        data_quality=EvidenceDataQuality.OBSERVED,
        as_of_date="2026-07-01",
        available_date="2026-07-01",
    )
    position = PositionDTO(
        position_id="default:2330",
        portfolio_id="default",
        stock_code="2330",
        stock_name="TSMC",
        quantity=1000.0,
        average_cost=100.0,
        invested_amount=100000.0,
        opened_at="2026-07-01",
        last_trade_date="2026-07-01",
        source_type="manual",
        source_id="",
        source_summary={"portfolio_mode": "simulated"},
        current_price=101.0,
    )

    observation = LiveResearchGapService(config).build_gap_for_position(
        position,
        observation_date="2026-07-08",
    )

    assert observation.evidence_event_id == ""
    assert observation.evidence_outcome_id == ""
    assert observation.metadata_json["match_confidence"] == "low"
    assert observation.metadata_json["candidate_evidence_event_ids"] == [event.event_id]
    assert "fuzzy_match_candidate_only" in observation.warnings_json
