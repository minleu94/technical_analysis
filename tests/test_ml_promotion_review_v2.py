from __future__ import annotations

import pytest

from ml_module.promotion_review_package_v2 import MLPromotionReviewPackageV2Service


def _build_package(**overrides: object):
    values: dict[str, object] = {
        "experiment_id": "experiment:rule-vs-hgb-v1",
        "comparison_artifact_id": "comparison:rule-vs-hgb-v1",
        "comparison_review_status": "eligible_for_promotion_review",
        "formal_oos_decision_id": "formal-oos:core-v1",
        "forward_evidence_ids": ("forward:1",),
        "paper_evidence_ids": ("paper:1",),
        "source_decision_revision_ids": ("source-decision:1",),
        "shadow_observed_days": 20,
        "drift_statuses": ("stable",),
        "calibration_status": "passed",
        "rollback_artifact_id": "rollback:rule-v1",
    }
    values.update(overrides)
    return MLPromotionReviewPackageV2Service().build(**values)  # type: ignore[arg-type]


def test_twenty_shadow_days_only_mark_pipeline_operational() -> None:
    package = _build_package()

    assert package.shadow_pipeline_operational is True
    assert package.review_status == "defer"
    assert "formal_oos_not_allowed" in package.blockers
    assert package.formal_oos_allowed is False
    assert package.apply_promotion is False
    assert package.auto_promotion_allowed is False
    assert package.retrain_allowed is False
    assert package.production_scheduler_allowed is False
    assert package.trading_allowed is False
    assert package.production_blend_alpha_bp == 0


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    [
        ("forward_evidence_ids", (), "missing_forward_evidence"),
        ("paper_evidence_ids", (), "missing_paper_evidence"),
        ("source_decision_revision_ids", (), "missing_source_decision_revisions"),
        ("comparison_artifact_id", "", "missing_comparison_artifact"),
        ("drift_statuses", (), "missing_drift_status"),
        ("calibration_status", "pending", "calibration_not_passed"),
        ("rollback_artifact_id", "", "missing_rollback_artifact"),
    ],
)
def test_missing_required_citation_defers_review(
    field: str, value: object, expected_blocker: str
) -> None:
    package = _build_package(**{field: value})

    assert package.review_status == "defer"
    assert expected_blocker in package.blockers


def test_service_rejects_attempt_to_enable_formal_oos() -> None:
    with pytest.raises(ValueError, match="formal_oos_allowed"):
        MLPromotionReviewPackageV2Service().build(
            experiment_id="experiment:rule-vs-hgb-v1",
            comparison_artifact_id="comparison:rule-vs-hgb-v1",
            comparison_review_status="eligible_for_promotion_review",
            formal_oos_decision_id="formal-oos:core-v1",
            formal_oos_allowed=True,
            forward_evidence_ids=("forward:1",),
            paper_evidence_ids=("paper:1",),
            source_decision_revision_ids=("source-decision:1",),
            shadow_observed_days=20,
            drift_statuses=("stable",),
            calibration_status="passed",
            rollback_artifact_id="rollback:rule-v1",
        )
