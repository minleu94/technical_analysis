"""Fail-closed consumer for producer-owned shadow model artifacts.

This module validates the B-owned manifest and load contract before invoking
joblib.  It intentionally does not build features or run model inference.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

import joblib

from ml_module.model_artifact_manifest import FeatureSchema, ModelArtifactManifest


@dataclass(frozen=True)
class ArtifactCompatibilityExpectation:
    expected_model_family: str
    expected_feature_registry_hash: str
    expected_label_registry_hash: str
    expected_feature_schema: FeatureSchema
    installed_library_versions: Mapping[str, str]


@dataclass(frozen=True)
class ShadowModelArtifactLoadResult:
    status: str
    manifest: ModelArtifactManifest | None
    model: Any | None
    blockers: tuple[str, ...]
    formal_rule_unchanged: bool = True
    production_action_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.formal_rule_unchanged or self.production_action_allowed:
            raise ValueError("artifact load result must preserve the formal rule path")
        if self.status == "shadow_model_ready":
            if self.manifest is None or self.model is None or self.blockers:
                raise ValueError("ready artifact result requires manifest and model")
        elif self.status == "rule_only_fallback":
            if self.model is not None or not self.blockers:
                raise ValueError("fallback artifact result requires blockers and no model")
        else:
            raise ValueError(f"unsupported artifact load status: {self.status}")

    @classmethod
    def ready(
        cls, manifest: ModelArtifactManifest, model: Any
    ) -> "ShadowModelArtifactLoadResult":
        return cls(status="shadow_model_ready", manifest=manifest, model=model, blockers=())

    @classmethod
    def fallback(
        cls, blocker: str, *, manifest: ModelArtifactManifest | None = None
    ) -> "ShadowModelArtifactLoadResult":
        return cls(
            status="rule_only_fallback",
            manifest=manifest,
            model=None,
            blockers=(blocker,),
        )


class SafeShadowModelArtifactLoader:
    def __init__(
        self,
        *,
        data_root: str | Path | None = None,
        deserializer: Callable[[Path], Any] = joblib.load,
    ) -> None:
        self._data_root = Path(
            data_root or os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")
        ).resolve()
        self._deserializer = deserializer

    def load(
        self,
        artifact_root: str | Path,
        *,
        expectation: ArtifactCompatibilityExpectation,
    ) -> ShadowModelArtifactLoadResult:
        raw_root = Path(artifact_root)
        root = raw_root.resolve()
        if not raw_root.is_absolute() or root == self._data_root or self._data_root in root.parents:
            return ShadowModelArtifactLoadResult.fallback("artifact_root_not_shadow_safe")

        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            return ShadowModelArtifactLoadResult.fallback("manifest_missing")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ModelArtifactManifest.from_dict(payload)
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            return ShadowModelArtifactLoadResult.fallback(_manifest_blocker(exc))

        try:
            manifest.to_load_contract().validate(
                expected_model_family=expectation.expected_model_family,
                expected_feature_registry_hash=expectation.expected_feature_registry_hash,
                expected_label_registry_hash=expectation.expected_label_registry_hash,
                expected_feature_schema=expectation.expected_feature_schema,
                installed_library_versions=expectation.installed_library_versions,
            )
        except ValueError as exc:
            return ShadowModelArtifactLoadResult.fallback(
                _compatibility_blocker(exc), manifest=manifest
            )

        artifact_path = (root / manifest.artifact_filename).resolve()
        if artifact_path.parent != root or not artifact_path.is_file():
            return ShadowModelArtifactLoadResult.fallback(
                "artifact_missing_or_uncontrolled", manifest=manifest
            )
        if _sha256_file(artifact_path) != manifest.artifact_hash:
            return ShadowModelArtifactLoadResult.fallback(
                "artifact_hash_mismatch", manifest=manifest
            )

        try:
            model = self._deserializer(artifact_path)
        except Exception:
            return ShadowModelArtifactLoadResult.fallback(
                "artifact_deserialization_failed", manifest=manifest
            )
        if not _model_matches_manifest(model, manifest):
            return ShadowModelArtifactLoadResult.fallback(
                "deserialized_model_identity_mismatch", manifest=manifest
            )
        return ShadowModelArtifactLoadResult.ready(manifest, model)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _model_matches_manifest(model: Any, manifest: ModelArtifactManifest) -> bool:
    return (
        getattr(model, "model_id", None) == manifest.model_id
        and getattr(model, "dataset_id", None) == manifest.dataset_id
        and getattr(model, "model_family", None) == manifest.model_family
        and getattr(model, "shadow_only", None) is True
        and getattr(model, "production_eligible", None) is False
        and getattr(model, "production_action_allowed", False) is False
    )


def _manifest_blocker(error: Exception) -> str:
    message = str(error)
    if "shadow flags" in message:
        return "manifest_shadow_flags_invalid"
    if "manifest hash" in message:
        return "manifest_hash_mismatch"
    if "schema_version" in message:
        return "manifest_schema_version_mismatch"
    return "manifest_invalid"


def _compatibility_blocker(error: ValueError) -> str:
    message = str(error)
    mappings = {
        "model family mismatch": "model_family_mismatch",
        "feature registry hash mismatch": "feature_registry_hash_mismatch",
        "label registry hash mismatch": "label_registry_hash_mismatch",
        "feature schema mismatch": "feature_schema_mismatch",
        "library version mismatch": "library_version_mismatch",
        "not shadow-only": "manifest_shadow_flags_invalid",
    }
    for fragment, blocker in mappings.items():
        if fragment in message:
            return blocker
    return "artifact_load_contract_mismatch"
