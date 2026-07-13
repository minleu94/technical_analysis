from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable

import joblib

from ml_module.model_artifact_loader import (
    ArtifactCompatibilityExpectation,
    SafeShadowModelArtifactLoader,
)
from ml_module.model_artifact_manifest import ModelArtifactManifest


_SCHEMA = (("score_bp", "int", "bp"),)


@dataclass(frozen=True)
class FixtureShadowBundle:
    model_id: str = "model-1"
    dataset_id: str = "dataset-1"
    model_family: str = "fixture_family"
    shadow_only: bool = True
    production_eligible: bool = False
    production_action_allowed: bool = False


def _sha_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _expectation(**overrides: object) -> ArtifactCompatibilityExpectation:
    values: dict[str, object] = {
        "expected_model_family": "fixture_family",
        "expected_feature_registry_hash": _sha_bytes(b"features"),
        "expected_label_registry_hash": _sha_bytes(b"labels"),
        "expected_feature_schema": _SCHEMA,
        "installed_library_versions": {"python": "3.11.8"},
    }
    values.update(overrides)
    return ArtifactCompatibilityExpectation(**values)  # type: ignore[arg-type]


def _write_fixture(
    root: Path,
    *,
    bundle: FixtureShadowBundle | None = None,
) -> ModelArtifactManifest:
    root.mkdir(parents=True)
    artifact_path = root / "model-1.joblib"
    joblib.dump(bundle or FixtureShadowBundle(), artifact_path)
    manifest = ModelArtifactManifest.create(
        model_id="model-1",
        dataset_id="dataset-1",
        created_run_id="run-1",
        created_at="2026-07-13T12:00:00+00:00",
        model_family="fixture_family",
        feature_registry_hash=_sha_bytes(b"features"),
        label_registry_hash=_sha_bytes(b"labels"),
        feature_schema=_SCHEMA,
        training_as_of="2024-12-31",
        hyperparameters_hash=_sha_bytes(b"params"),
        library_versions={"python": "3.11.9"},
        serialization_format="joblib",
        artifact_filename=artifact_path.name,
        artifact_hash=_sha_bytes(artifact_path.read_bytes()),
    )
    (root / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), sort_keys=True), encoding="utf-8"
    )
    return manifest


def test_validated_fixture_is_deserialized_only_after_contract_checks(tmp_path: Path) -> None:
    root = tmp_path / "shadow-model"
    manifest = _write_fixture(root)
    loader = SafeShadowModelArtifactLoader(data_root=tmp_path / "formal-data")

    result = loader.load(root, expectation=_expectation())

    assert result.status == "shadow_model_ready"
    assert result.manifest == manifest
    assert result.model == FixtureShadowBundle()
    assert result.blockers == ()
    assert result.formal_rule_unchanged is True
    assert result.production_action_allowed is False


def test_hash_mismatch_falls_back_without_calling_deserializer(tmp_path: Path) -> None:
    root = tmp_path / "shadow-model"
    _write_fixture(root)
    (root / "model-1.joblib").write_bytes(b"tampered")
    called = False

    def forbidden_deserializer(path: Path) -> object:
        nonlocal called
        called = True
        raise AssertionError(f"must not deserialize {path}")

    result = SafeShadowModelArtifactLoader(
        data_root=tmp_path / "formal-data", deserializer=forbidden_deserializer
    ).load(root, expectation=_expectation())

    assert result.status == "rule_only_fallback"
    assert result.model is None
    assert result.blockers == ("artifact_hash_mismatch",)
    assert called is False


def test_schema_family_and_shadow_flag_mismatches_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "shadow-model"
    _write_fixture(root)
    loader = SafeShadowModelArtifactLoader(data_root=tmp_path / "formal-data")

    schema_result = loader.load(
        root,
        expectation=_expectation(expected_feature_schema=(("other", "int", "bp"),)),
    )
    family_result = loader.load(
        root,
        expectation=_expectation(expected_model_family="other_family"),
    )
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    payload["shadow_only"] = False
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    flags_result = loader.load(root, expectation=_expectation())

    assert schema_result.blockers == ("feature_schema_mismatch",)
    assert family_result.blockers == ("model_family_mismatch",)
    assert flags_result.blockers == ("manifest_shadow_flags_invalid",)
    assert all(result.status == "rule_only_fallback" for result in (schema_result, family_result, flags_result))


def test_deserialized_identity_mismatch_and_missing_manifest_fall_back(tmp_path: Path) -> None:
    root = tmp_path / "shadow-model"
    _write_fixture(root, bundle=FixtureShadowBundle(model_id="wrong-model"))
    loader = SafeShadowModelArtifactLoader(data_root=tmp_path / "formal-data")

    identity_result = loader.load(root, expectation=_expectation())
    missing_result = loader.load(tmp_path / "missing", expectation=_expectation())

    assert identity_result.status == "rule_only_fallback"
    assert identity_result.model is None
    assert identity_result.blockers == ("deserialized_model_identity_mismatch",)
    assert missing_result.blockers == ("manifest_missing",)


def test_data_root_artifact_path_is_rejected_before_read(tmp_path: Path) -> None:
    formal_root = tmp_path / "formal-data"
    loader = SafeShadowModelArtifactLoader(data_root=formal_root)

    result = loader.load(formal_root / "models" / "model-1", expectation=_expectation())

    assert result.status == "rule_only_fallback"
    assert result.blockers == ("artifact_root_not_shadow_safe",)
