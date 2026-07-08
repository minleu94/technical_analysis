from app_module.v3_effectiveness_dtos import V3EffectivenessSlice
from app_module.v3_effectiveness_read_model import V3EffectivenessReadModel
from app_module.v3_gap_classifier import classify_v3_gap


def test_v3_gap_classifier_marks_manual_validation_pending() -> None:
    gap = classify_v3_gap("manual_validation_missing", source_trace="docs/06_qa")

    assert gap.classification == "manual_validation_pending"
    assert gap.manual_validation_status == "PENDING_MANUAL_VALIDATION"
    assert gap.severity == "warning"


def test_effectiveness_slice_serializes_sufficiency_without_investment_claim() -> None:
    dto = V3EffectivenessSlice(
        slice_id="recommendation_included",
        event_family="recommendation",
        event_type="recommendation_included",
        source_type="persisted_recommendation",
        dashboard_surface="evidence_review",
        sample_count=18,
        ready_outcome_count=12,
        pending_outcome_count=6,
        missing_outcome_count=0,
        benchmark_coverage_bp=10000,
        industry_coverage_bp=500,
        sample_sufficiency_label="insufficient_sample",
        confidence_label="none",
        quality="DEGRADED",
        warnings=("sample_below_minimum",),
        limitations=("不是交易建議",),
    )

    payload = dto.to_dict()

    assert payload["sample_sufficiency_label"] == "insufficient_sample"
    assert payload["confidence_label"] == "none"
    assert "不是交易建議" in payload["limitations"]


def test_read_model_labels_review_ready_when_sample_and_outcomes_sufficient() -> None:
    rows = [
        {
            "event_family": "portfolio_alert",
            "event_type": "portfolio_alert_triggered",
            "source_type": "daily_decision_snapshot",
            "ready_outcome_count": 80,
            "pending_outcome_count": 0,
            "missing_outcome_count": 0,
            "benchmark_coverage_bp": 10000,
            "industry_coverage_bp": 3500,
            "warnings": (),
        }
    ]

    report = V3EffectivenessReadModel(min_sample_size=30).build_report(rows=rows)

    first = report.slices[0]
    assert first.sample_sufficiency_label == "review_ready"
    assert first.confidence_label in {"low", "medium", "needs_manual_validation"}
    assert report.access_boundary["production_scheduler_allowed"] is False


def test_read_model_groups_rows_and_preserves_read_only_boundary() -> None:
    report = V3EffectivenessReadModel(min_sample_size=30).build_report(
        rows=[
            {
                "event_family": "recommendation",
                "event_type": "recommendation_included",
                "source_type": "persisted_recommendation",
                "ready_outcome_count": 10,
                "pending_outcome_count": 1,
                "missing_outcome_count": 0,
                "warnings": ("sample_below_minimum",),
            },
            {
                "event_family": "recommendation",
                "event_type": "recommendation_included",
                "source_type": "persisted_recommendation",
                "ready_outcome_count": 8,
                "pending_outcome_count": 1,
                "missing_outcome_count": 0,
                "warnings": ("manual_validation_missing",),
            },
        ]
    )

    first = report.slices[0]
    assert first.sample_count == 20
    assert first.sample_sufficiency_label == "insufficient_sample"
    assert report.access_boundary["writes_allowed"] is False
    assert report.manual_validation_status == "PENDING_MANUAL_VALIDATION"
