from pathlib import Path

import pytest

from ml_module.dataset_manifest import (
    MLDatasetField,
    MLDatasetManifest,
    MLDatasetManifestRegistry,
    MLDatasetManifestV2,
)
from tests.test_ml_dataset_manifest_v2 import _manifest as _manifest_v2


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


def test_registry_round_trips_v2_and_rejects_cross_version_dataset_id_collision(tmp_path: Path) -> None:
    registry = MLDatasetManifestRegistry(tmp_path / "ml-v2.sqlite")
    manifest = _manifest_v2(dataset_id="shared-id")
    registry.append(manifest)

    assert registry.get("shared-id") == manifest
    with pytest.raises(ValueError, match="already exists"):
        registry.append(_manifest().create(
            dataset_id="shared-id", created_at=_manifest().created_at,
            decision_date_start=_manifest().decision_date_start,
            decision_date_end=_manifest().decision_date_end, row_count=1,
            features=_manifest().features, labels=_manifest().labels,
            source_versions=_manifest().source_versions, content_hash="sha256:collision",
        ))


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
