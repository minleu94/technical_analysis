from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest

from ml_module.allocation_v3_readback_bundle import (
    BUNDLE_SCHEMA_VERSION,
    _object_reference,
    _write_content_addressed_object,
    create_readback_bundle,
    load_readback_bundle,
)


def _digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    source_hash = _digest("source")
    contract_hash = _digest("contract")
    dataset_hash = _digest("dataset")
    parent_input_hash = _digest("parent-input")
    parent_store_hash = _digest("parent-store")
    parent_store_file_hash = _digest("parent-store-file")
    market_hash = _digest("market")
    training_manifest_hash = _digest("training-manifest")
    release_identity_hash = _digest("release")
    source_refs = [["source:test", source_hash]]
    payload = {
        "schema_version": "allocation-inference-input-v3",
        "feature_contract": {"contract_version": "test"},
        "feature_contract_hash": contract_hash,
        "parent_input_compressed_hash": parent_input_hash,
        "rows": [
            {
                "row_id": "row:post-freeze-shadow:2026-09-07:TEST",
                "decision_at": "2026-09-07T18:00:00+08:00",
                "symbol": "TEST",
                "dataset_identity_hash": dataset_hash,
                "feature_registry_hash": contract_hash,
                "source_manifest_hashes": source_refs,
                "targets": None,
            }
        ],
    }
    input_path = tmp_path / "frozen.json.gz"
    input_path.write_bytes(
        gzip.compress(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            mtime=0,
        )
    )
    training = {
        "schema_version": "allocation-v3-linear-shadow-training.v1",
        "manifest_hash": training_manifest_hash,
        "v3_input_hash": "placeholder",
        "parent_store_manifest_hash": parent_store_hash,
        "parent_store_manifest_file_hash": parent_store_file_hash,
        "market_database_file_hash": market_hash,
        "source_manifest_hashes": source_refs,
        "feature_order": ["test.feature"],
        "feature_packs": [["test", ["test.feature"]]],
        "fit_fold_id": "fold-001",
        "meta_fold_id": "fold-002",
        "calibration_fold_ids": ["fold-003", "fold-004"],
        "profile": "v3_h5_linear_shadow",
        "horizon": 5,
        "algorithm": "ridge_logistic",
        "v3_contract_hash": contract_hash,
        "readback_inference_mode": "post_freeze_research_shadow",
        "inference_readback": {
            "mode": "post_freeze_research_shadow",
            "decision_at": "2026-09-07T18:00:00+08:00",
            "status": "planned_before_publish",
        },
        "meta_probability_input": "calibrated",
        "rank_contract": "allocation-rank-v2",
    }
    # The training input hash is bound to the exact compressed bytes.
    input_hash = "sha256:" + hashlib.sha256(input_path.read_bytes()).hexdigest()
    training["v3_input_hash"] = input_hash
    training_bytes = (json.dumps(training, sort_keys=True) + "\n").encode("utf-8")
    release = {
        "schema_version": "allocation-ml-inference-release.v1",
        "release_id": "release-test",
        "release_identity_hash": release_identity_hash,
        "model_id": "model-test",
        "dataset_id": "dataset-test",
        "dataset_identity_hash": dataset_hash,
        "feature_registry_hash": contract_hash,
        "source_manifest_hashes": source_refs,
        "training_manifest_hash": training_manifest_hash,
    }
    release_root = tmp_path / "release"
    release_root.mkdir()
    (release_root / "release_manifest.json").write_text(
        json.dumps(release, sort_keys=True), encoding="utf-8"
    )
    (release_root / "training_manifest.json").write_bytes(training_bytes)
    output_root = tmp_path / "bundle"
    return input_path, release_root, output_root, input_hash


def test_bundle_is_content_addressed_idempotent_and_survives_source_removal(
    tmp_path: Path,
) -> None:
    input_path, release_root, output_root, input_hash = _fixture(tmp_path)
    first = create_readback_bundle(
        v3_input_path=input_path,
        release_root=release_root,
        output_root=output_root,
    )
    assert first["status"] == "readback_bundle_created"
    assert first["input_hash"] == input_hash
    assert first["new_bytes_written"] > 0
    manifest_path = Path(first["bundle_manifest"])
    manifest_bytes = manifest_path.read_bytes()
    object_paths = sorted(
        path for path in output_root.rglob("*") if path.is_file()
    )
    output_bytes = sum(path.stat().st_size for path in object_paths)

    second = create_readback_bundle(
        v3_input_path=input_path,
        release_root=release_root,
        output_root=output_root,
    )
    assert second["status"] == "readback_bundle_reused"
    assert second["bundle_id"] == first["bundle_id"]
    assert second["new_bytes_written"] == 0
    assert manifest_path.read_bytes() == manifest_bytes
    assert sum(path.stat().st_size for path in output_root.rglob("*") if path.is_file()) == output_bytes

    input_path.unlink()
    bundle = load_readback_bundle(manifest_path)
    assert bundle.input_path.is_file()
    assert bundle.input_hash == input_hash
    assert bundle.manifest["schema_version"] == BUNDLE_SCHEMA_VERSION
    # Bundle metadata must not retain a dependency on the deleted TEMP path.
    assert str(input_path) not in manifest_path.read_text(encoding="utf-8")


def test_interrupted_object_publish_leaves_no_final_partial_and_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "bundle"
    raw = b"atomic-object"
    reference = _object_reference(output_root, raw, extension="json")
    final_path = output_root / reference["path"]

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _write_content_addressed_object(output_root, raw, reference)
    assert not final_path.exists()
    assert list(final_path.parent.glob("*.partial")) == []

    monkeypatch.undo()
    assert _write_content_addressed_object(output_root, raw, reference) is True
    assert final_path.read_bytes() == raw
    assert _write_content_addressed_object(output_root, raw, reference) is False


def test_concurrent_same_content_publish_has_one_immutable_result(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "bundle"
    raw = b"same-content"
    reference = _object_reference(output_root, raw, extension="json")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: _write_content_addressed_object(
                    output_root,
                    raw,
                    reference,
                ),
                (0, 1),
            )
        )
    assert sorted(results) == [False, True]
    assert (output_root / reference["path"]).read_bytes() == raw
