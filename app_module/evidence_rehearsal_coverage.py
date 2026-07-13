from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from app_module.evidence_rehearsal_dtos import CoverageMetric


@dataclass(frozen=True)
class CoverageObservation:
    row_id: str
    source_id: str
    source_version: str
    decision_date: str
    available_date: str | None
    quality: str
    feature_present: bool
    label_maturity_date: str | None


class EvidenceRehearsalCoverageProjector:
    def project(
        self,
        rows: Iterable[CoverageObservation],
        *,
        decision_date: str,
    ) -> tuple[CoverageMetric, ...]:
        projection_date = _parse_date(decision_date, "decision_date")
        cohorts_by_source: dict[str, dict[str, int]] = {}
        for row in rows:
            cohort = _cohort_for(row, projection_date)
            counts = cohorts_by_source.setdefault(row.source_id, _empty_counts())
            counts[cohort] += 1

        return tuple(
            _coverage_metric(source_id, counts)
            for source_id, counts in sorted(cohorts_by_source.items())
        )


def _cohort_for(row: CoverageObservation, projection_date: date) -> str:
    _parse_date(row.decision_date, "row.decision_date")
    if not row.feature_present or row.label_maturity_date is None or row.available_date is None:
        return "missing"

    available_date = _parse_date(row.available_date, "available_date")
    if available_date > projection_date:
        return "future_blocked"

    label_maturity_date = _parse_date(row.label_maturity_date, "label_maturity_date")
    if label_maturity_date > projection_date:
        return "immature_label"
    if row.quality != "complete":
        return "degraded"
    return "observed"


def _coverage_metric(source_id: str, counts: dict[str, int]) -> CoverageMetric:
    total_count = sum(counts.values())
    observed_count = counts["observed"]
    coverage_bp = observed_count * 10_000 // total_count
    return CoverageMetric(
        source_id=source_id,
        total_count=total_count,
        observed_count=observed_count,
        degraded_count=counts["degraded"],
        missing_count=counts["missing"],
        future_blocked_count=counts["future_blocked"],
        immature_label_count=counts["immature_label"],
        coverage_bp=coverage_bp,
    )


def _empty_counts() -> dict[str, int]:
    return {
        "observed": 0,
        "degraded": 0,
        "missing": 0,
        "future_blocked": 0,
        "immature_label": 0,
    }


def _parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an ISO date") from error
