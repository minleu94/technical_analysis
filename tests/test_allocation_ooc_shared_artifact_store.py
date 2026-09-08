from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ml_module.allocation_ooc_shared_artifact_store import (
    OOCSharedArtifactStore,
    semantic_key_hash,
)


def _digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _semantic_key() -> dict[str, object]:
    digest = _digest("shared-ooc-key")
    return {
        "schema_version": "allocation-ooc-artifact-key.v1",
        "namespace": "base_oof",
        "artifact_kind": "base_oof_expert",
        "artifact_scope": {
            "fold_id": "fold-001",
            "pack_id": "pack-a",
            "horizon_trading_days": 5,
            "algorithm": "ridge_logistic",
        },
        "store_lineage": {
            "schema_version": "allocation-ooc-store.v1",
            "store_manifest_hash": digest,
            "store_manifest_file_hash": _digest("store-file"),
            "dataset_identity_hash": _digest("dataset"),
            "source_manifest_hashes": [["direct", _digest("direct")]],
        },
        "feature_contract": {
            "schema_version": "allocation-ooc-feature-contract.v1",
            "registry_hash": _digest("features"),
            "feature_ids": ["feature-a", "feature-b"],
            "feature_scales": [100, 100],
            "feature_packs": [{"pack_id": "pack-a", "feature_ids": ["feature-a"]}],
        },
        "label_target_contract": {
            "schema_version": "allocation-ooc-label-target-contract.v1",
            "contract_hash": _digest("labels"),
            "label_fields": ["downside"],
            "target_fields": ["target"],
        },
        "split_contract": {
            "fold_id": "fold-001",
            "train_fold_ids": ["fold-000"],
            "test_fold_ids": ["fold-001"],
            "calibration_fold_ids": ["fold-000"],
            "purge_trading_days": 60,
            "embargo_trading_days": 5,
        },
        "maturity_contract": {
            "cutoff_exclusive": "2024-03-01",
            "mature_prior_oof_only": True,
        },
        "model_contract": {
            "selected_horizons": [5],
            "requested_algorithms": ["ridge_logistic"],
            "ridge_alpha_bp": 100,
            "logistic_iterations": 2,
            "implementation": "linear-v1",
        },
        "training_contract": {
            "training_profile": "minimal_linear_shadow",
            "complexity_policy": {
                "algorithm_count": 1,
                "horizon_count": 1,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
            "batch_size": 31,
            "workers": 1,
        },
        "calibration_contract": {
            "method": "cross_fitted_binned_calibration",
            "namespace": "calibrator",
            "withheld_oof_fold_ids": ["fold-000"],
            "fit_calibration_row_identity_separation": "prior_oof_only",
            "diagnostic_only": True,
        },
        "implementation_contract": {
            "training_schema_version": "allocation-ooc-training.v5",
            "expert_schema_version": "allocation-ooc-expert.v5",
            "meta_schema_version": "allocation-ooc-meta.v3",
            "oof_dtype": "<i4",
            "key_builder_version": "allocation-ooc-semantic-key-builder.v1",
        },
        "time_range": {"start": "2024-01-01", "end": "2024-03-01"},
        "lane": "research_shadow",
    }


def _artifact_manifest(payloads: dict[str, bytes]) -> dict[str, object]:
    records = []
    for relative, payload in sorted(payloads.items()):
        records.append(
            {
                "path": relative,
                "byte_count": len(payload),
                "file_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "schema_version": "allocation-ooc-expert.v5",
        "artifact_kind": "base_oof_expert",
        "fold_id": "fold-001",
        "pack_id": "pack-a",
        "horizon_trading_days": 5,
        "algorithm": "ridge_logistic",
        "expert_id": "pack-a|h5|ridge_logistic",
        "test_row_count": 2,
        "oof_shape": [2, 10],
        "artifact_storage": "shared_immutable",
        "artifacts": records,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }


def _publish_fixture(
    root: Path,
    *,
    payloads: dict[str, bytes] | None = None,
) -> tuple[OOCSharedArtifactStore, dict[str, object], dict[str, object]]:
    payloads = payloads or {
        "oof.i32": b"\x01\x00\x00\x00" * 20,
        "head.joblib": b"small-linear-head",
    }
    source = root / "source"
    source.mkdir(parents=True)
    for relative, payload in payloads.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    key = _semantic_key()
    manifest = _artifact_manifest(payloads)
    manifest["shared_artifact_key_hash"] = semantic_key_hash(key)
    store = OOCSharedArtifactStore(root / "registry")
    result = store.publish(
        semantic_key=key,
        artifact_manifest=manifest,
        source_directory=source,
    )
    return store, key, result


def test_shared_ooc_artifact_reuses_and_survives_registry_move(
    tmp_path: Path,
) -> None:
    store, key, first = _publish_fixture(tmp_path / "first")

    assert first["status"] == "immutable_ooc_artifact_created"
    assert int(first["new_bytes_written"]) > 0
    resolved = store.resolve(key)
    assert resolved is not None
    assert resolved.semantic_key_hash == semantic_key_hash(key)

    second = store.publish(
        semantic_key=key,
        artifact_manifest=resolved.artifact_manifest,
        source_directory=tmp_path / "first" / "source",
    )
    assert second["status"] == "immutable_ooc_artifact_reused"
    assert second["new_bytes_written"] == 0

    moved_root = tmp_path / "moved-registry"
    shutil.copytree(store.root, moved_root)
    moved = OOCSharedArtifactStore(moved_root)
    moved_resolution = moved.resolve(key)
    assert moved_resolution is not None
    assert all(
        path.is_relative_to(moved_root)
        for path in moved_resolution.file_paths.values()
    )


def test_ooc_artifact_dependency_change_is_a_miss_and_tamper_fails(
    tmp_path: Path,
) -> None:
    store, key, _first = _publish_fixture(tmp_path / "source-store")

    changed = deepcopy(key)
    assert isinstance(changed["model_contract"], dict)
    changed["model_contract"]["ridge_alpha_bp"] = 101
    assert store.resolve(changed) is None

    copied_root = tmp_path / "tampered-registry"
    shutil.copytree(store.root, copied_root)
    tampered_store = OOCSharedArtifactStore(copied_root)
    resolution = tampered_store.resolve(key)
    assert resolution is not None
    payload_path = next(iter(resolution.file_paths.values()))
    payload_path.write_bytes(b"X" * payload_path.stat().st_size)
    with pytest.raises(ValueError, match="bytes/hash mismatch|changed"):
        tampered_store.resolve(key)


@pytest.mark.parametrize(
    ("field_path", "replacement"),
    (
        (("artifact_scope", "fold_id"), "fold-002"),
        (("artifact_scope", "pack_id"), "pack-b"),
        (("lane",), "formal"),
        (("namespace",), "meta_oof"),
    ),
)
def test_ooc_semantic_key_does_not_cross_fold_pack_lane_or_namespace(
    tmp_path: Path,
    field_path: tuple[str, ...],
    replacement: str,
) -> None:
    store, key, _first = _publish_fixture(tmp_path / "source-store")
    changed = deepcopy(key)
    cursor: dict[str, object] = changed
    for field in field_path[:-1]:
        nested = cursor[field]
        assert isinstance(nested, dict)
        cursor = nested
    cursor[field_path[-1]] = replacement
    if field_path == ("namespace",):
        with pytest.raises(ValueError, match="kind and namespace"):
            store.resolve(changed)
    else:
        assert store.resolve(changed) is None


def test_same_semantic_key_cannot_bind_changed_manifest(tmp_path: Path) -> None:
    store, key, _first = _publish_fixture(tmp_path / "source-store")
    source = tmp_path / "changed-source"
    source.mkdir()
    payloads = {
        "oof.i32": b"\x01\x00\x00\x00" * 20,
        "head.joblib": b"different-head",
    }
    for relative, payload in payloads.items():
        (source / relative).write_bytes(payload)
    with pytest.raises(ValueError, match="already bound"):
        store.publish(
            semantic_key=key,
            artifact_manifest=_artifact_manifest(payloads),
            source_directory=source,
        )
