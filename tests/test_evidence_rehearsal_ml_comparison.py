from __future__ import annotations

import pytest

from app_module.evidence_rehearsal_ml_comparison import (
    MLRehearsalComparisonService,
    MLShadowDiagnosticsInput,
)
from ml_module.available_date_boundary import (
    MLAvailableDateBoundary,
    MLBoundaryFilterResult,
    MLFeatureValue,
    MLLabelValue,
    MLTrainingRow,
)
from ml_module.dataset_manifest import MLDatasetField, MLDatasetManifest
from ml_module.drift_champion_comparison import (
    MLChampionComparisonResult,
    MLFeatureDriftResult,
)
from ml_module.model_prediction_registries import MLShadowPredictionRecord
from ml_module.probability_calibration import FittedShadowProbabilityCalibrator
from ml_module.purged_walk_forward import PurgedWalkForwardFold


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


def test_actual_boundary_filter_excludes_future_features_and_unmatured_labels() -> None:
    rows = (
        _accepted_row("accepted"),
        MLTrainingRow(
            row_id="future-feature",
            decision_date="2026-06-01",
            features=(MLFeatureValue("score_bp", 5000, "2026-06-02"),),
            label=MLLabelValue("future_return_bp", 150, "2026-06-30", "ready"),
        ),
        MLTrainingRow(
            row_id="immature-label",
            decision_date="2026-06-01",
            features=(MLFeatureValue("score_bp", 5000, "2026-06-01"),),
            label=MLLabelValue("future_return_bp", None, "2026-07-10", "pending"),
        ),
    )
    boundary_report = MLAvailableDateBoundary().filter(rows, training_as_of="2026-07-01")

    result = MLRehearsalComparisonService().compare(_manifest(row_count=3), boundary_report, ())

    assert result.status == "insufficient_sample"
    assert result.accepted_rows == 1
    assert result.future_blocked_rows == 1
    assert result.immature_label_rows == 1
    assert result.mature_label_rows == 1
    assert result.boundary_issues == ()


def test_inconsistent_accepted_boundary_row_fails_closed() -> None:
    inconsistent_row = MLTrainingRow(
        row_id="inconsistent",
        decision_date="2026-06-01",
        features=(MLFeatureValue("score_bp", 5000, "2026-06-02"),),
        label=MLLabelValue("future_return_bp", None, "2026-07-14", "pending"),
    )
    boundary_report = MLBoundaryFilterResult((inconsistent_row,), (), ())

    result = MLRehearsalComparisonService().compare(_manifest(row_count=1), boundary_report, ())

    assert result.status == "boundary_inconsistent"
    assert result.shadow_only is True
    assert result.production_action_allowed is False
    assert result.future_blocked_rows == 1
    assert result.immature_label_rows == 1
    assert result.mature_label_rows == 0
    assert "accepted_future_feature:inconsistent:score_bp" in result.boundary_issues
    assert "accepted_label_not_mature:inconsistent" in result.boundary_issues
    assert "accepted_future_label:inconsistent" in result.boundary_issues


def test_manifest_row_conservation_and_diagnostic_mapping_fail_closed() -> None:
    boundary_report = MLBoundaryFilterResult(
        (_accepted_row("duplicate"),),
        ("duplicate", "rejected"),
        (("unexpected", ("future_feature:score_bp",)),),
    )

    result = MLRehearsalComparisonService().compare(_manifest(row_count=4), boundary_report, ())

    assert result.status == "boundary_inconsistent"
    assert "manifest_row_count_mismatch" in result.boundary_issues
    assert "row_id_not_unique:duplicate" in result.boundary_issues
    assert "diagnostic_rejected_row_mismatch" in result.boundary_issues


def test_production_action_prediction_fails_closed() -> None:
    class UnsafePrediction:
        dataset_id = "shadow-dataset-v1"
        shadow_only = True
        production_action_allowed = True

    with pytest.raises(ValueError, match="shadow-only"):
        MLRehearsalComparisonService().compare(
            _manifest(row_count=1),
            MLBoundaryFilterResult((_accepted_row("accepted"),), (), ()),
            (UnsafePrediction(),),
        )


def test_existing_ml_diagnostics_are_projected_without_recalculation() -> None:
    diagnostics = MLShadowDiagnosticsInput(
        purged_folds=(
            PurgedWalkForwardFold(
                fold_id="fold-001",
                train_rows=(),
                test_rows=(),
                test_start="2026-06-01",
                test_end="2026-06-05",
                purge_days=5,
                embargo_days=2,
            ),
        ),
        calibration=FittedShadowProbabilityCalibrator(
            calibration_id="cal-1",
            model_id="shadow-model-v1",
            estimator=object(),
            sample_count=20,
            fold_count=2,
        ),
        drift_results=(MLFeatureDriftResult("score_bp", 0.26, "major_drift", 20, 20),),
        champion_comparison=MLChampionComparisonResult(
            sample_count=20,
            k=5,
            champion_precision_at_k_bp=6000,
            challenger_precision_at_k_bp=8000,
            challenger_return_mae_bp=120,
            challenger_downside_brier_bp=500,
            review_status="challenger_directionally_better",
        ),
    )

    result = MLRehearsalComparisonService().compare(
        _manifest(row_count=1),
        MLBoundaryFilterResult((_accepted_row("accepted"),), (), ()),
        (),
        diagnostics=diagnostics,
    )

    assert result.status == "insufficient_sample"
    assert result.purged_fold_ids == ("fold-001",)
    assert result.calibration_status == "provided"
    assert result.calibration_sample_count == 20
    assert result.drift_statuses == (("score_bp", "major_drift"),)
    assert result.rule_vs_challenger_status == "challenger_directionally_better"
    assert result.rule_vs_challenger_sample_count == 20


def test_accepted_label_after_training_cutoff_fails_closed() -> None:
    row = MLTrainingRow(
        row_id="future-label",
        decision_date="2026-06-01",
        features=(MLFeatureValue("score_bp", 5000, "2026-06-01"),),
        label=MLLabelValue("future_return_bp", 150, "2026-07-02", "ready"),
    )

    result = MLRehearsalComparisonService().compare(
        _manifest(row_count=1),
        MLBoundaryFilterResult((row,), (), ()),
        (),
        diagnostics=MLShadowDiagnosticsInput(training_as_of="2026-07-01"),
    )

    assert result.status == "boundary_inconsistent"
    assert result.mature_label_rows == 0
    assert "accepted_future_label:future-label" in result.boundary_issues


def test_ready_status_requires_explicit_training_cutoff() -> None:
    boundary_report = MLBoundaryFilterResult(
        tuple(_accepted_row(f"accepted-{index}") for index in range(20)), (), ()
    )

    result = MLRehearsalComparisonService().compare(
        _manifest(row_count=20), boundary_report, ()
    )

    assert result.status == "training_context_required"
