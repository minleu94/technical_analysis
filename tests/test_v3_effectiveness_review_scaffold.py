from app_module.v3_effectiveness_read_model import V3EffectivenessReadModel
from app_module.v3_effectiveness_review_scaffold import V3ReviewScaffoldBuilder


def test_scaffold_lists_signal_alert_gate_reviews_without_auto_action() -> None:
    report = V3EffectivenessReadModel(min_sample_size=30).build_report(
        rows=[
            {
                "event_family": "risk_prompt",
                "event_type": "liquidity_gate_excluded",
                "source_type": "negative_evidence",
                "ready_outcome_count": 34,
                "pending_outcome_count": 0,
                "missing_outcome_count": 0,
                "benchmark_coverage_bp": 10000,
                "industry_coverage_bp": 2000,
                "warnings": ("manual_validation_missing",),
            }
        ]
    )

    scaffold = V3ReviewScaffoldBuilder().build(report)
    first = scaffold.items[0]

    assert first.manual_validation_status == "PENDING_MANUAL_VALIDATION"
    assert first.apply_lifecycle_action is False
    assert first.auto_trading is False
    assert first.review_question


def test_scaffold_maps_review_categories() -> None:
    report = V3EffectivenessReadModel(min_sample_size=1).build_report(
        rows=[
            {
                "event_family": "screening_matrix",
                "event_type": "screening_matrix_fail",
                "source_type": "negative_evidence",
                "ready_outcome_count": 5,
                "pending_outcome_count": 0,
                "missing_outcome_count": 0,
                "warnings": (),
            },
            {
                "event_family": "recommendation",
                "event_type": "recommendation_included",
                "source_type": "persisted_recommendation",
                "ready_outcome_count": 5,
                "pending_outcome_count": 0,
                "missing_outcome_count": 0,
                "warnings": (),
            },
        ]
    )

    scaffold = V3ReviewScaffoldBuilder().build(report)
    categories = {item.event_family: item.review_category for item in scaffold.items}
    assert categories["screening_matrix"] == "gate"
    assert categories["recommendation"] == "signal"
    assert scaffold.production_scheduler_allowed is False
