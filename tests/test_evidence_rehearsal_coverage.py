from __future__ import annotations

import pytest

from app_module.evidence_rehearsal_coverage import (
    CoverageObservation,
    EvidenceRehearsalCoverageProjector,
)


DECISION_DATE = "2026-07-12"


def _row(**overrides: object) -> CoverageObservation:
    values: dict[str, object] = {
        "row_id": "row-1",
        "source_id": "daily_prices",
        "source_version": "v1",
        "decision_date": DECISION_DATE,
        "available_date": DECISION_DATE,
        "quality": "complete",
        "feature_present": True,
        "label_maturity_date": DECISION_DATE,
    }
    values.update(overrides)
    return CoverageObservation(**values)  # type: ignore[arg-type]


def test_project_counts_complete_and_degraded_cohorts_with_integer_coverage_bp() -> None:
    metrics = EvidenceRehearsalCoverageProjector().project(
        (
            _row(row_id="complete"),
            _row(row_id="degraded", quality="degraded"),
        ),
        decision_date=DECISION_DATE,
    )

    assert len(metrics) == 1
    metric = metrics[0]
    assert metric.source_id == "daily_prices"
    assert metric.total_count == 2
    assert metric.observed_count == 1
    assert metric.degraded_count == 1
    assert metric.missing_count == 0
    assert metric.future_blocked_count == 0
    assert metric.immature_label_count == 0
    assert metric.coverage_bp == 5000


def test_project_counts_missing_feature_or_label_as_missing_cohort() -> None:
    metrics = EvidenceRehearsalCoverageProjector().project(
        (
            _row(row_id="missing-feature", feature_present=False),
            _row(row_id="missing-label", label_maturity_date=None),
        ),
        decision_date=DECISION_DATE,
    )

    assert metrics[0].total_count == 2
    assert metrics[0].missing_count == 2
    assert metrics[0].coverage_bp == 0


def test_project_counts_missing_available_date_as_missing_cohort() -> None:
    metrics = EvidenceRehearsalCoverageProjector().project(
        (_row(available_date=None),),
        decision_date=DECISION_DATE,
    )

    metric = metrics[0]
    assert metric.missing_count == 1
    assert metric.observed_count == 0


def test_project_prioritizes_missingness_when_a_row_has_multiple_failures() -> None:
    metrics = EvidenceRehearsalCoverageProjector().project(
        (
            _row(
                feature_present=False,
                available_date="2026-07-13",
                label_maturity_date="2026-07-13",
                quality="degraded",
            ),
        ),
        decision_date=DECISION_DATE,
    )

    metric = metrics[0]
    assert metric.missing_count == 1
    assert metric.future_blocked_count == 0
    assert metric.immature_label_count == 0
    assert metric.degraded_count == 0
    assert metric.observed_count == 0


def test_project_blocks_future_available_data_without_counting_it_as_observed() -> None:
    metrics = EvidenceRehearsalCoverageProjector().project(
        (_row(available_date="2026-07-13"),),
        decision_date=DECISION_DATE,
    )

    metric = metrics[0]
    assert metric.future_blocked_count == 1
    assert metric.observed_count == 0
    assert metric.coverage_bp == 0


def test_project_rejects_row_with_a_different_decision_date() -> None:
    with pytest.raises(ValueError, match="row.decision_date"):
        EvidenceRehearsalCoverageProjector().project(
            (
                _row(
                    decision_date="2026-07-10",
                    available_date="2026-07-11",
                    label_maturity_date="2026-07-10",
                ),
            ),
            decision_date=DECISION_DATE,
        )


def test_project_counts_unmatured_labels_separately() -> None:
    metrics = EvidenceRehearsalCoverageProjector().project(
        (_row(label_maturity_date="2026-07-13"),),
        decision_date=DECISION_DATE,
    )

    metric = metrics[0]
    assert metric.immature_label_count == 1
    assert metric.observed_count == 0
    assert metric.coverage_bp == 0


def test_project_returns_empty_tuple_for_empty_rows() -> None:
    assert EvidenceRehearsalCoverageProjector().project((), decision_date=DECISION_DATE) == ()


def test_project_orders_sources_deterministically_and_preserves_cohort_invariant() -> None:
    metrics = EvidenceRehearsalCoverageProjector().project(
        (
            _row(row_id="z-complete", source_id="zeta"),
            _row(row_id="a-future", source_id="alpha", available_date="2026-07-13"),
            _row(row_id="a-missing", source_id="alpha", feature_present=False),
            _row(row_id="z-immature", source_id="zeta", label_maturity_date="2026-07-13"),
            _row(row_id="z-degraded", source_id="zeta", quality="degraded"),
        ),
        decision_date=DECISION_DATE,
    )

    assert [metric.source_id for metric in metrics] == ["alpha", "zeta"]
    for metric in metrics:
        assert metric.total_count == (
            metric.observed_count
            + metric.degraded_count
            + metric.missing_count
            + metric.future_blocked_count
            + metric.immature_label_count
        )
        assert metric.future_blocked_count == 0 or metric.observed_count < metric.total_count
