from ml_module.available_date_boundary import (
    MLAvailableDateBoundary,
    MLFeatureValue,
    MLLabelValue,
    MLTrainingRow,
)


def _row() -> MLTrainingRow:
    return MLTrainingRow(
        row_id="2330:2026-06-01",
        decision_date="2026-06-01",
        features=(MLFeatureValue("score_bp", 6500, "2026-06-01"),),
        label=MLLabelValue("future_20d_excess_bp", 300, "2026-06-30", "ready"),
    )


def test_mature_row_is_accepted_at_training_cutoff() -> None:
    result = MLAvailableDateBoundary().validate(_row(), training_as_of="2026-07-01")

    assert result.accepted is True
    assert result.diagnostics == ()


def test_future_feature_is_rejected() -> None:
    row = MLTrainingRow(
        row_id="r",
        decision_date="2026-06-01",
        features=(MLFeatureValue("score_bp", 6500, "2026-06-02"),),
        label=MLLabelValue("label", 1, "2026-06-30", "ready"),
    )

    result = MLAvailableDateBoundary().validate(row, training_as_of="2026-07-01")
    assert result.accepted is False
    assert "future_feature:score_bp" in result.diagnostics


def test_unmatured_or_future_label_is_rejected() -> None:
    pending = MLTrainingRow(
        row_id="r",
        decision_date="2026-06-01",
        features=(MLFeatureValue("score", 1, "2026-06-01"),),
        label=MLLabelValue("label", None, "2026-07-10", "pending"),
    )

    result = MLAvailableDateBoundary().validate(pending, training_as_of="2026-07-01")
    assert result.accepted is False
    assert "label_not_mature" in result.diagnostics
    assert "label_unavailable_at_training_cutoff" in result.diagnostics


def test_future_rows_do_not_change_prior_row_validation() -> None:
    boundary = MLAvailableDateBoundary()
    first = boundary.filter((_row(),), training_as_of="2026-07-01")
    future = MLTrainingRow(
        row_id="future",
        decision_date="2026-07-10",
        features=(MLFeatureValue("score", 1, "2026-07-10"),),
        label=MLLabelValue("label", 1, "2026-08-01", "ready"),
    )
    second = boundary.filter((_row(), future), training_as_of="2026-07-01")

    assert first.accepted_rows == second.accepted_rows
    assert second.rejected_row_ids == ("future",)
