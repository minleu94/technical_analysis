"""Validated JSON input provider for evidence-rehearsal ML shadow comparison."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from app_module.evidence_rehearsal_ml_comparison import MLShadowDiagnosticsInput
from app_module.evidence_rehearsal_orchestrator import EvidenceRehearsalMLInputs


@dataclass(frozen=True)
class _FeatureValue:
    feature_id: str
    value: Any
    available_date: str


@dataclass(frozen=True)
class _LabelValue:
    label_id: str
    value: Any
    available_date: str
    maturity_status: str


@dataclass(frozen=True)
class _TrainingRow:
    row_id: str
    decision_date: str
    features: tuple[_FeatureValue, ...]
    label: _LabelValue


@dataclass(frozen=True)
class _BoundaryFilterResult:
    accepted_rows: tuple[_TrainingRow, ...]
    rejected_row_ids: tuple[str, ...]
    diagnostics_by_row: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class _Manifest:
    dataset_id: str
    created_at: str
    row_count: int
    frozen: bool
    shadow_only: bool
    production_eligible: bool


@dataclass(frozen=True)
class _Prediction:
    dataset_id: str
    shadow_only: bool
    production_action_allowed: bool


class JsonMLRehearsalEvidenceProvider:
    """Load boundary evidence without trusting a caller-supplied status field."""

    def __init__(self, root: Path) -> None:
        self._path = Path(root) / "rehearsal-ml-input.json"

    def load(self) -> EvidenceRehearsalMLInputs:
        payload = _read_mapping(self._path)
        manifest_payload = _required_mapping(payload, "manifest")
        manifest = _Manifest(
            dataset_id=_required_str(manifest_payload, "dataset_id"),
            created_at=_required_str(manifest_payload, "created_at"),
            row_count=_required_int(manifest_payload, "row_count"),
            frozen=_required_bool(manifest_payload, "frozen"),
            shadow_only=_required_bool(manifest_payload, "shadow_only"),
            production_eligible=_required_bool(
                manifest_payload, "production_eligible"
            ),
        )
        if (
            not manifest.frozen
            or not manifest.shadow_only
            or manifest.production_eligible
        ):
            raise ValueError("manifest must remain frozen and shadow-only")

        accepted_rows = tuple(
            _training_row(item)
            for item in _required_mapping_list(payload, "accepted_rows")
        )
        rejected_rows = _required_mapping_list(payload, "rejected_rows")
        rejected_row_ids = tuple(
            _required_str(item, "row_id") for item in rejected_rows
        )
        diagnostics_by_row = tuple(
            (
                _required_str(item, "row_id"),
                tuple(_required_str_list(item, "diagnostics")),
            )
            for item in rejected_rows
        )
        boundary_report = _BoundaryFilterResult(
            accepted_rows=accepted_rows,
            rejected_row_ids=rejected_row_ids,
            diagnostics_by_row=diagnostics_by_row,
        )
        predictions = tuple(
            _prediction(item, manifest.dataset_id)
            for item in _required_mapping_list(payload, "predictions")
        )
        training_as_of = payload.get("training_as_of")
        if training_as_of is not None and not isinstance(training_as_of, str):
            raise ValueError("training_as_of must be a string")
        return EvidenceRehearsalMLInputs(
            manifest=manifest,
            boundary_report=boundary_report,
            predictions=predictions,
            diagnostics=MLShadowDiagnosticsInput(training_as_of=training_as_of),
        )


def _read_mapping(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"ML rehearsal input must be readable JSON: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("ML rehearsal input must contain a JSON object")
    return payload


def _training_row(payload: Mapping[str, Any]) -> _TrainingRow:
    feature_payloads = _required_mapping_list(payload, "features")
    label_payload = _required_mapping(payload, "label")
    return _TrainingRow(
        row_id=_required_str(payload, "row_id"),
        decision_date=_required_str(payload, "decision_date"),
        features=tuple(
            _FeatureValue(
                feature_id=_required_str(item, "feature_id"),
                value=item.get("value"),
                available_date=_required_str(item, "available_date"),
            )
            for item in feature_payloads
        ),
        label=_LabelValue(
            label_id=_optional_str(label_payload, "label_id", "label"),
            value=label_payload.get("value"),
            available_date=_required_str(label_payload, "available_date"),
            maturity_status=_required_str(label_payload, "maturity_status"),
        ),
    )


def _prediction(payload: Mapping[str, Any], dataset_id: str) -> _Prediction:
    return _Prediction(
        dataset_id=_optional_str(payload, "dataset_id", dataset_id),
        shadow_only=_required_bool(payload, "shadow_only"),
        production_action_allowed=_required_bool(
            payload, "production_action_allowed"
        ),
    )


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _required_mapping_list(
    payload: Mapping[str, Any], key: str
) -> tuple[Mapping[str, Any], ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{key} must be a list of objects")
    return tuple(value)


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_str(payload: Mapping[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_str_list(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{key} must be a list of non-empty strings")
    return tuple(value)


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value
