"""Frozen ML dataset manifests and append-only registry."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


@dataclass(frozen=True)
class MLDatasetField:
    name: str
    dtype: str
    source_id: str
    available_date_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "source_id": self.source_id,
            "available_date_required": self.available_date_required,
        }


@dataclass(frozen=True)
class MLDatasetManifest:
    dataset_id: str
    created_at: str
    decision_date_start: str
    decision_date_end: str
    row_count: int
    features: tuple[MLDatasetField, ...]
    labels: tuple[MLDatasetField, ...]
    source_versions: Mapping[str, str]
    content_hash: str
    manifest_hash: str
    frozen: bool = True
    shadow_only: bool = True
    production_eligible: bool = False

    @classmethod
    def create(
        cls,
        *,
        dataset_id: str,
        created_at: str,
        decision_date_start: str,
        decision_date_end: str,
        row_count: int,
        features: tuple[MLDatasetField, ...],
        labels: tuple[MLDatasetField, ...],
        source_versions: Mapping[str, str],
        content_hash: str,
    ) -> "MLDatasetManifest":
        if not dataset_id or not content_hash:
            raise ValueError("dataset_id and content_hash are required")
        if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
            raise ValueError("row_count must be positive")
        if not features or not labels:
            raise ValueError("features and labels are required")
        if not all(field.available_date_required for field in (*features, *labels)):
            raise ValueError("every ML field requires an available-date contract")
        payload = {
            "dataset_id": dataset_id,
            "created_at": created_at,
            "decision_date_start": decision_date_start,
            "decision_date_end": decision_date_end,
            "row_count": row_count,
            "features": [field.to_dict() for field in features],
            "labels": [field.to_dict() for field in labels],
            "source_versions": dict(sorted(source_versions.items())),
            "content_hash": content_hash,
            "frozen": True,
            "shadow_only": True,
            "production_eligible": False,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            dataset_id=dataset_id,
            created_at=created_at,
            decision_date_start=decision_date_start,
            decision_date_end=decision_date_end,
            row_count=row_count,
            features=features,
            labels=labels,
            source_versions=dict(sorted(source_versions.items())),
            content_hash=content_hash,
            manifest_hash=f"sha256:{digest}",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "created_at": self.created_at,
            "decision_date_start": self.decision_date_start,
            "decision_date_end": self.decision_date_end,
            "row_count": self.row_count,
            "features": [field.to_dict() for field in self.features],
            "labels": [field.to_dict() for field in self.labels],
            "source_versions": dict(self.source_versions),
            "content_hash": self.content_hash,
            "manifest_hash": self.manifest_hash,
            "frozen": self.frozen,
            "shadow_only": self.shadow_only,
            "production_eligible": self.production_eligible,
        }


class MLDatasetManifestRegistry:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS ml_dataset_manifests (dataset_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL)"
            )

    def append(self, manifest: MLDatasetManifest) -> None:
        try:
            with sqlite3.connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO ml_dataset_manifests VALUES (?, ?)",
                    (manifest.dataset_id, json.dumps(manifest.to_dict(), sort_keys=True)),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"dataset manifest already exists: {manifest.dataset_id}") from exc

    def get(self, dataset_id: str) -> MLDatasetManifest | None:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                "SELECT manifest_json FROM ml_dataset_manifests WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        return MLDatasetManifest(
            dataset_id=payload["dataset_id"],
            created_at=payload["created_at"],
            decision_date_start=payload["decision_date_start"],
            decision_date_end=payload["decision_date_end"],
            row_count=int(payload["row_count"]),
            features=tuple(MLDatasetField(**item) for item in payload["features"]),
            labels=tuple(MLDatasetField(**item) for item in payload["labels"]),
            source_versions=payload["source_versions"],
            content_hash=payload["content_hash"],
            manifest_hash=payload["manifest_hash"],
            frozen=bool(payload["frozen"]),
            shadow_only=bool(payload["shadow_only"]),
            production_eligible=bool(payload["production_eligible"]),
        )
