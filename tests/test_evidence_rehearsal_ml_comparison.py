from __future__ import annotations

import pytest

from app_module.evidence_rehearsal_ml_comparison import MLRehearsalComparisonService
from ml_module.available_date_boundary import (
    MLBoundaryFilterResult,
    MLFeatureValue,
    MLLabelValue,
    MLTrainingRow,
)
from ml_module.dataset_manifest import MLDatasetField, MLDatasetManifest
from ml_module.model_prediction_registries import MLShadowPredictionRecord


def _manifest(*, row_count: int) -> MLDatasetManifest:
    return MLDatasetManifest.create(
        dataset_id="shadow-dataset-v1",
        created_at="2026-07-13T11:00:00+00:00",
        decision_date_start="2026-06-01",
        decision_date_end="2026-06-30",
        row_count=row_count,
        features=(MLDatasetField("score_bp", "int", "evidence", True),),
        labels=(MLDatasetField("future_return_bp", "int", "outcomes", True),),
        source_versions={"evidence": "v1", "outcomes": "v1"},
        content_hash="sha256:dataset-content",
    )


def _accepted_row(row_id: str, *, feature_value: int | None = 5000) -> MLTrainingRow:
    return MLTrainingRow(
        row_id=row_id,
        decision_date="2026-06-01",
        features=(MLFeatureValue("score_bp", feature_value, "2026-06-01"),),
        label=MLLabelValue("future_return_bp", 150, "2026-06-30", "ready"),
    )


def test_insufficient_samples_defer_instead_of_promote() -> None:
    service = MLRehearsalComparisonService()
    boundary_report = MLBoundaryFilterResult((), ("future",), (("future", ("future_feature:score_bp",)),))

    result = service.compare(_manifest(row_count=1), boundary_report, ())

    assert result.status == "insufficient_sample"
    assert result.shadow_only is True
    assert result.production_action_allowed is False


def test_comparison_reports_exclusions_and_missingness_without_imputation() -> None:
    service = MLRehearsalComparisonService()
    boundary_report = MLBoundaryFilterResult(
        (_accepted_row("accepted", feature_value=None),),
        ("future", "immature"),
        (
            ("future", ("future_feature:score_bp",)),
            ("immature", ("label_not_mature", "label_unavailable_at_training_cutoff")),
        ),
    )

    result = service.compare(_manifest(row_count=3), boundary_report, ())

    assert result.accepted_rows == 1
    assert result.excluded_rows == 2
    assert result.future_blocked_rows == 1
    assert result.immature_label_rows == 1
    assert result.missing_feature_rows == 1
    assert boundary_report.accepted_rows[0].features[0].value is None


def test_comparison_rejects_prediction_from_another_frozen_dataset() -> None:
    service = MLRehearsalComparisonService()
    prediction = MLShadowPredictionRecord(
        prediction_id="prediction-1",
        model_id="shadow-model-v1",
        dataset_id="another-dataset",
        symbol="2330",
        decision_date="2026-06-01",
        available_date="2026-06-01",
        return_prediction_bp=150.0,
        ranking_score=0.5,
        downside_probability=0.2,
    )

    with pytest.raises(ValueError, match="dataset_id"):
        service.compare(_manifest(row_count=1), MLBoundaryFilterResult((_accepted_row("accepted"),), (), ()), (prediction,))
