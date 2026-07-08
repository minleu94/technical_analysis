"""V3.0 evidence effectiveness read-only DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class V3GapClassification:
    gap_code: str
    severity: str
    classification: str
    source_trace: str | None = None
    closeout_requirement: str = ""
    manual_validation_status: str = "NOT_REQUIRED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_code": self.gap_code,
            "severity": self.severity,
            "classification": self.classification,
            "source_trace": self.source_trace,
            "closeout_requirement": self.closeout_requirement,
            "manual_validation_status": self.manual_validation_status,
        }


@dataclass(frozen=True)
class V3EffectivenessSlice:
    slice_id: str
    event_family: str
    event_type: str
    source_type: str
    dashboard_surface: str
    sample_count: int
    ready_outcome_count: int
    pending_outcome_count: int
    missing_outcome_count: int
    benchmark_coverage_bp: int
    industry_coverage_bp: int
    sample_sufficiency_label: str
    confidence_label: str
    quality: str
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    gap_classifications: tuple[V3GapClassification, ...] = ()
    decision_date_range: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "event_family": self.event_family,
            "event_type": self.event_type,
            "source_type": self.source_type,
            "dashboard_surface": self.dashboard_surface,
            "decision_date_range": self.decision_date_range,
            "sample_count": self.sample_count,
            "ready_outcome_count": self.ready_outcome_count,
            "pending_outcome_count": self.pending_outcome_count,
            "missing_outcome_count": self.missing_outcome_count,
            "benchmark_coverage_bp": self.benchmark_coverage_bp,
            "industry_coverage_bp": self.industry_coverage_bp,
            "sample_sufficiency_label": self.sample_sufficiency_label,
            "confidence_label": self.confidence_label,
            "quality": self.quality,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
            "gap_classifications": [
                gap.to_dict() for gap in self.gap_classifications
            ],
        }


@dataclass(frozen=True)
class V3EffectivenessReport:
    active_milestone: str
    slices: tuple[V3EffectivenessSlice, ...]
    access_boundary: Mapping[str, bool | str]
    manual_validation_status: str = "PENDING_MANUAL_VALIDATION"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_milestone": self.active_milestone,
            "manual_validation_status": self.manual_validation_status,
            "access_boundary": dict(self.access_boundary),
            "warnings": list(self.warnings),
            "slices": [item.to_dict() for item in self.slices],
        }
