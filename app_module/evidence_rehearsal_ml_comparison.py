"""Evidence rehearsal 的唯讀 ML shadow 比較摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


_MINIMUM_SHADOW_SAMPLE_COUNT = 20


class _FeatureValue(Protocol):
    value: object


class _TrainingRow(Protocol):
    features: tuple[_FeatureValue, ...]


class _BoundaryFilterReport(Protocol):
    accepted_rows: tuple[_TrainingRow, ...]
    rejected_row_ids: tuple[str, ...]
    diagnostics_by_row: tuple[tuple[str, tuple[str, ...]], ...]


class _DatasetManifest(Protocol):
    dataset_id: str
    row_count: int
    frozen: bool
    shadow_only: bool
    production_eligible: bool


class _ShadowPredictionRecord(Protocol):
    dataset_id: str
    shadow_only: bool
    production_action_allowed: bool


@dataclass(frozen=True)
class MLShadowComparison:
    dataset_id: str
    total_rows: int
    accepted_rows: int
    future_blocked_rows: int
    immature_label_rows: int
    status: str
    shadow_only: bool = True
    production_action_allowed: bool = False
    excluded_rows: int = 0
    missing_feature_rows: int = 0
    prediction_count: int = 0


class MLRehearsalComparisonService:
    """彙整既有因果邊界結果，不訓練模型也不持久化資料。"""

    def compare(
        self,
        manifest: _DatasetManifest,
        boundary_report: _BoundaryFilterReport,
        predictions: Iterable[_ShadowPredictionRecord],
    ) -> MLShadowComparison:
        _require_shadow_manifest(manifest)
        prediction_records = tuple(predictions)
        _require_dataset_predictions(manifest.dataset_id, prediction_records)

        diagnostics = boundary_report.diagnostics_by_row
        future_blocked_rows = sum(
            any(item.startswith("future_feature:") for item in row_diagnostics)
            for _, row_diagnostics in diagnostics
        )
        immature_label_rows = sum(
            "label_not_mature" in row_diagnostics
            for _, row_diagnostics in diagnostics
        )
        missing_feature_rows = sum(
            any(feature.value is None for feature in row.features)
            for row in boundary_report.accepted_rows
        )
        accepted_rows = len(boundary_report.accepted_rows)
        return MLShadowComparison(
            dataset_id=manifest.dataset_id,
            total_rows=manifest.row_count,
            accepted_rows=accepted_rows,
            future_blocked_rows=future_blocked_rows,
            immature_label_rows=immature_label_rows,
            excluded_rows=len(boundary_report.rejected_row_ids),
            missing_feature_rows=missing_feature_rows,
            prediction_count=len(prediction_records),
            status=(
                "insufficient_sample"
                if accepted_rows < _MINIMUM_SHADOW_SAMPLE_COUNT
                else "shadow_ready"
            ),
        )


def _require_shadow_manifest(manifest: _DatasetManifest) -> None:
    if not manifest.frozen or not manifest.shadow_only or manifest.production_eligible:
        raise ValueError("manifest must remain frozen and shadow-only")


def _require_dataset_predictions(
    dataset_id: str, predictions: tuple[_ShadowPredictionRecord, ...]
) -> None:
    for prediction in predictions:
        if prediction.dataset_id != dataset_id:
            raise ValueError("prediction dataset_id must match the manifest")
        if not prediction.shadow_only or prediction.production_action_allowed:
            raise ValueError("prediction must remain shadow-only")
