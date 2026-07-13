from pathlib import Path

import pytest

from ml_module.model_prediction_registries import (
    MLModelRecord,
    MLModelRegistry,
    MLShadowPredictionRecord,
    MLShadowPredictionRegistry,
)


def _model() -> MLModelRecord:
    return MLModelRecord(
        model_id="m1",
        dataset_id="d1",
        created_at="2026-07-12T12:00:00+00:00",
        model_family="hist_gradient_boosting",
        feature_names=("score_bp", "regime"),
        artifact_path="artifacts/m1.joblib",
        artifact_hash="sha256:abc",
        calibration_id="cal-1",
    )


def test_model_registry_is_append_only_and_shadow_only(tmp_path: Path) -> None:
    registry = MLModelRegistry(tmp_path / "ml.sqlite")
    registry.append(_model())

    loaded = registry.get("m1")
    assert loaded == _model()
    assert loaded.shadow_only is True
    assert loaded.lifecycle_status == "shadow_candidate"
    assert loaded.production_eligible is False
    with pytest.raises(ValueError, match="already exists"):
        registry.append(_model())


def test_prediction_registry_preserves_causal_dates(tmp_path: Path) -> None:
    registry = MLShadowPredictionRegistry(tmp_path / "ml.sqlite")
    record = MLShadowPredictionRecord(
        prediction_id="p1",
        model_id="m1",
        dataset_id="d1",
        symbol="2330",
        decision_date="2026-07-12",
        available_date="2026-07-12",
        return_prediction_bp=250.5,
        ranking_score=250.5,
        downside_probability=0.2,
    )
    registry.append(record)

    assert registry.list_for_model("m1") == (record,)
    with pytest.raises(ValueError, match="already exists"):
        registry.append(record)


def test_future_available_prediction_is_rejected() -> None:
    with pytest.raises(ValueError, match="available_date"):
        MLShadowPredictionRecord(
            prediction_id="p",
            model_id="m",
            dataset_id="d",
            symbol="2330",
            decision_date="2026-07-12",
            available_date="2026-07-13",
            return_prediction_bp=1.0,
            ranking_score=1.0,
            downside_probability=0.2,
        )


def test_probability_outside_unit_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="downside_probability"):
        MLShadowPredictionRecord(
            prediction_id="p",
            model_id="m",
            dataset_id="d",
            symbol="2330",
            decision_date="2026-07-12",
            available_date="2026-07-12",
            return_prediction_bp=1.0,
            ranking_score=1.0,
            downside_probability=1.1,
        )
