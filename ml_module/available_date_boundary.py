"""Causal feature and matured-label boundary for ML training rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable


@dataclass(frozen=True)
class MLFeatureValue:
    feature_id: str
    value: Any
    available_date: str


@dataclass(frozen=True)
class MLLabelValue:
    label_id: str
    value: Any
    available_date: str
    maturity_status: str


@dataclass(frozen=True)
class MLTrainingRow:
    row_id: str
    decision_date: str
    features: tuple[MLFeatureValue, ...]
    label: MLLabelValue


@dataclass(frozen=True)
class MLRowBoundaryResult:
    row_id: str
    accepted: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class MLBoundaryFilterResult:
    accepted_rows: tuple[MLTrainingRow, ...]
    rejected_row_ids: tuple[str, ...]
    diagnostics_by_row: tuple[tuple[str, tuple[str, ...]], ...]


class MLAvailableDateBoundary:
    def validate(self, row: MLTrainingRow, *, training_as_of: str) -> MLRowBoundaryResult:
        diagnostics: list[str] = []
        if _date(row.decision_date) > _date(training_as_of):
            diagnostics.append("decision_after_training_cutoff")
        if not row.features:
            diagnostics.append("missing_features")
        for feature in row.features:
            if _date(feature.available_date) > _date(row.decision_date):
                diagnostics.append(f"future_feature:{feature.feature_id}")
        if row.label.maturity_status != "ready" or row.label.value is None:
            diagnostics.append("label_not_mature")
        if _date(row.label.available_date) > _date(training_as_of):
            diagnostics.append("label_unavailable_at_training_cutoff")
        unique = tuple(sorted(set(diagnostics)))
        return MLRowBoundaryResult(row.row_id, not unique, unique)

    def filter(
        self, rows: Iterable[MLTrainingRow], *, training_as_of: str
    ) -> MLBoundaryFilterResult:
        accepted: list[MLTrainingRow] = []
        rejected: list[str] = []
        diagnostics: list[tuple[str, tuple[str, ...]]] = []
        for row in rows:
            result = self.validate(row, training_as_of=training_as_of)
            if result.accepted:
                accepted.append(row)
            else:
                rejected.append(row.row_id)
                diagnostics.append((row.row_id, result.diagnostics))
        return MLBoundaryFilterResult(tuple(accepted), tuple(rejected), tuple(diagnostics))


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
