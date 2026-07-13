from ml_module.promotion_review_package import MLPromotionReviewPackageService


def test_complete_evidence_only_becomes_human_review_candidate() -> None:
    package = MLPromotionReviewPackageService(minimum_shadow_days=20).build(
        model_id="m1",
        dataset_id="d1",
        champion_model_id="rule-champion-v1",
        shadow_observed_days=25,
        comparison_status="challenger_directionally_better",
        drift_statuses=("stable", "moderate_drift"),
        calibration_status="passed",
        rollback_artifact="rollback/rule-champion-v1.json",
        verification_artifacts=("walk-forward.json", "comparison.json"),
    )

    assert package.review_status == "eligible_for_human_review"
    assert package.auto_promotion_allowed is False
    assert package.apply_promotion is False
    assert package.rollback_required is True


def test_major_drift_defers_review() -> None:
    package = MLPromotionReviewPackageService().build(
        model_id="m1",
        dataset_id="d1",
        champion_model_id="rule-v1",
        shadow_observed_days=30,
        comparison_status="challenger_directionally_better",
        drift_statuses=("major_drift",),
        calibration_status="passed",
        rollback_artifact="rollback.json",
        verification_artifacts=("wf.json",),
    )

    assert package.review_status == "defer"
    assert "major_feature_drift" in package.blockers


def test_missing_rollback_artifact_blocks_review() -> None:
    package = MLPromotionReviewPackageService().build(
        model_id="m1",
        dataset_id="d1",
        champion_model_id="rule-v1",
        shadow_observed_days=30,
        comparison_status="challenger_directionally_better",
        drift_statuses=("stable",),
        calibration_status="passed",
        rollback_artifact="",
        verification_artifacts=("wf.json",),
    )

    assert package.review_status == "defer"
    assert "missing_rollback_artifact" in package.blockers


def test_short_shadow_window_blocks_review() -> None:
    package = MLPromotionReviewPackageService(minimum_shadow_days=20).build(
        model_id="m1",
        dataset_id="d1",
        champion_model_id="rule-v1",
        shadow_observed_days=19,
        comparison_status="mixed_or_tied",
        drift_statuses=("stable",),
        calibration_status="passed",
        rollback_artifact="rollback.json",
        verification_artifacts=("wf.json",),
    )

    assert "insufficient_shadow_days" in package.blockers
