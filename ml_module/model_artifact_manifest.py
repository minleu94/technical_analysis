"""Producer-owned model artifact record and metadata-only load contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


FeatureSchema = tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class ModelArtifactLoadContract:
    model_id: str
    dataset_id: str
    created_run_id: str
    model_family: str
    feature_registry_hash: str
    label_registry_hash: str
    feature_schema: FeatureSchema
    training_as_of: str
    hyperparameters_hash: str
    library_versions: Mapping[str, str]
    serialization_format: str
    artifact_filename: str
    artifact_hash: str
    manifest_hash: str
    shadow_only: bool
    production_eligible: bool
    production_action_allowed: bool

    def validate(
        self,
        *,
        expected_model_family: str,
        expected_feature_registry_hash: str,
        expected_label_registry_hash: str,
        expected_feature_schema: FeatureSchema,
        installed_library_versions: Mapping[str, str],
    ) -> None:
        if not self.shadow_only or self.production_eligible or self.production_action_allowed:
            raise ValueError("model artifact is not shadow-only")
        if expected_model_family != self.model_family:
            raise ValueError("model family mismatch")
        if expected_feature_registry_hash != self.feature_registry_hash:
            raise ValueError("feature registry hash mismatch")
        if expected_label_registry_hash != self.label_registry_hash:
            raise ValueError("label registry hash mismatch")
        if expected_feature_schema != self.feature_schema:
            raise ValueError("feature schema mismatch")
        for library, recorded_version in self.library_versions.items():
            installed_version = installed_library_versions.get(library)
            if installed_version is None or _major_minor(installed_version) != _major_minor(
                recorded_version
            ):
                raise ValueError(f"library version mismatch: {library}")


@dataclass(frozen=True)
class ModelArtifactManifest:
    model_id: str
    dataset_id: str
    created_run_id: str
    created_at: str
    model_family: str
    feature_registry_hash: str
    label_registry_hash: str
    feature_schema: FeatureSchema
    training_as_of: str
    hyperparameters_hash: str
    library_versions: Mapping[str, str]
    serialization_format: str
    artifact_filename: str
    artifact_hash: str
    manifest_hash: str
    research_alpha_bp: int = 0
    production_alpha_bp: int = 0
    blend_selection_metric: str = "return_mae_bp"
    blend_selection_label_cutoff: str = ""
    blend_selection_threshold_bp: int = 0
    schema_version: str = "ml-model-artifact-manifest.v1"
    frozen: bool = True
    shadow_only: bool = True
    production_eligible: bool = False
    production_action_allowed: bool = False

    @classmethod
    def create(
        cls,
        *,
        model_id: str,
        dataset_id: str,
        created_run_id: str,
        created_at: str,
        model_family: str,
        feature_registry_hash: str,
        label_registry_hash: str,
        feature_schema: FeatureSchema,
        training_as_of: str,
        hyperparameters_hash: str,
        library_versions: Mapping[str, str],
        serialization_format: str,
        artifact_filename: str,
        artifact_hash: str,
        research_alpha_bp: int = 0,
        production_alpha_bp: int = 0,
        blend_selection_metric: str = "return_mae_bp",
        blend_selection_label_cutoff: str | None = None,
        blend_selection_threshold_bp: int = 0,
    ) -> "ModelArtifactManifest":
        text_fields = {
            "model_id": model_id,
            "dataset_id": dataset_id,
            "created_run_id": created_run_id,
            "created_at": created_at,
            "model_family": model_family,
        }
        for field_name, value in text_fields.items():
            if not value or not value.strip():
                raise ValueError(f"{field_name} is required")
        _require_sha256(feature_registry_hash, field_name="feature_registry_hash")
        _require_sha256(label_registry_hash, field_name="label_registry_hash")
        _require_sha256(hyperparameters_hash, field_name="hyperparameters_hash")
        _require_sha256(artifact_hash, field_name="artifact_hash")
        training_cutoff = date.fromisoformat(training_as_of[:10])
        selection_cutoff = blend_selection_label_cutoff or training_as_of
        if date.fromisoformat(selection_cutoff[:10]) > training_cutoff:
            raise ValueError("blend_selection_label_cutoff must not exceed training_as_of")
        if production_alpha_bp != 0:
            raise ValueError("production_alpha_bp must remain zero")
        for field_name, numeric_value in {
            "research_alpha_bp": research_alpha_bp,
            "blend_selection_threshold_bp": blend_selection_threshold_bp,
        }.items():
            if isinstance(numeric_value, bool) or not isinstance(numeric_value, int):
                raise TypeError(f"{field_name} must be an integer basis-point value")
        if research_alpha_bp < 0 or research_alpha_bp > 10_000:
            raise ValueError("research_alpha_bp must be within 0..10000")
        if not blend_selection_metric:
            raise ValueError("blend_selection_metric is required")
        if not feature_schema:
            raise ValueError("feature_schema is required")
        feature_ids = tuple(item[0] for item in feature_schema)
        if (
            any(len(item) != 3 or not all(item) for item in feature_schema)
            or len(feature_ids) != len(set(feature_ids))
        ):
            raise ValueError("feature_schema entries must be unique id/dtype/unit triples")
        normalized_versions = dict(sorted(library_versions.items()))
        if not normalized_versions:
            raise ValueError("library_versions are required")
        for library, version in normalized_versions.items():
            if not library or not version:
                raise ValueError("library_versions require non-empty names and versions")
            _major_minor(version)
        if serialization_format not in {"joblib"}:
            raise ValueError("serialization_format is unsupported")
        if (
            not artifact_filename
            or artifact_filename in {".", ".."}
            or "/" in artifact_filename
            or "\\" in artifact_filename
        ):
            raise ValueError("artifact_filename must be a controlled basename")
        payload = {
            "schema_version": "ml-model-artifact-manifest.v1",
            "model_id": model_id,
            "dataset_id": dataset_id,
            "created_run_id": created_run_id,
            "created_at": created_at,
            "model_family": model_family,
            "feature_registry_hash": feature_registry_hash,
            "label_registry_hash": label_registry_hash,
            "feature_schema": [list(item) for item in feature_schema],
            "training_as_of": training_as_of,
            "hyperparameters_hash": hyperparameters_hash,
            "library_versions": normalized_versions,
            "serialization_format": serialization_format,
            "artifact_filename": artifact_filename,
            "artifact_hash": artifact_hash,
            "research_alpha_bp": research_alpha_bp,
            "production_alpha_bp": 0,
            "blend_selection_metric": blend_selection_metric,
            "blend_selection_label_cutoff": selection_cutoff,
            "blend_selection_threshold_bp": blend_selection_threshold_bp,
            "frozen": True,
            "shadow_only": True,
            "production_eligible": False,
            "production_action_allowed": False,
        }
        manifest_hash = _payload_hash(payload)
        return cls(
            model_id=model_id,
            dataset_id=dataset_id,
            created_run_id=created_run_id,
            created_at=created_at,
            model_family=model_family,
            feature_registry_hash=feature_registry_hash,
            label_registry_hash=label_registry_hash,
            feature_schema=feature_schema,
            training_as_of=training_as_of,
            hyperparameters_hash=hyperparameters_hash,
            library_versions=MappingProxyType(normalized_versions),
            serialization_format=serialization_format,
            artifact_filename=artifact_filename,
            artifact_hash=artifact_hash,
            manifest_hash=manifest_hash,
            research_alpha_bp=research_alpha_bp,
            production_alpha_bp=0,
            blend_selection_metric=blend_selection_metric,
            blend_selection_label_cutoff=selection_cutoff,
            blend_selection_threshold_bp=blend_selection_threshold_bp,
        )

    def to_load_contract(self) -> ModelArtifactLoadContract:
        return ModelArtifactLoadContract(
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            created_run_id=self.created_run_id,
            model_family=self.model_family,
            feature_registry_hash=self.feature_registry_hash,
            label_registry_hash=self.label_registry_hash,
            feature_schema=self.feature_schema,
            training_as_of=self.training_as_of,
            hyperparameters_hash=self.hyperparameters_hash,
            library_versions=self.library_versions,
            serialization_format=self.serialization_format,
            artifact_filename=self.artifact_filename,
            artifact_hash=self.artifact_hash,
            manifest_hash=self.manifest_hash,
            shadow_only=self.shadow_only,
            production_eligible=self.production_eligible,
            production_action_allowed=self.production_action_allowed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "dataset_id": self.dataset_id,
            "created_run_id": self.created_run_id,
            "created_at": self.created_at,
            "model_family": self.model_family,
            "feature_registry_hash": self.feature_registry_hash,
            "label_registry_hash": self.label_registry_hash,
            "feature_schema": [list(item) for item in self.feature_schema],
            "training_as_of": self.training_as_of,
            "hyperparameters_hash": self.hyperparameters_hash,
            "library_versions": dict(self.library_versions),
            "serialization_format": self.serialization_format,
            "artifact_filename": self.artifact_filename,
            "artifact_hash": self.artifact_hash,
            "research_alpha_bp": self.research_alpha_bp,
            "production_alpha_bp": self.production_alpha_bp,
            "blend_selection_metric": self.blend_selection_metric,
            "blend_selection_label_cutoff": self.blend_selection_label_cutoff,
            "blend_selection_threshold_bp": self.blend_selection_threshold_bp,
            "manifest_hash": self.manifest_hash,
            "frozen": self.frozen,
            "shadow_only": self.shadow_only,
            "production_eligible": self.production_eligible,
            "production_action_allowed": self.production_action_allowed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ModelArtifactManifest":
        if payload.get("schema_version") != "ml-model-artifact-manifest.v1":
            raise ValueError("unsupported model artifact manifest schema_version")
        if (
            payload.get("frozen") is not True
            or payload.get("shadow_only") is not True
            or payload.get("production_eligible") is not False
            or payload.get("production_action_allowed") is not False
        ):
            raise ValueError("model artifact manifest shadow flags are invalid")
        manifest = cls.create(
            model_id=str(payload["model_id"]),
            dataset_id=str(payload["dataset_id"]),
            created_run_id=str(payload["created_run_id"]),
            created_at=str(payload["created_at"]),
            model_family=str(payload["model_family"]),
            feature_registry_hash=str(payload["feature_registry_hash"]),
            label_registry_hash=str(payload["label_registry_hash"]),
            feature_schema=tuple(tuple(item) for item in payload["feature_schema"]),
            training_as_of=str(payload["training_as_of"]),
            hyperparameters_hash=str(payload["hyperparameters_hash"]),
            library_versions=payload["library_versions"],
            serialization_format=str(payload["serialization_format"]),
            artifact_filename=str(payload["artifact_filename"]),
            artifact_hash=str(payload["artifact_hash"]),
            research_alpha_bp=int(payload.get("research_alpha_bp", 0)),
            production_alpha_bp=int(payload.get("production_alpha_bp", 0)),
            blend_selection_metric=str(payload.get("blend_selection_metric", "return_mae_bp")),
            blend_selection_label_cutoff=str(
                payload.get("blend_selection_label_cutoff", payload["training_as_of"])
            ),
            blend_selection_threshold_bp=int(payload.get("blend_selection_threshold_bp", 0)),
        )
        if manifest.manifest_hash != payload.get("manifest_hash"):
            raise ValueError("model artifact manifest hash mismatch")
        return manifest


def _require_sha256(value: str, *, field_name: str) -> None:
    prefix = "sha256:"
    digest = value[len(prefix) :] if value.startswith(prefix) else ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _major_minor(version: str) -> tuple[int, int]:
    parts = version.split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"library version must include numeric major.minor: {version}")
    return int(parts[0]), int(parts[1])


def _payload_hash(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"
