from __future__ import annotations

from app_module.evidence_metric_applicability import EvidenceMetricApplicability


def test_risk_prompt_score_is_not_applicable() -> None:
    result = EvidenceMetricApplicability().classify(
        event_family="risk_prompt",
        event_type="risk_prompt_data_quality",
    )

    assert result.score_requirement == "not_applicable"
    assert result.supported_metrics == ("alert_quality",)


def test_recommendation_included_requires_score() -> None:
    result = EvidenceMetricApplicability().classify(
        event_family="recommendation",
        event_type="recommendation_included",
    )

    assert result.score_requirement == "required"
    assert "precision_at_k" in result.supported_metrics


def test_unknown_family_keeps_score_optional() -> None:
    result = EvidenceMetricApplicability().classify(
        event_family="custom_evidence",
        event_type="custom_observation",
    )

    assert result.score_requirement == "optional"
