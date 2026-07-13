"""Frozen ML dataset manifests and append-only registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType
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


@dataclass(frozen=True)
class MLDatasetManifestV2:
    """Causal historical dataset contract consumed by shadow inference."""

    dataset_id: str
    created_at: str
    decision_date_start: str
    decision_date_end: str
    row_count: int
    features: tuple[MLDatasetField, ...]
    labels: tuple[MLDatasetField, ...]
    feature_registry_hash: str
    label_registry_hash: str
    universe_policy_id: str
    decision_timing: str
    split_policy: str
    source_fingerprints: Mapping[str, str]
    accepted_diagnostics: Mapping[str, int]
    excluded_diagnostics: Mapping[str, int]
    corporate_action_coverage: str
    broker_eligibility: str
    fundamental_eligibility: str
    content_hash: str
    manifest_hash: str
    schema_version: str = "ml-dataset-manifest.v2"
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
        feature_registry_hash: str,
        label_registry_hash: str,
        universe_policy_id: str,
        decision_timing: str,
        split_policy: str,
        source_fingerprints: Mapping[str, str],
        accepted_diagnostics: Mapping[str, int],
        excluded_diagnostics: Mapping[str, int],
        corporate_action_coverage: str,
        broker_eligibility: str,
        fundamental_eligibility: str,
        content_hash: str,
    ) -> "MLDatasetManifestV2":
        text_fields = {
            "dataset_id": dataset_id,
            "created_at": created_at,
            "universe_policy_id": universe_policy_id,
            "corporate_action_coverage": corporate_action_coverage,
            "broker_eligibility": broker_eligibility,
            "fundamental_eligibility": fundamental_eligibility,
        }
        for field_name, value in text_fields.items():
            if not value or not value.strip():
                raise ValueError(f"{field_name} is required")
        if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
            raise ValueError("row_count must be positive")
        if date.fromisoformat(decision_date_start[:10]) > date.fromisoformat(
            decision_date_end[:10]
        ):
            raise ValueError("decision date range is invalid")
        if not features or not labels:
            raise ValueError("features and labels are required")
        if not all(field.available_date_required for field in (*features, *labels)):
            raise ValueError("every ML field requires an available-date contract")
        _require_unique_fields(features, kind="feature")
        _require_unique_fields(labels, kind="label")
        _require_sha256(feature_registry_hash, field_name="feature_registry_hash")
        _require_sha256(label_registry_hash, field_name="label_registry_hash")
        _require_sha256(content_hash, field_name="content_hash")
        if decision_timing != "decision_t_uses_previous_trading_day":
            raise ValueError("decision_timing must enforce the previous trading day cutoff")
        if split_policy != "expanding_purged_walk_forward_trading_calendar":
            raise ValueError("split_policy must use trading-calendar purged walk-forward")
        if broker_eligibility != "excluded_separate_addon":
            raise ValueError("broker_eligibility must keep broker data in a separate add-on")
        if fundamental_eligibility != "ineligible_pending_pit_repair":
            raise ValueError(
                "fundamental_eligibility must remain ineligible_pending_pit_repair"
            )
        normalized_sources = dict(sorted(source_fingerprints.items()))
        if not normalized_sources:
            raise ValueError("source_fingerprints are required")
        for source_id, fingerprint in normalized_sources.items():
            if not source_id:
                raise ValueError("source fingerprint ids must be non-empty")
            _require_sha256(fingerprint, field_name=f"source_fingerprints[{source_id}]")
        normalized_accepted = _normalize_counts(accepted_diagnostics)
        normalized_excluded = _normalize_counts(excluded_diagnostics)
        payload = {
            "schema_version": "ml-dataset-manifest.v2",
            "dataset_id": dataset_id,
            "created_at": created_at,
            "decision_date_start": decision_date_start,
            "decision_date_end": decision_date_end,
            "row_count": row_count,
            "features": [field.to_dict() for field in features],
            "labels": [field.to_dict() for field in labels],
            "feature_registry_hash": feature_registry_hash,
            "label_registry_hash": label_registry_hash,
            "universe_policy_id": universe_policy_id,
            "decision_timing": decision_timing,
            "split_policy": split_policy,
            "source_fingerprints": normalized_sources,
            "accepted_diagnostics": normalized_accepted,
            "excluded_diagnostics": normalized_excluded,
            "corporate_action_coverage": corporate_action_coverage,
            "broker_eligibility": broker_eligibility,
            "fundamental_eligibility": fundamental_eligibility,
            "content_hash": content_hash,
            "frozen": True,
            "shadow_only": True,
            "production_eligible": False,
        }
        manifest_hash = _payload_hash(payload)
        return cls(
            dataset_id=dataset_id,
            created_at=created_at,
            decision_date_start=decision_date_start,
            decision_date_end=decision_date_end,
            row_count=row_count,
            features=features,
            labels=labels,
            feature_registry_hash=feature_registry_hash,
            label_registry_hash=label_registry_hash,
            universe_policy_id=universe_policy_id,
            decision_timing=decision_timing,
            split_policy=split_policy,
            source_fingerprints=MappingProxyType(normalized_sources),
            accepted_diagnostics=MappingProxyType(normalized_accepted),
            excluded_diagnostics=MappingProxyType(normalized_excluded),
            corporate_action_coverage=corporate_action_coverage,
            broker_eligibility=broker_eligibility,
            fundamental_eligibility=fundamental_eligibility,
            content_hash=content_hash,
            manifest_hash=manifest_hash,
        )

    @property
    def feature_canonical_order(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.features)

    @property
    def feature_dtypes(self) -> tuple[str, ...]:
        return tuple(field.dtype for field in self.features)

    def assert_feature_contract(
        self,
        *,
        registry_hash: str,
        canonical_ids: tuple[str, ...],
        canonical_dtypes: tuple[str, ...],
    ) -> None:
        if registry_hash != self.feature_registry_hash:
            raise ValueError("feature registry hash mismatch")
        if canonical_ids != self.feature_canonical_order:
            raise ValueError("feature canonical order mismatch")
        if canonical_dtypes != self.feature_dtypes:
            raise ValueError("feature dtype mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "created_at": self.created_at,
            "decision_date_start": self.decision_date_start,
            "decision_date_end": self.decision_date_end,
            "row_count": self.row_count,
            "features": [field.to_dict() for field in self.features],
            "labels": [field.to_dict() for field in self.labels],
            "feature_registry_hash": self.feature_registry_hash,
            "label_registry_hash": self.label_registry_hash,
            "universe_policy_id": self.universe_policy_id,
            "decision_timing": self.decision_timing,
            "split_policy": self.split_policy,
            "source_fingerprints": dict(self.source_fingerprints),
            "accepted_diagnostics": dict(self.accepted_diagnostics),
            "excluded_diagnostics": dict(self.excluded_diagnostics),
            "corporate_action_coverage": self.corporate_action_coverage,
            "broker_eligibility": self.broker_eligibility,
            "fundamental_eligibility": self.fundamental_eligibility,
            "content_hash": self.content_hash,
            "manifest_hash": self.manifest_hash,
            "frozen": self.frozen,
            "shadow_only": self.shadow_only,
            "production_eligible": self.production_eligible,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MLDatasetManifestV2":
        if payload.get("schema_version") != "ml-dataset-manifest.v2":
            raise ValueError("unsupported dataset manifest schema_version")
        if (
            payload.get("frozen") is not True
            or payload.get("shadow_only") is not True
            or payload.get("production_eligible") is not False
        ):
            raise ValueError("dataset manifest shadow flags are invalid")
        manifest = cls.create(
            dataset_id=str(payload["dataset_id"]),
            created_at=str(payload["created_at"]),
            decision_date_start=str(payload["decision_date_start"]),
            decision_date_end=str(payload["decision_date_end"]),
            row_count=int(payload["row_count"]),
            features=tuple(MLDatasetField(**item) for item in payload["features"]),
            labels=tuple(MLDatasetField(**item) for item in payload["labels"]),
            feature_registry_hash=str(payload["feature_registry_hash"]),
            label_registry_hash=str(payload["label_registry_hash"]),
            universe_policy_id=str(payload["universe_policy_id"]),
            decision_timing=str(payload["decision_timing"]),
            split_policy=str(payload["split_policy"]),
            source_fingerprints=payload["source_fingerprints"],
            accepted_diagnostics=payload["accepted_diagnostics"],
            excluded_diagnostics=payload["excluded_diagnostics"],
            corporate_action_coverage=str(payload["corporate_action_coverage"]),
            broker_eligibility=str(payload["broker_eligibility"]),
            fundamental_eligibility=str(payload["fundamental_eligibility"]),
            content_hash=str(payload["content_hash"]),
        )
        if manifest.manifest_hash != payload.get("manifest_hash"):
            raise ValueError("dataset manifest hash mismatch")
        return manifest


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


def _require_unique_fields(fields: tuple[MLDatasetField, ...], *, kind: str) -> None:
    names = tuple(field.name for field in fields)
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError(f"{kind} field names must be non-empty and unique")


def _require_sha256(value: str, *, field_name: str) -> None:
    prefix = "sha256:"
    digest = value[len(prefix) :] if value.startswith(prefix) else ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _normalize_counts(values: Mapping[str, int]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, value in sorted(values.items()):
        if not key or isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("diagnostic counts require non-empty ids and non-negative integers")
        normalized[key] = value
    return normalized


def _payload_hash(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"
