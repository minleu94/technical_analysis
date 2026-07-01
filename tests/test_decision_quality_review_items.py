from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from app_module.decision_quality_service import DecisionQualityService
from app_module.evidence_event_dtos import EvidenceEvent, EvidenceOutcome
from app_module.evidence_event_repository import EvidenceEventRepository
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "decision_quality_items.db"
    config.use_sqlite = True
    return config


def _seed_ready_recommendation_evidence(config: TWStockConfig, *, count: int) -> None:
    repo = EvidenceEventRepository(config)
    for index in range(count):
        decision_date = (date(2026, 6, 1) + timedelta(days=index)).isoformat()
        event = EvidenceEvent(
            event_id=f"evt-ready-{index}",
            event_hash=f"hash-ready-{index}",
            event_date=decision_date,
            decision_date=decision_date,
            symbol=f"24{index:02d}",
            event_type="recommendation_included",
            event_family="recommendation",
            source_type="recommendation",
            source_id=f"result-{index}",
            score_percentile_bp=9000,
            data_quality="observed",
            as_of_date=decision_date,
            available_date=decision_date,
        )
        repo.insert_event(event)
        repo.upsert_outcome(
            EvidenceOutcome(
                outcome_id=f"out-ready-{index}",
                event_id=event.event_id,
                window_days=20,
                forward_return_bp=700,
                benchmark_excess_bp=650,
                industry_excess_bp=500,
                max_adverse_excursion_bp=-100,
                max_favorable_excursion_bp=900,
                outcome_status="ready",
                data_quality="observed",
            )
        )


def _seed_degraded_event(config: TWStockConfig) -> None:
    repo = EvidenceEventRepository(config)
    event = EvidenceEvent(
        event_id="evt-low-quality",
        event_hash="hash-low-quality",
        event_date="2026-06-05",
        decision_date="2026-06-05",
        symbol="2881",
        event_type="recommendation_included",
        event_family="recommendation",
        source_type="recommendation",
        source_id="result-low-quality",
        data_quality="degraded",
        warnings=("input_degraded",),
        as_of_date="2026-06-05",
        available_date="2026-06-05",
    )
    repo.insert_event(event)


def test_missed_high_quality_signal_requires_ready_and_sufficient_sample(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_ready_recommendation_evidence(config, count=10)

    _review, items = DecisionQualityService(config).build_review(
        review_type="monthly",
        start_date="2026-06-01",
        end_date="2026-06-30",
        min_sample_size=10,
    )

    missed = [item for item in items if item.item_type == "missed_high_quality_signal"]
    assert len(missed) == 1
    assert missed[0].severity == "low"
    assert "process_review" in missed[0].reason_codes_json


def test_insufficient_sample_does_not_create_missed_signal_item(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_ready_recommendation_evidence(config, count=4)

    review, items = DecisionQualityService(config).build_review(
        review_type="monthly",
        start_date="2026-06-01",
        end_date="2026-06-30",
        min_sample_size=10,
    )

    assert review.review_status == "incomplete"
    assert "insufficient_review_sample" in review.warnings_json
    assert "missed_high_quality_signal" not in {item.item_type for item in items}


def test_low_quality_data_used_creates_review_item(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_degraded_event(config)

    _review, items = DecisionQualityService(config).build_review(
        review_type="monthly",
        start_date="2026-06-01",
        end_date="2026-06-30",
        min_sample_size=1,
    )

    low_quality = [item for item in items if item.item_type == "low_quality_data_used"]
    assert len(low_quality) == 1
    assert low_quality[0].related_evidence_event_id == "evt-low-quality"
