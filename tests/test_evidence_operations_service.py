from __future__ import annotations

from pathlib import Path

from app_module.decision_quality_dtos import DecisionQualityItem, DecisionQualityReview
from app_module.decision_quality_repository import DecisionQualityRepository
from app_module.evidence_operations_service import EvidenceOperationsService
from app_module.signal_decay_dtos import SignalDecayObservation
from app_module.signal_decay_repository import SignalDecayRepository
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence-ops.db"
    config.use_sqlite = True
    return config


def _review() -> DecisionQualityReview:
    return DecisionQualityReview(
        review_id="dqr-weekly",
        review_hash="sha256:dqr-weekly",
        review_period_start="2026-06-24",
        review_period_end="2026-06-30",
        review_type="weekly",
        evidence_event_count=12,
        trade_count=2,
        journal_entry_count=0,
        unreviewed_decay_candidate_count=1,
        decision_quality_score_bp=6200,
        review_status="needs_review",
        quality="degraded",
        warnings_json=["journal_missing"],
    )


def _item() -> DecisionQualityItem:
    return DecisionQualityItem(
        item_id="dqi-decay",
        review_id="dqr-weekly",
        item_type="unreviewed_signal_decay",
        related_decay_id="decay-1",
        source_type="event_type",
        source_id="recommendation_included",
        severity="medium",
        status="open",
        reason_codes_json=["signal_decay_unreviewed"],
        suggested_review_question="這個 signal decay candidate 是否需要進入人工 lifecycle review？",
    )


def _decay() -> SignalDecayObservation:
    return SignalDecayObservation(
        decay_id="decay-1",
        decay_hash="sha256:decay-1",
        observation_date="2026-06-30",
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        event_type="recommendation_included",
        event_family="recommendation",
        sample_size_short=30,
        sample_size_long=120,
        forward_excess_short_bp=-500,
        forward_excess_long_bp=200,
        decay_score_bp=6500,
        decay_status="decaying",
        suggested_lifecycle_action="demote_candidate",
        confidence="medium",
        evidence_event_count=120,
        quality="degraded",
        warnings_json=["missing_live_gap_evidence"],
    )


def _readiness(*args, **kwargs) -> dict[str, object]:
    return {
        "readiness": "ready_for_manual_confirm",
        "blocking_gaps": ["why_not_exclusion_payload_missing"],
        "warnings": ["liquidity_gate_payload_missing"],
        "required_manual_checks": ["manual approval before any future scheduler enablement"],
        "production_scheduler_allowed": False,
        "latest_smoke_status": "passed",
        "working_copy_confirm_passed": True,
    }


def test_weekly_review_collects_manual_approval_and_lifecycle_candidates(tmp_path: Path) -> None:
    config = _config(tmp_path)
    decision_repo = DecisionQualityRepository(config)
    decision_repo.save_review(_review(), items=[_item()])
    decision_repo.create_action_item(
        review_id="dqr-weekly",
        item_id="dqi-decay",
        description="人工確認 recommendation_included 是否只需觀察或進入 demote review",
        owner="human",
    )
    SignalDecayRepository(config).save_observation(_decay())

    report = EvidenceOperationsService(config, readiness_evaluator=_readiness).build_weekly_review(
        start_date="2026-06-24",
        end_date="2026-06-30",
    )

    assert report.manual_approval.production_scheduler_allowed is False
    assert report.manual_approval.readiness == "ready_for_manual_confirm"
    assert report.status == "needs_manual_review"
    assert report.decision_quality.open_item_count == 1
    assert report.decision_quality.action_item_count == 1
    assert report.signal_decay.demote_candidate_count == 1
    assert report.manual_lifecycle_candidates[0]["suggested_lifecycle_action"] == "demote_candidate"
    assert "review_signal_decay_candidate" in report.next_actions
    assert "apply_lifecycle_action" not in report.next_actions


def test_weekly_review_with_insufficient_evidence_stays_coverage_only(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = EvidenceOperationsService(config, readiness_evaluator=_readiness).build_weekly_review(
        start_date="2026-06-24",
        end_date="2026-06-30",
    )

    assert report.status == "coverage_only"
    assert report.decision_quality.reviews_count == 0
    assert report.signal_decay.observations_count == 0
    assert "collect_more_evidence" in report.next_actions
    assert "strategy_conclusion" not in " ".join(report.next_actions)

