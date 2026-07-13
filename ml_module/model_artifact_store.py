"""Hash-verified storage for opaque shadow model artifacts.

The store deliberately treats model bytes as opaque.  Deserialization and
feature transformation remain owned by the frozen historical-model contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping


@dataclass(frozen=True)
class ShadowModelArtifactManifest:
    model_id: str
    dataset_id: str
    feature_registry_hash: str
    label_registry_hash: str
    model_family: str
    training_cutoff: str
    created_run_id: str
    library_versions: Mapping[str, str]
    artifact_hash: str
    shadow_only: bool = True
    production_eligible: bool = False

    def __post_init__(self) -> None:
        required = (
            self.model_id,
            self.dataset_id,
            self.feature_registry_hash,
            self.label_registry_hash,
            self.model_family,
            self.training_cutoff,
            self.created_run_id,
            self.artifact_hash,
        )
        if not all(required):
            raise ValueError("complete artifact identity is required")
        if not self.shadow_only or self.production_eligible:
            raise ValueError("model artifact must remain shadow-only")

    @classmethod
    def create(
        cls,
        *,
        model_id: str,
        dataset_id: str,
        feature_registry_hash: str,
        label_registry_hash: str,
        model_family: str,
        training_cutoff: str,
        created_run_id: str,
        library_versions: Mapping[str, str],
        artifact_bytes: bytes,
    ) -> "ShadowModelArtifactManifest":
        return cls(
            model_id=model_id,
            dataset_id=dataset_id,
            feature_registry_hash=feature_registry_hash,
            label_registry_hash=label_registry_hash,
            model_family=model_family,
            training_cutoff=training_cutoff,
            created_run_id=created_run_id,
            library_versions=dict(sorted(library_versions.items())),
            artifact_hash=_sha256(artifact_bytes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "dataset_id": self.dataset_id,
            "feature_registry_hash": self.feature_registry_hash,
            "label_registry_hash": self.label_registry_hash,
            "model_family": self.model_family,
            "training_cutoff": self.training_cutoff,
            "created_run_id": self.created_run_id,
            "library_versions": dict(sorted(self.library_versions.items())),
            "artifact_hash": self.artifact_hash,
            "shadow_only": self.shadow_only,
            "production_eligible": self.production_eligible,
        }


@dataclass(frozen=True)
class LoadedShadowModelArtifact:
    manifest: ShadowModelArtifactManifest
    artifact_bytes: bytes


class ShadowModelArtifactStore:
    def __init__(self, root: str | Path, *, data_root: str | Path | None = None) -> None:
        self._root = _validate_shadow_path(root, data_root=data_root)

    def save(self, manifest: ShadowModelArtifactManifest, artifact_bytes: bytes) -> Path:
        if _sha256(artifact_bytes) != manifest.artifact_hash:
            raise ValueError("artifact hash does not match manifest")
        model_dir = self._root / manifest.model_id
        artifact_path = model_dir / "artifact.bin"
        manifest_path = model_dir / "manifest.json"
        if manifest_path.exists():
            existing = self._read_manifest(manifest_path)
            if existing != manifest or not artifact_path.exists() or _sha256(artifact_path.read_bytes()) != manifest.artifact_hash:
                raise ValueError(f"artifact conflict for model_id: {manifest.model_id}")
            return artifact_path

        model_dir.mkdir(parents=True, exist_ok=True)
        artifact_tmp = _write_temp(model_dir, artifact_bytes)
        manifest_bytes = json.dumps(
            manifest.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        manifest_tmp = _write_temp(model_dir, manifest_bytes)
        try:
            os.replace(artifact_tmp, artifact_path)
            os.replace(manifest_tmp, manifest_path)
        except Exception:
            artifact_tmp.unlink(missing_ok=True)
            manifest_tmp.unlink(missing_ok=True)
            if not manifest_path.exists():
                artifact_path.unlink(missing_ok=True)
            raise
        return artifact_path

    def load(
        self,
        model_id: str,
        *,
        expected_feature_registry_hash: str | None = None,
        expected_model_family: str | None = None,
    ) -> LoadedShadowModelArtifact:
        model_dir = self._root / model_id
        manifest_path = model_dir / "manifest.json"
        artifact_path = model_dir / "artifact.bin"
        if not manifest_path.is_file() or not artifact_path.is_file():
            raise FileNotFoundError(f"complete artifact is missing: {model_id}")
        manifest = self._read_manifest(manifest_path)
        artifact_bytes = artifact_path.read_bytes()
        if _sha256(artifact_bytes) != manifest.artifact_hash:
            raise ValueError("artifact hash mismatch")
        if expected_feature_registry_hash is not None and manifest.feature_registry_hash != expected_feature_registry_hash:
            raise ValueError("feature registry hash mismatch")
        if expected_model_family is not None and manifest.model_family != expected_model_family:
            raise ValueError("model family mismatch")
        return LoadedShadowModelArtifact(manifest=manifest, artifact_bytes=artifact_bytes)

    @staticmethod
    def _read_manifest(path: Path) -> ShadowModelArtifactManifest:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ShadowModelArtifactManifest(**payload)


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _write_temp(directory: Path, payload: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=".artifact-", dir=directory)
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _validate_shadow_path(path: str | Path, *, data_root: str | Path | None) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_absolute():
        raise ValueError("explicit absolute shadow path is required")
    formal_root = Path(data_root or os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    if resolved == formal_root or formal_root in resolved.parents:
        raise ValueError("shadow artifact path cannot be DATA_ROOT or its descendant")
    return resolved
