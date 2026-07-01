from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


READINESS_NOT_READY = "not_ready"
READINESS_DRY_RUN_ONLY = "dry_run_only"
READINESS_READY_FOR_DESIGN = "ready_for_design"
READINESS_READY_FOR_MANUAL_CONFIRM = "ready_for_manual_confirm"
READINESS_VALUES = (
    READINESS_NOT_READY,
    READINESS_DRY_RUN_ONLY,
    READINESS_READY_FOR_DESIGN,
    READINESS_READY_FOR_MANUAL_CONFIRM,
)

STEP_READY = "ready"
STEP_SKIPPED = "skipped"
STEP_DEGRADED = "degraded"
STEP_FAILED = "failed"


def scheduler_readiness_after_run(
    readiness_before: str,
    *,
    dry_run: bool,
    blocking_gaps: tuple[str, ...],
    errors_count: int,
) -> str:
    if errors_count > 0:
        return READINESS_NOT_READY
    if blocking_gaps:
        if readiness_before in READINESS_VALUES:
            return readiness_before
        return READINESS_NOT_READY
    return READINESS_READY_FOR_MANUAL_CONFIRM


@dataclass(frozen=True)
class EvidencePipelineDiagnostic:
    code: str
    message: str = ""
    severity: str = "warning"
    step_name: str = ""
    source_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "step_name": self.step_name,
            "source_name": self.source_name,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidencePipelineRunRequest:
    decision_date: str
    start_date: str | None = None
    end_date: str | None = None
    db_path: str | None = None
    sources: tuple[str, ...] = ("all",)
    result_id: str | None = None
    symbol: str | None = None
    windows: tuple[int, ...] = (5, 10, 20, 60)
    group_by: str = "event_type"
    window: int = 20
    min_sample_size: int = 10
    limit: int | None = None
    dry_run: bool = True
    confirm: bool = False
    skip_snapshot: bool = False
    skip_capture: bool = False
    skip_outcomes: bool = False
    skip_summary: bool = False
    report_output: str | None = None
    allow_production_db_confirm: bool = False


@dataclass(frozen=True)
class EvidencePipelineStepSummary:
    step_name: str
    status: str
    dry_run: bool
    records_seen: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    warnings_count: int = 0
    errors_count: int = 0
    diagnostics: tuple[EvidencePipelineDiagnostic, ...] = ()
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "status": self.status,
            "dry_run": self.dry_run,
            "records_seen": self.records_seen,
            "records_created": self.records_created,
            "records_updated": self.records_updated,
            "records_skipped": self.records_skipped,
            "warnings_count": self.warnings_count,
            "errors_count": self.errors_count,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class EvidencePipelineRunSummary:
    run_id: str
    decision_date: str
    start_date: str | None
    end_date: str | None
    dry_run: bool
    confirm: bool
    db_path: str | None
    started_at: str
    finished_at: str
    overall_status: str
    scheduler_readiness_before: str
    scheduler_readiness_after: str
    source_coverage: dict[str, Any]
    steps: tuple[EvidencePipelineStepSummary, ...]
    events_seen: int = 0
    events_inserted: int = 0
    events_skipped_duplicate: int = 0
    outcomes_attempted: int = 0
    outcomes_created: int = 0
    outcomes_updated: int = 0
    outcomes_pending: int = 0
    summary_groups: int = 0
    groups_ready: int = 0
    groups_insufficient_sample: int = 0
    groups_degraded: int = 0
    warnings_count: int = 0
    errors_count: int = 0
    blocking_gaps: tuple[str, ...] = ()
    next_recommended_action: str = ""
    report_output: str | None = None
    forward_summary: tuple[dict[str, Any], ...] = ()

    @property
    def diagnostic_codes(self) -> tuple[str, ...]:
        codes: list[str] = []
        for step in self.steps:
            codes.extend(item.code for item in step.diagnostics)
        return tuple(codes)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        payload["blocking_gaps"] = list(self.blocking_gaps)
        payload["forward_summary"] = [dict(item) for item in self.forward_summary]
        payload["diagnostic_codes"] = list(self.diagnostic_codes)
        return payload
