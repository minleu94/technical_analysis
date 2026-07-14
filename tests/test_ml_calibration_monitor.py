from __future__ import annotations

import pytest

from ml_module.calibration_monitor import (
    CalibrationOutcomeObservation,
    MaturedLabelCalibrationMonitor,
)


def _observation(
    prediction_id: str,
    *,
    probability_bp: int,
    actual_downside: int | None,
    maturity_status: str = "ready",
    label_available_date: str = "2026-07-10",
) -> CalibrationOutcomeObservation:
    return CalibrationOutcomeObservation(
        prediction_id=prediction_id,
        model_id="model-1",
        dataset_id="dataset-1",
        decision_date="2026-06-01",
        downside_probability_bp=probability_bp,
        actual_downside=actual_downside,
        maturity_status=maturity_status,
        label_available_date=label_available_date,
    )


def test_calibration_uses_only_matured_labels_available_by_as_of() -> None:
    report = MaturedLabelCalibrationMonitor().evaluate(
        model_id="model-1",
        dataset_id="dataset-1",
        evaluated_as_of="2026-07-13",
        observations=(
            _observation("p1", probability_bp=1000, actual_downside=0),
            _observation("p2", probability_bp=9000, actual_downside=1),
            _observation(
                "pending", probability_bp=10000, actual_downside=None, maturity_status="pending"
            ),
            _observation(
                "future", probability_bp=10000, actual_downside=0, label_available_date="2026-07-14"
            ),
        ),
    )

    assert report.matured_sample_count == 2
    assert report.excluded_immature_count == 2
    assert report.downside_brier_bp == 100
    assert report.status == "passed"
    assert report.auto_retrain_allowed is False
    assert report.auto_promotion_allowed is False
    assert report.production_action_allowed is False


def test_no_matured_labels_returns_typed_review_report() -> None:
    report = MaturedLabelCalibrationMonitor().evaluate(
        model_id="model-1",
        dataset_id="dataset-1",
        evaluated_as_of="2026-07-13",
        observations=(
            _observation("pending", probability_bp=5000, actual_downside=None, maturity_status="pending"),
        ),
    )

    assert report.matured_sample_count == 0
    assert report.downside_brier_bp is None
    assert report.status == "insufficient_matured_labels"
    assert report.blockers == ("no_matured_labels_available",)


def test_duplicate_matured_prediction_identity_is_rejected() -> None:
    row = _observation("same", probability_bp=5000, actual_downside=1)

    with pytest.raises(ValueError, match="prediction_id"):
        MaturedLabelCalibrationMonitor().evaluate(
            model_id="model-1",
            dataset_id="dataset-1",
            evaluated_as_of="2026-07-13",
            observations=(row, row),
        )
