from __future__ import annotations

import json
from pathlib import Path

from ml_module.model_lifecycle_registry import (
    ModelLifecycleEvent,
    ModelLifecycleRegistry,
    initialize_model_lifecycle_registry,
)
from ml_module.model_prediction_registries import initialize_shadow_registry
from scripts.inspect_ml_shadow_operations import main


def test_inspect_is_read_only_and_reports_lifecycle(capsys, tmp_path: Path) -> None:
    prediction_db = tmp_path / "shadow" / "predictions.sqlite"
    lifecycle_db = tmp_path / "shadow" / "lifecycle.sqlite"
    initialize_shadow_registry(prediction_db, data_root=tmp_path / "formal-data")
    initialize_model_lifecycle_registry(lifecycle_db, data_root=tmp_path / "formal-data")
    lifecycle = ModelLifecycleRegistry(lifecycle_db, data_root=tmp_path / "formal-data")
    lifecycle.append(
        ModelLifecycleEvent(
            event_id="activate",
            model_id="model-1",
            event_type="activated_for_shadow",
            created_at="2026-07-13T12:00:00+00:00",
            reason="fixture",
        )
    )
    before = lifecycle_db.stat().st_mtime_ns

    assert main([
        "--prediction-registry", str(prediction_db),
        "--lifecycle-registry", str(lifecycle_db),
        "--model-id", "model-1",
        "--data-root", str(tmp_path / "formal-data"),
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["lifecycle_status"] == "activated_for_shadow"
    assert payload["prediction_count"] == 0
    assert lifecycle_db.stat().st_mtime_ns == before


def test_inspect_missing_registry_does_not_create_files(tmp_path: Path) -> None:
    prediction_db = tmp_path / "missing" / "predictions.sqlite"
    lifecycle_db = tmp_path / "missing" / "lifecycle.sqlite"

    assert main([
        "--prediction-registry", str(prediction_db),
        "--lifecycle-registry", str(lifecycle_db),
        "--model-id", "model-1",
        "--data-root", str(tmp_path / "formal-data"),
    ]) == 1
    assert not prediction_db.exists()
    assert not lifecycle_db.exists()
