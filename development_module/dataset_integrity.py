"""Persisted Dataset V0 identity and semantic-content verification."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from development_module.contracts import DevelopmentDatasetManifest


def validate_persisted_dataset_v0(
    *,
    manifest_file: Path,
    dataset_file: Path,
    manifest: Mapping[str, object],
    dataset: Mapping[str, object],
) -> None:
    """Fail closed before training when persisted generation artifacts diverge."""
    if manifest_file.parent != dataset_file.parent:
        raise ValueError("manifest and dataset must share one generation directory")
    generation_id = _required_string(manifest, "generation_id")
    if manifest_file.parent.name != generation_id:
        raise ValueError("generation directory must match manifest generation_id")
    if manifest.get("dataset_id") != f"terra-development-v0:{generation_id}":
        raise ValueError("dataset_id must match manifest generation_id")

    fit_rows = _row_list(dataset, "fit_rows")
    evaluation_rows = _row_list(dataset, "evaluation_rows")
    _validate_count(manifest, "fit_row_count", len(fit_rows), "fit row count")
    _validate_count(
        manifest,
        "evaluation_row_count",
        len(evaluation_rows),
        "evaluation row count",
    )
    expected_hash = _required_string(manifest, "content_hash")
    observed_hash = persisted_dataset_content_hash(dataset)
    if observed_hash != expected_hash:
        raise ValueError("Dataset V0 content hash mismatch")


def persisted_dataset_content_hash(dataset: Mapping[str, object]) -> str:
    """Recompute the generator's semantic hash from its persisted JSON shape."""
    return DevelopmentDatasetManifest.canonical_sha256({
        "fit_rows": [_semantic_row(row) for row in _row_list(dataset, "fit_rows")],
        "evaluation_rows": [
            _semantic_row(row) for row in _row_list(dataset, "evaluation_rows")
        ],
    })


def _semantic_row(value: object) -> dict[str, object]:
    row = _mapping(value, "dataset row")
    features = row.get("features")
    labels = row.get("labels")
    if not isinstance(features, list) or not isinstance(labels, list):
        raise ValueError("invalid Dataset V0 row schema")
    return {
        "symbol": row.get("symbol"),
        "decision_date": row.get("decision_date"),
        "feature_as_of_date": row.get("feature_as_of_date"),
        "available_date": row.get("available_date"),
        "values": features,
        "labels": [_semantic_label(label) for label in labels],
    }


def _semantic_label(value: object) -> dict[str, object]:
    label = _mapping(value, "dataset label")
    return {
        "id": label.get("label_id"),
        "value": label.get("value"),
        "horizon_end_date": label.get("horizon_end_date"),
        "available_date": label.get("available_date"),
        "quality": label.get("quality"),
    }


def _row_list(dataset: Mapping[str, object], name: str) -> list[object]:
    value = dataset.get(name)
    if not isinstance(value, list):
        raise ValueError(f"Dataset V0 {name} must be an array")
    return value


def _validate_count(
    manifest: Mapping[str, object], name: str, observed: int, label: str
) -> None:
    expected = manifest.get(name)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != observed:
        raise ValueError(f"Dataset V0 {label} mismatch")


def _required_string(value: Mapping[str, object], name: str) -> str:
    field = value.get(name)
    if not isinstance(field, str) or not field.strip():
        raise ValueError(f"{name} is required")
    return field


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"invalid {label}")
    return value
