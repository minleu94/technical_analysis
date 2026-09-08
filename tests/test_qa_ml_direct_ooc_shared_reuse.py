from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.qa_ml_direct_ooc_shared_reuse import (
    EvidenceError,
    _sha256_json,
    _validate_ooc_artifact,
    snapshot_directory,
)
from tests.test_allocation_ooc_shared_artifact_store import _publish_fixture


def test_snapshot_is_stream_hashed_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "ooc-run"
    source.mkdir()
    (source / "artifact.bin").write_bytes(b"bounded-ooc-artifact")
    snapshot_path = tmp_path / "qa" / "before.json"

    first = snapshot_directory(root=source, output_path=snapshot_path)
    second = snapshot_directory(root=source, output_path=snapshot_path)

    assert first["snapshot_hash"] == second["snapshot_hash"]
    assert first["file_sha256"] == second["file_sha256"]
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["files"]["artifact.bin"]["bytes"] == len(
        b"bounded-ooc-artifact"
    )


def test_snapshot_output_cannot_overlap_read_only_source(tmp_path: Path) -> None:
    source = tmp_path / "ooc-run"
    source.mkdir()
    (source / "artifact.bin").write_bytes(b"source")

    with pytest.raises(EvidenceError, match="overlaps read-only source"):
        snapshot_directory(
            root=source,
            output_path=source / "qa" / "snapshot.json",
        )


def test_qa_validates_shared_ooc_artifact_without_local_payload_copy(
    tmp_path: Path,
) -> None:
    store, _key, publication = _publish_fixture(tmp_path / "fixture")
    resolution = store.resolve_reference(publication["reference"])
    artifact = dict(resolution.artifact_manifest)
    artifact["artifact_path"] = "artifacts/base"
    artifact["shared_artifact_key_hash"] = resolution.semantic_key_hash
    artifact["shared_artifact_reference"] = dict(resolution.reference)
    artifact_body = dict(artifact)
    artifact_body.pop("artifact_path")
    artifact["manifest_hash"] = _sha256_json(artifact_body)

    run_directory = tmp_path / "run" / "runs" / "bounded"
    (run_directory / "artifacts" / "base").mkdir(parents=True)
    summary = _validate_ooc_artifact(
        artifact=artifact,
        run_directory=run_directory,
        field_name="ooc.base_experts.artifacts",
        shared_artifact_store=store,
    )

    assert summary["artifact_storage"] == "shared_immutable"
    assert summary["shared_artifact_key_hash"] == resolution.semantic_key_hash
    assert set(summary["payload_hashes"]) == set(resolution.file_paths)
    assert not list((run_directory / "artifacts" / "base").iterdir())
