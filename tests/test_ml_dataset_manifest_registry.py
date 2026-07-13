from pathlib import Path

import pytest

from ml_module.dataset_manifest import (
    MLDatasetField,
    MLDatasetManifest,
    MLDatasetManifestRegistry,
)


def _manifest() -> MLDatasetManifest:
    return MLDatasetManifest.create(
        dataset_id="gate7-20260712-v1",
        created_at="2026-07-12T12:00:00+00:00",
        decision_date_start="2025-01-01",
        decision_date_end="2026-06-30",
        row_count=1000,
        features=(MLDatasetField("score_bp", "int", "evidence.score", True),),
        labels=(MLDatasetField("future_20d_excess_bp", "int", "forward_outcome", True),),
        source_versions={"evidence": "v3", "prices": "20260712"},
        content_hash="sha256:data-content",
    )


def test_manifest_is_frozen_shadow_only_and_has_deterministic_hash() -> None:
    first = _manifest()
    second = _manifest()

    assert first.manifest_hash == second.manifest_hash
    assert first.frozen is True
    assert first.shadow_only is True
    assert first.production_eligible is False


def test_registry_is_append_only(tmp_path: Path) -> None:
    registry = MLDatasetManifestRegistry(tmp_path / "ml.sqlite")
    registry.append(_manifest())

    assert registry.get("gate7-20260712-v1") == _manifest()
    with pytest.raises(ValueError, match="already exists"):
        registry.append(_manifest())


def test_manifest_requires_available_date_for_every_field() -> None:
    with pytest.raises(ValueError, match="available-date"):
        MLDatasetManifest.create(
            dataset_id="bad",
            created_at="2026-07-12T12:00:00+00:00",
            decision_date_start="2025-01-01",
            decision_date_end="2026-06-30",
            row_count=1,
            features=(MLDatasetField("score", "int", "source", False),),
            labels=(MLDatasetField("label", "int", "source", True),),
            source_versions={"source": "v1"},
            content_hash="sha256:x",
        )


def test_manifest_rejects_empty_or_zero_row_dataset() -> None:
    with pytest.raises(ValueError, match="row_count"):
        MLDatasetManifest.create(
            dataset_id="empty",
            created_at="2026-07-12T12:00:00+00:00",
            decision_date_start="2025-01-01",
            decision_date_end="2026-06-30",
            row_count=0,
            features=(MLDatasetField("score", "int", "source", True),),
            labels=(MLDatasetField("label", "int", "source", True),),
            source_versions={"source": "v1"},
            content_hash="sha256:x",
        )
