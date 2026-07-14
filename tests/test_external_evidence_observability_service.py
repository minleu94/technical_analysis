from __future__ import annotations

from app_module.external_evidence_observability import ExternalEvidenceObservabilityService


def test_service_projects_read_only_identity_status_and_frozen_metrics() -> None:
    metrics = {"primary_effect_bp": 50, "downside_ci_low_bp": 0}

    projection = ExternalEvidenceObservabilityService().project(
        review_status="defer",
        blockers=("formal_oos_not_allowed",),
        missing_requirements=("formal_oos",),
        degraded=True,
        artifact_citations=("comparison:rule-vs-hgb-v1", "rollback:rule-v1"),
        model_id="model:hgb-core-v1",
        dataset_id="dataset:core-v1",
        prediction_ids=("prediction:2026-07-13:2330",),
        frozen_domain_metrics=metrics,
    )

    assert projection.review_status == "defer"
    assert projection.degraded is True
    assert projection.artifact_citations == (
        "comparison:rule-vs-hgb-v1",
        "rollback:rule-v1",
    )
    assert projection.frozen_domain_metrics == metrics
    assert projection.frozen_domain_metrics is not metrics
    assert projection.apply_promotion is False
    assert projection.promotion_allowed is False
    assert projection.retrain_allowed is False
    assert projection.scheduler_allowed is False
    assert projection.trading_allowed is False
    assert projection.formal_oos_allowed is False
    assert projection.production_blend_alpha_bp == 0
