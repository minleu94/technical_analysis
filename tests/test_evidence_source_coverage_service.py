from __future__ import annotations

from datetime import date
from pathlib import Path

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import build_stored_decision_desk_snapshot
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_pipeline_runner_dtos import (
    READINESS_DRY_RUN_ONLY,
    READINESS_NOT_READY,
    READINESS_READY_FOR_DESIGN,
)
from app_module.evidence_source_coverage_service import EvidenceSourceCoverageService
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig
from tests.test_decision_desk_snapshot_repository import _snapshot


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_snapshot(config: TWStockConfig) -> None:
    DecisionDeskSnapshotRepository(config).save_snapshot(
        build_stored_decision_desk_snapshot(_snapshot(date(2026, 6, 30)))
    )


def _recommendation(*, result_id: str = "coverage-rec", with_payloads: bool = False) -> RecommendationResultDTO:
    why_not_payload = [{"stock_code": "1101", "exclusion_reason_codes": ["weak_relative_strength"]}]
    liquidity_payload = [{"stock_code": "2201", "exclusion_reason_codes": ["low_liquidity"]}]
    return RecommendationResultDTO(
        result_id=result_id,
        result_name="Coverage fixture",
        config={},
        recommendations=[
            RecommendationDTO(
                stock_code="2330",
                stock_name="TSMC",
                close_price=100.0,
                price_change=1.0,
                total_score=80.0,
                indicator_score=30.0,
                pattern_score=30.0,
                volume_score=20.0,
                recommendation_reasons="rank_top",
                industry="Semi",
                regime_match=True,
            )
        ],
        why_not_payload_json=why_not_payload if with_payloads else [],
        liquidity_gate_payload_json=liquidity_payload if with_payloads else [],
    )


def _seed_recommendation(config: TWStockConfig, *, with_payloads: bool = False) -> str:
    return RecommendationRepository(config).save_result(_recommendation(with_payloads=with_payloads))


def test_source_coverage_flags_durable_source_gaps_as_blocking(tmp_path: Path) -> None:
    config = _config(tmp_path)

    summary = EvidenceSourceCoverageService(config, db_path=config.db_file).inspect(
        decision_date="2026-07-01"
    ).to_dict()

    assert summary["scheduler_readiness"] == READINESS_NOT_READY
    assert "recommendation_persisted_missing" in summary["blocking_gaps"]
    assert "decision_desk_snapshot_missing" in summary["blocking_gaps"]
    assert "why_not_payload_missing" in summary["warnings"]
    assert "liquidity_gate_payload_missing" in summary["warnings"]
    assert "why_not_exclusion_payload_missing" not in summary["blocking_gaps"]


def test_source_coverage_treats_exclusion_payload_gaps_as_warnings(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_snapshot(config)
    _seed_recommendation(config, with_payloads=False)

    summary = EvidenceSourceCoverageService(config, db_path=config.db_file).inspect(
        decision_date="2026-07-01"
    ).to_dict()

    assert summary["scheduler_readiness"] == READINESS_DRY_RUN_ONLY
    assert summary["blocking_gaps"] == []
    assert summary["warnings"] == ["why_not_payload_missing", "liquidity_gate_payload_missing"]
    assert summary["recommendation_persisted_available"] is True
    assert summary["recommendation_exclusion_payload_available"] is False
    assert summary["watchlist_trigger_capture_ready"] is True
    assert summary["portfolio_alert_capture_ready"] is True
    assert summary["risk_prompt_capture_ready"] is True
    assert summary["source_capability_status"]["recommendation.exclusion.why_not_payload"] == "partial"


def test_source_coverage_is_ready_for_design_when_payloads_and_snapshot_are_present(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_snapshot(config)
    _seed_recommendation(config, with_payloads=True)

    summary = EvidenceSourceCoverageService(config, db_path=config.db_file).inspect(
        decision_date="2026-07-01"
    ).to_dict()

    assert summary["scheduler_readiness"] == READINESS_READY_FOR_DESIGN
    assert summary["blocking_gaps"] == []
    assert summary["warnings"] == []
    assert summary["recommendation_exclusion_payload_available"] is True
    assert summary["why_not_capture_ready"] is True
    assert summary["liquidity_gate_capture_ready"] is True
