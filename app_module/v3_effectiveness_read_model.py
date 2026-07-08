"""Read-only V3.0 effectiveness projection."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from app_module.v3_effectiveness_dtos import (
    V3EffectivenessReport,
    V3EffectivenessSlice,
)
from app_module.v3_gap_classifier import classify_v3_gap


MAJOR_WARNING_CODES = {
    "source_missing_screening_matrix",
    "forward_outcome_missing",
    "missing_industry_benchmark",
}


class V3EffectivenessReadModel:
    """Builds deterministic disclosure DTOs from already-saved evidence rows."""

    def __init__(self, *, min_sample_size: int = 30) -> None:
        if min_sample_size <= 0:
            raise ValueError("min_sample_size must be positive")
        self._min_sample_size = min_sample_size

    def build_report(
        self, *, rows: Iterable[Mapping[str, Any]]
    ) -> V3EffectivenessReport:
        grouped: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "ready_outcome_count": 0,
                "pending_outcome_count": 0,
                "missing_outcome_count": 0,
                "benchmark_coverage_bp": 0,
                "industry_coverage_bp": 0,
                "warnings": set(),
                "source_traces": set(),
                "dashboard_surface": "evidence_review",
                "decision_date_range": None,
            }
        )
        for row in rows:
            event_family = str(row.get("event_family", "unknown"))
            event_type = str(row.get("event_type", event_family))
            source_type = str(row.get("source_type", "unknown"))
            key = (event_family, event_type, source_type)
            bucket = grouped[key]
            bucket["ready_outcome_count"] += int(row.get("ready_outcome_count", 0))
            bucket["pending_outcome_count"] += int(
                row.get("pending_outcome_count", 0)
            )
            bucket["missing_outcome_count"] += int(
                row.get("missing_outcome_count", 0)
            )
            bucket["benchmark_coverage_bp"] = max(
                int(bucket["benchmark_coverage_bp"]),
                int(row.get("benchmark_coverage_bp", 0)),
            )
            bucket["industry_coverage_bp"] = max(
                int(bucket["industry_coverage_bp"]),
                int(row.get("industry_coverage_bp", 0)),
            )
            bucket["dashboard_surface"] = str(
                row.get("dashboard_surface", bucket["dashboard_surface"])
            )
            bucket["decision_date_range"] = row.get(
                "decision_date_range", bucket["decision_date_range"]
            )
            for warning in row.get("warnings", ()):
                bucket["warnings"].add(str(warning))
            if row.get("source_trace"):
                bucket["source_traces"].add(str(row["source_trace"]))

        slices = tuple(
            self._build_slice(key, bucket)
            for key, bucket in sorted(grouped.items(), key=lambda item: item[0])
        )
        report_warnings = tuple(
            sorted({warning for item in slices for warning in item.warnings})
        )
        return V3EffectivenessReport(
            active_milestone="V3.0 engineering candidate",
            slices=slices,
            access_boundary={
                "mode": "read_only",
                "writes_allowed": False,
                "production_scheduler_allowed": False,
                "auto_trading": False,
                "scheduler_write_mode": False,
            },
            manual_validation_status="PENDING_MANUAL_VALIDATION",
            warnings=report_warnings,
        )

    def _build_slice(
        self, key: tuple[str, str, str], bucket: Mapping[str, Any]
    ) -> V3EffectivenessSlice:
        event_family, event_type, source_type = key
        ready = int(bucket["ready_outcome_count"])
        pending = int(bucket["pending_outcome_count"])
        missing = int(bucket["missing_outcome_count"])
        sample_count = ready + pending + missing
        warnings = tuple(sorted(bucket["warnings"]))
        sample_label = self._sample_sufficiency_label(sample_count, warnings)
        confidence_label = self._confidence_label(
            sample_label=sample_label,
            ready_outcome_count=ready,
            benchmark_coverage_bp=int(bucket["benchmark_coverage_bp"]),
            warnings=warnings,
        )
        quality = "OBSERVED"
        if missing > 0 or warnings:
            quality = "DEGRADED"
        if sample_count == 0:
            quality = "MISSING"
        source_trace = ";".join(sorted(bucket["source_traces"])) or None
        gap_classifications = tuple(
            classify_v3_gap(warning, source_trace=source_trace)
            for warning in warnings
        )
        limitations = (
            "不是交易建議",
            "不宣稱投資有效性",
            "不啟用 production scheduler",
        )
        return V3EffectivenessSlice(
            slice_id=f"{event_family}:{event_type}:{source_type}",
            event_family=event_family,
            event_type=event_type,
            source_type=source_type,
            dashboard_surface=str(bucket["dashboard_surface"]),
            decision_date_range=bucket["decision_date_range"],
            sample_count=sample_count,
            ready_outcome_count=ready,
            pending_outcome_count=pending,
            missing_outcome_count=missing,
            benchmark_coverage_bp=int(bucket["benchmark_coverage_bp"]),
            industry_coverage_bp=int(bucket["industry_coverage_bp"]),
            sample_sufficiency_label=sample_label,
            confidence_label=confidence_label,
            quality=quality,
            warnings=warnings,
            limitations=limitations,
            gap_classifications=gap_classifications,
        )

    def _sample_sufficiency_label(
        self, sample_count: int, warnings: tuple[str, ...]
    ) -> str:
        if sample_count < self._min_sample_size:
            return "insufficient_sample"
        if "manual_validation_missing" in warnings:
            return "needs_manual_validation"
        if any(warning in MAJOR_WARNING_CODES for warning in warnings):
            return "directional_only"
        return "review_ready"

    def _confidence_label(
        self,
        *,
        sample_label: str,
        ready_outcome_count: int,
        benchmark_coverage_bp: int,
        warnings: tuple[str, ...],
    ) -> str:
        if sample_label == "insufficient_sample":
            return "none"
        if sample_label == "needs_manual_validation":
            return "needs_manual_validation"
        if sample_label == "directional_only":
            return "low"
        if ready_outcome_count >= self._min_sample_size * 2 and benchmark_coverage_bp >= 8000 and not warnings:
            return "medium"
        return "low"


def sample_v3_effectiveness_rows() -> tuple[dict[str, Any], ...]:
    return (
        {
            "event_family": "recommendation",
            "event_type": "recommendation_included",
            "source_type": "persisted_recommendation",
            "ready_outcome_count": 18,
            "pending_outcome_count": 4,
            "missing_outcome_count": 0,
            "benchmark_coverage_bp": 10000,
            "industry_coverage_bp": 500,
            "warnings": ("sample_below_minimum", "manual_validation_missing"),
            "source_trace": "sample:persisted_recommendation",
        },
        {
            "event_family": "portfolio_alert",
            "event_type": "portfolio_alert_triggered",
            "source_type": "daily_decision_snapshot",
            "ready_outcome_count": 80,
            "pending_outcome_count": 0,
            "missing_outcome_count": 0,
            "benchmark_coverage_bp": 10000,
            "industry_coverage_bp": 3500,
            "warnings": (),
            "source_trace": "sample:daily_decision_snapshot",
        },
        {
            "event_family": "screening_matrix",
            "event_type": "source_missing_screening_matrix",
            "source_type": "negative_evidence",
            "ready_outcome_count": 118,
            "pending_outcome_count": 0,
            "missing_outcome_count": 0,
            "benchmark_coverage_bp": 10000,
            "industry_coverage_bp": 0,
            "warnings": (
                "source_missing_screening_matrix",
                "missing_industry_benchmark",
            ),
            "source_trace": "sample:historical_replay_reference_fix",
        },
    )
