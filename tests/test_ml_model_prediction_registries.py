from pathlib import Path

import pytest

from ml_module.model_prediction_registries import (
    MLModelRecord,
    MLModelRegistry,
    MLShadowPredictionRecord,
    MLShadowPredictionRegistry,
    initialize_shadow_registry,
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
    db_path = tmp_path / "ml.sqlite"
    initialize_shadow_registry(db_path, data_root=tmp_path / "formal-data")
    registry = MLModelRegistry(db_path, data_root=tmp_path / "formal-data")
    registry.append(_model())

    loaded = registry.get("m1")
    assert loaded == _model()
    assert loaded.shadow_only is True
    assert loaded.lifecycle_status == "shadow_candidate"
    assert loaded.production_eligible is False
    assert registry.append(_model()) == "idempotent"


def test_prediction_registry_preserves_causal_dates(tmp_path: Path) -> None:
    db_path = tmp_path / "ml.sqlite"
    initialize_shadow_registry(db_path, data_root=tmp_path / "formal-data")
    registry = MLShadowPredictionRegistry(db_path, data_root=tmp_path / "formal-data")
    record = MLShadowPredictionRecord(
        prediction_id="p1",
        model_id="m1",
        dataset_id="d1",
        symbol="2330",
        decision_date="2026-07-12",
        available_date="2026-07-12",
        return_prediction_bp=250,
        ranking_score=6500,
        downside_probability=2000,
        uncertainty_bp=300,
        feature_snapshot_hash="sha256:snapshot",
        source_versions_hash="sha256:sources",
    )
    registry.append(record)

    assert registry.list_for_model("m1") == (record,)
    assert registry.append(record) == "idempotent"


def test_registry_requires_explicit_initialization_and_never_creates_on_read(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "shadow.sqlite"
    registry = MLShadowPredictionRegistry(db_path, data_root=tmp_path / "formal-data")

    assert not db_path.exists()
    with pytest.raises(FileNotFoundError):
        registry.list_for_model("missing")
    assert not db_path.exists()


def test_registry_rejects_data_root_descendant(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DATA_ROOT"):
        MLShadowPredictionRegistry(
            tmp_path / "formal-data" / "sqlite" / "shadow.sqlite",
            data_root=tmp_path / "formal-data",
        )


def test_prediction_v2_schema_uses_integer_bp_and_batch_is_atomic(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "shadow.sqlite"
    initialize_shadow_registry(db_path, data_root=tmp_path / "formal-data")
    registry = MLShadowPredictionRegistry(db_path, data_root=tmp_path / "formal-data")
    valid = MLShadowPredictionRecord(
        prediction_id="p1",
        model_id="m1",
        dataset_id="d1",
        symbol="2330",
        decision_date="2026-07-12",
        available_date="2026-07-12",
        return_prediction_bp=250,
        ranking_score=6500,
        downside_probability=2000,
        uncertainty_bp=300,
        feature_snapshot_hash="sha256:snapshot",
        source_versions_hash="sha256:sources",
    )
    conflict = MLShadowPredictionRecord(**{**valid.__dict__, "return_prediction_bp": 251})

    registry.append(valid)
    with pytest.raises(ValueError, match="conflict"):
        registry.append_batch((MLShadowPredictionRecord(**{**valid.__dict__, "prediction_id": "p2"}), conflict))
    assert tuple(row.prediction_id for row in registry.list_for_model("m1")) == ("p1",)
    with sqlite3.connect(db_path) as conn:
        column_types = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(ml_shadow_predictions_v2)")}
    assert column_types["return_prediction_bp"] == "INTEGER"
    assert column_types["ranking_score_bp"] == "INTEGER"
    assert column_types["downside_probability_bp"] == "INTEGER"
    assert column_types["uncertainty_bp"] == "INTEGER"


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
