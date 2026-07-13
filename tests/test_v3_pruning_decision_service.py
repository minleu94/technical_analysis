from app_module.v3_pruning_decision_service import V3PruningDecisionService


def test_insufficient_sample_always_defers() -> None:
    proposal = V3PruningDecisionService(minimum_sample=30).propose(
        slice_id="recommendation:included",
        metrics={"sample_count": 12, "hit_rate_bp": 8000, "score_monotonic": True},
    )

    assert proposal.action == "defer"
    assert proposal.apply_action is False
    assert "insufficient_sample" in proposal.reason_codes


def test_manual_validation_pending_always_defers() -> None:
    proposal = V3PruningDecisionService(minimum_sample=30).propose(
        slice_id="recommendation:included",
        metrics={"sample_count": 80, "hit_rate_bp": 8000, "score_monotonic": True},
        manual_validation_status="PENDING_MANUAL_VALIDATION",
    )

    assert proposal.action == "defer"
    assert "manual_validation_pending" in proposal.reason_codes


def test_stable_signal_is_retained_as_non_applying_proposal() -> None:
    proposal = V3PruningDecisionService(minimum_sample=30).propose(
        slice_id="recommendation:included",
        metrics={
            "sample_count": 80,
            "hit_rate_bp": 6200,
            "payoff_ratio_bp": 13000,
            "score_monotonic": True,
            "mae_mfe_ready": True,
        },
        manual_validation_status="COMPLETED",
    )

    assert proposal.action == "retain"
    assert proposal.apply_action is False
    assert proposal.to_dict()["review_required"] is True


def test_weak_non_monotonic_signal_is_restricted_not_auto_retired() -> None:
    proposal = V3PruningDecisionService(minimum_sample=30).propose(
        slice_id="recommendation:included",
        metrics={"sample_count": 80, "hit_rate_bp": 3500, "score_monotonic": False},
        manual_validation_status="COMPLETED",
    )

    assert proposal.action == "restrict"
    assert proposal.apply_action is False
