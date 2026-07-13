"""Evidence rehearsal 的唯讀 ML shadow 比較摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Protocol


_MINIMUM_SHADOW_SAMPLE_COUNT = 20


class _FeatureValue(Protocol):
    feature_id: str
    value: object
    available_date: str


class _LabelValue(Protocol):
    value: object
    available_date: str
    maturity_status: str


class _TrainingRow(Protocol):
    row_id: str
    decision_date: str
    features: tuple[_FeatureValue, ...]
    label: _LabelValue


class _BoundaryFilterReport(Protocol):
    accepted_rows: tuple[_TrainingRow, ...]
    rejected_row_ids: tuple[str, ...]
    diagnostics_by_row: tuple[tuple[str, tuple[str, ...]], ...]


class _DatasetManifest(Protocol):
    dataset_id: str
    created_at: str
    row_count: int
    frozen: bool
    shadow_only: bool
    production_eligible: bool


class _ShadowPredictionRecord(Protocol):
    dataset_id: str
    shadow_only: bool
    production_action_allowed: bool


class _PurgedFold(Protocol):
    fold_id: str


class _CalibrationResult(Protocol):
    calibration_id: str
    sample_count: int
    fold_count: int
    shadow_only: bool
    production_eligible: bool


class _DriftResult(Protocol):
    feature_id: str
    status: str
    retrain_automatically: bool


class _ChampionComparisonResult(Protocol):
    sample_count: int
    review_status: str
    auto_promotion_allowed: bool


@dataclass(frozen=True)
class MLShadowDiagnosticsInput:
    """既有 ML 結果的唯讀投影輸入，不觸發任何重新計算。"""

    purged_folds: tuple[_PurgedFold, ...] = ()
    calibration: _CalibrationResult | None = None
    drift_results: tuple[_DriftResult, ...] = ()
    champion_comparison: _ChampionComparisonResult | None = None
    training_as_of: str | None = None


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
    mature_label_rows: int = 0
    purged_fold_ids: tuple[str, ...] = ()
    calibration_status: str = "not_provided"
    calibration_sample_count: int = 0
    calibration_fold_count: int = 0
    drift_statuses: tuple[tuple[str, str], ...] = ()
    rule_vs_challenger_status: str = "not_provided"
    rule_vs_challenger_sample_count: int = 0
    boundary_issues: tuple[str, ...] = ()
    validation_context_status: str = "not_provided"


@dataclass(frozen=True)
class _BoundaryProjection:
    future_blocked_rows: int
    immature_label_rows: int
    mature_label_rows: int
    missing_feature_rows: int
    issues: tuple[str, ...]
    validation_context_status: str


class MLRehearsalComparisonService:
    """彙整既有因果邊界結果，不訓練模型也不持久化資料。"""

    def compare(
        self,
        manifest: _DatasetManifest,
        boundary_report: _BoundaryFilterReport,
        predictions: Iterable[_ShadowPredictionRecord],
        *,
        diagnostics: MLShadowDiagnosticsInput | None = None,
    ) -> MLShadowComparison:
        _require_shadow_manifest(manifest)
        prediction_records = tuple(predictions)
        _require_dataset_predictions(manifest.dataset_id, prediction_records)
        diagnostic_projection = _project_diagnostics(diagnostics)
        boundary = _project_boundary(
            manifest,
            boundary_report,
            diagnostic_projection.training_as_of,
            diagnostic_projection.validation_context_status,
        )
        accepted_rows = len(boundary_report.accepted_rows)
        status = (
            "boundary_inconsistent"
            if boundary.issues
            else "insufficient_sample"
            if accepted_rows < _MINIMUM_SHADOW_SAMPLE_COUNT
            else "training_context_required"
            if boundary.validation_context_status == "not_provided"
            else "shadow_ready"
        )
        return MLShadowComparison(
            dataset_id=manifest.dataset_id,
            total_rows=manifest.row_count,
            accepted_rows=accepted_rows,
            future_blocked_rows=boundary.future_blocked_rows,
            immature_label_rows=boundary.immature_label_rows,
            excluded_rows=len(boundary_report.rejected_row_ids),
            missing_feature_rows=boundary.missing_feature_rows,
            prediction_count=len(prediction_records),
            mature_label_rows=boundary.mature_label_rows,
            purged_fold_ids=diagnostic_projection.purged_fold_ids,
            calibration_status=diagnostic_projection.calibration_status,
            calibration_sample_count=diagnostic_projection.calibration_sample_count,
            calibration_fold_count=diagnostic_projection.calibration_fold_count,
            drift_statuses=diagnostic_projection.drift_statuses,
            rule_vs_challenger_status=diagnostic_projection.rule_vs_challenger_status,
            rule_vs_challenger_sample_count=diagnostic_projection.rule_vs_challenger_sample_count,
            boundary_issues=boundary.issues,
            validation_context_status=boundary.validation_context_status,
            status=status,
        )


@dataclass(frozen=True)
class _DiagnosticProjection:
    purged_fold_ids: tuple[str, ...]
    calibration_status: str
    calibration_sample_count: int
    calibration_fold_count: int
    drift_statuses: tuple[tuple[str, str], ...]
    rule_vs_challenger_status: str
    rule_vs_challenger_sample_count: int
    training_as_of: date | None
    validation_context_status: str


def _project_boundary(
    manifest: _DatasetManifest,
    boundary_report: _BoundaryFilterReport,
    training_as_of: date | None,
    validation_context_status: str,
) -> _BoundaryProjection:
    accepted_rows = boundary_report.accepted_rows
    rejected_row_ids = boundary_report.rejected_row_ids
    diagnostics_by_row = boundary_report.diagnostics_by_row
    issues: list[str] = []
    if manifest.row_count != len(accepted_rows) + len(rejected_row_ids):
        issues.append("manifest_row_count_mismatch")
    for row_id in _duplicate_ids(
        tuple(row.row_id for row in accepted_rows) + rejected_row_ids
    ):
        issues.append(f"row_id_not_unique:{row_id}")
    diagnostic_ids = tuple(row_id for row_id, _ in diagnostics_by_row)
    if (
        len(diagnostic_ids) != len(set(diagnostic_ids))
        or set(diagnostic_ids) != set(rejected_row_ids)
    ):
        issues.append("diagnostic_rejected_row_mismatch")

    future_row_ids = {
        row_id
        for row_id, row_diagnostics in diagnostics_by_row
        if any(item.startswith("future_feature:") for item in row_diagnostics)
    }
    immature_row_ids = {
        row_id
        for row_id, row_diagnostics in diagnostics_by_row
        if (
            "label_not_mature" in row_diagnostics
            or "label_unavailable_at_training_cutoff" in row_diagnostics
        )
    }
    mature_label_rows = 0
    missing_feature_rows = 0
    manifest_created_date = _parse_date(manifest.created_at)
    if manifest_created_date is None:
        issues.append("invalid_manifest_created_at")
    for row in accepted_rows:
        row_issues, has_future_feature, label_is_mature, has_missing_feature = _validate_accepted_row(
            row, manifest_created_date, training_as_of
        )
        issues.extend(row_issues)
        if has_future_feature:
            future_row_ids.add(row.row_id)
        if not label_is_mature:
            immature_row_ids.add(row.row_id)
        else:
            mature_label_rows += 1
        if has_missing_feature:
            missing_feature_rows += 1
    return _BoundaryProjection(
        future_blocked_rows=len(future_row_ids),
        immature_label_rows=len(immature_row_ids),
        mature_label_rows=mature_label_rows,
        missing_feature_rows=missing_feature_rows,
        issues=tuple(sorted(set(issues))),
        validation_context_status=validation_context_status,
    )


def _validate_accepted_row(
    row: _TrainingRow,
    manifest_created_date: date | None,
    training_as_of: date | None,
) -> tuple[tuple[str, ...], bool, bool, bool]:
    issues: list[str] = []
    decision_date = _parse_date(row.decision_date)
    if decision_date is None:
        issues.append(f"invalid_decision_date:{row.row_id}")
    elif manifest_created_date is not None and decision_date > manifest_created_date:
        issues.append(f"accepted_decision_after_manifest:{row.row_id}")
    has_future_feature = False
    if not row.features:
        issues.append(f"accepted_missing_features:{row.row_id}")
    for feature in row.features:
        feature_date = _parse_date(feature.available_date)
        if feature_date is None:
            issues.append(f"invalid_feature_available_date:{row.row_id}:{feature.feature_id}")
        elif decision_date is not None and feature_date > decision_date:
            has_future_feature = True
            issues.append(f"accepted_future_feature:{row.row_id}:{feature.feature_id}")
    label_is_mature = row.label.maturity_status == "ready" and row.label.value is not None
    if not label_is_mature:
        issues.append(f"accepted_label_not_mature:{row.row_id}")
    label_date = _parse_date(row.label.available_date)
    if label_date is None:
        label_is_mature = False
        issues.append(f"invalid_label_available_date:{row.row_id}")
    elif manifest_created_date is not None and label_date > manifest_created_date:
        label_is_mature = False
        issues.append(f"accepted_future_label:{row.row_id}")
    elif training_as_of is not None and label_date > training_as_of:
        label_is_mature = False
        issues.append(f"accepted_future_label:{row.row_id}")
    return tuple(issues), has_future_feature, label_is_mature, any(
        feature.value is None for feature in row.features
    )


def _project_diagnostics(
    diagnostics: MLShadowDiagnosticsInput | None,
) -> _DiagnosticProjection:
    if diagnostics is None:
        return _DiagnosticProjection(
            (), "not_provided", 0, 0, (), "not_provided", 0, None, "not_provided"
        )
    calibration = diagnostics.calibration
    if calibration is not None and (
        not calibration.shadow_only or calibration.production_eligible
    ):
        raise ValueError("calibration must remain shadow-only")
    champion = diagnostics.champion_comparison
    if champion is not None and champion.auto_promotion_allowed:
        raise ValueError("champion comparison must not allow auto promotion")
    for drift in diagnostics.drift_results:
        if drift.retrain_automatically:
            raise ValueError("drift result must not trigger automatic retraining")
    training_as_of = _parse_date(diagnostics.training_as_of) if diagnostics.training_as_of else None
    validation_context_status = "provided" if training_as_of is not None else "not_provided"
    if diagnostics.training_as_of and training_as_of is None:
        raise ValueError("training_as_of must be an ISO date")
    return _DiagnosticProjection(
        purged_fold_ids=tuple(fold.fold_id for fold in diagnostics.purged_folds),
        calibration_status="provided" if calibration is not None else "not_provided",
        calibration_sample_count=calibration.sample_count if calibration is not None else 0,
        calibration_fold_count=calibration.fold_count if calibration is not None else 0,
        drift_statuses=tuple(
            (drift.feature_id, drift.status) for drift in diagnostics.drift_results
        ),
        rule_vs_challenger_status=(
            champion.review_status if champion is not None else "not_provided"
        ),
        rule_vs_challenger_sample_count=champion.sample_count if champion is not None else 0,
        training_as_of=training_as_of,
        validation_context_status=validation_context_status,
    )


def _duplicate_ids(row_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({row_id for row_id in row_ids if row_ids.count(row_id) > 1}))


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


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
