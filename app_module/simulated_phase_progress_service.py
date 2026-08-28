from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from app_module.pre_v2_readiness_service import PreV2ReadinessService


SIMULATED_READY = "simulated_ready"
SIMULATED_DEGRADED = "simulated_degraded"
SIMULATED_BLOCKED = "simulated_blocked"
OFFICIAL_GATE_NOT_SATISFIED = "official_gate_not_satisfied"
MANUAL_VALIDATION_REQUIRED = "manual_validation_required"


@dataclass(frozen=True)
class ReplayEvidenceTagSummary:
    replay_mode: str
    source_label: str
    replay_run_id: str | None
    replay_decision_dates: tuple[str, ...]
    replay_data_as_of_dates: tuple[str, ...]
    data_as_of_dates: tuple[str, ...] = ()
    phase_simulation_scope: tuple[str, ...] = (
        "phase_0",
        "phase_1",
        "phase_2",
        "phase_3",
        "phase_4",
        "phase_5",
    )
    official_gate_credit: bool = False
    requires_real_world_validation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "replay_mode": self.replay_mode,
            "source_label": self.source_label,
            "replay_run_id": self.replay_run_id,
            "replay_decision_dates": list(self.replay_decision_dates),
            "replay_data_as_of_dates": list(self.replay_data_as_of_dates),
            "data_as_of_dates": list(self.data_as_of_dates),
            "phase_simulation_scope": list(self.phase_simulation_scope),
            "official_gate_credit": self.official_gate_credit,
            "requires_real_world_validation": self.requires_real_world_validation,
        }


@dataclass(frozen=True)
class SimulatedPhaseProgressItem:
    phase_id: str
    label: str
    simulated_status: str
    official_status: str
    source_trace: tuple[str, ...]
    replay_tags: dict[str, Any]
    official_gate_credit: bool = False
    real_world_validation_required: bool = True
    next_real_world_steps: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "label": self.label,
            "simulated_status": self.simulated_status,
            "official_status": self.official_status,
            "source_trace": list(self.source_trace),
            "replay_tags": dict(self.replay_tags),
            "official_gate_credit": self.official_gate_credit,
            "real_world_validation_required": self.real_world_validation_required,
            "next_real_world_steps": list(self.next_real_world_steps),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class RealWorldValidationPlan:
    phase_0_steps: tuple[str, ...]
    multi_day_dry_run_steps: tuple[str, ...]
    phase_3_4_steps: tuple[str, ...]
    phase_5_steps: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_0_steps": list(self.phase_0_steps),
            "multi_day_dry_run_steps": list(self.multi_day_dry_run_steps),
            "phase_3_4_steps": list(self.phase_3_4_steps),
            "phase_5_steps": list(self.phase_5_steps),
        }


@dataclass(frozen=True)
class SimulatedPhaseProgressReport:
    generated_at: str
    decision_date: str | None
    simulated_overall_status: str
    official_phase_5_status: str
    production_scheduler_allowed: bool
    replay_tags: ReplayEvidenceTagSummary
    official_gate_summary: dict[str, Any]
    replay_summary: dict[str, Any]
    scheduled_dry_run_summary: dict[str, Any]
    items: tuple[SimulatedPhaseProgressItem, ...]
    real_world_validation_plan: RealWorldValidationPlan
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "decision_date": self.decision_date,
            "simulated_overall_status": self.simulated_overall_status,
            "official_phase_5_status": self.official_phase_5_status,
            "production_scheduler_allowed": self.production_scheduler_allowed,
            "replay_tags": self.replay_tags.to_dict(),
            "official_gate_summary": dict(self.official_gate_summary),
            "replay_summary": dict(self.replay_summary),
            "scheduled_dry_run_summary": dict(self.scheduled_dry_run_summary),
            "items": [item.to_dict() for item in self.items],
            "real_world_validation_plan": self.real_world_validation_plan.to_dict(),
            "limitations": list(self.limitations),
        }


class SimulatedPhaseProgressService:
    """Read-only simulated Phase 0-5 progress inspector."""

    def __init__(
        self,
        config: Any,
        *,
        evidence_db_path: str | Path | None = None,
        research_db_path: str | Path | None = None,
        approved_weekly_history_projection_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.evidence_db_path = Path(evidence_db_path) if evidence_db_path is not None else Path(config.db_file)
        self.research_db_path = (
            Path(research_db_path) if research_db_path is not None else Path(config.research_run_db_file)
        )
        self.approved_weekly_history_projection_path = (
            approved_weekly_history_projection_path
            if approved_weekly_history_projection_path is not None
            else os.environ.get("WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH")
        )

    def build_report(
        self,
        *,
        decision_date: str | None = None,
        replay_summary_path: str | Path | None = None,
        scheduled_output_root: str | Path | None = None,
        multi_day_record_path: str | Path | None = None,
        min_weekly_records: int = 3,
        min_dry_run_days: int = 3,
    ) -> SimulatedPhaseProgressReport:
        replay_payload = _load_json(Path(replay_summary_path)) if replay_summary_path else {}
        scheduled_root = (
            Path(scheduled_output_root)
            if scheduled_output_root is not None
            else Path(self.config.output_root) / "scheduled" / "evidence_pipeline_dry_run"
        )
        scheduled_payload = _load_json(scheduled_root / "latest_status.json")
        pre_v2_report = PreV2ReadinessService(
            self.config,
            evidence_db_path=self.evidence_db_path,
            research_db_path=self.research_db_path,
            approved_weekly_history_projection_path=self.approved_weekly_history_projection_path,
        ).inspect(
            decision_date=decision_date,
            multi_day_record_path=multi_day_record_path,
            min_weekly_records=min_weekly_records,
            min_dry_run_days=min_dry_run_days,
        )

        replay_summary = _summarize_replay(replay_payload, replay_summary_path)
        scheduled_summary = _summarize_scheduled_status(scheduled_payload, scheduled_root)
        replay_tags = _replay_tags(replay_payload)
        official_summary = _official_gate_summary(pre_v2_report)
        items = _phase_items(
            replay_summary=replay_summary,
            scheduled_summary=scheduled_summary,
            official_gate_summary=official_summary,
            replay_tags=replay_tags,
        )
        return SimulatedPhaseProgressReport(
            generated_at=_utc_now_text(),
            decision_date=decision_date,
            simulated_overall_status=_overall_simulated_status(items),
            official_phase_5_status="blocked",
            production_scheduler_allowed=False,
            replay_tags=replay_tags,
            official_gate_summary=official_summary,
            replay_summary=replay_summary,
            scheduled_dry_run_summary=scheduled_summary,
            items=items,
            real_world_validation_plan=_real_world_validation_plan(),
            limitations=(
                "Simulated progress is read-only rehearsal evidence and does not change official gates.",
                "Historical replay and scheduled dry-run reports do not count as weekly history or multi-day manual review records.",
                "Production scheduler remains disabled until real weekly, multi-day, backup, rollback, and explicit approval gates are satisfied.",
            ),
        )


def render_simulated_phase_progress_markdown(report: SimulatedPhaseProgressReport) -> str:
    lines = [
        "# V2.2 Simulated Phase Progress",
        "",
        f"- generated_at: `{report.generated_at}`",
        f"- decision_date: `{report.decision_date or ''}`",
        f"- simulated_overall_status: `{report.simulated_overall_status}`",
        f"- official_phase_5_status: `{report.official_phase_5_status}`",
        f"- production_scheduler_allowed: `{str(report.production_scheduler_allowed).lower()}`",
        f"- official_gate_credit: `{str(report.replay_tags.official_gate_credit).lower()}`",
        f"- requires_real_world_validation: `{str(report.replay_tags.requires_real_world_validation).lower()}`",
        "",
        "## Replay Labels",
        "",
        f"- replay_mode: `{report.replay_tags.replay_mode}`",
        f"- source_label: `{report.replay_tags.source_label}`",
        f"- replay_run_id: `{report.replay_tags.replay_run_id or ''}`",
        f"- replay_decision_dates: `{', '.join(report.replay_tags.replay_decision_dates)}`",
        f"- replay_data_as_of_dates: `{', '.join(report.replay_tags.replay_data_as_of_dates)}`",
        "",
        "## Phase Summary",
        "",
        "| Phase | Simulated status | Official status | Next real-world steps |",
        "|---|---|---|---|",
    ]
    for item in report.items:
        steps = "; ".join(item.next_real_world_steps)
        lines.append(f"| {item.phase_id} | `{item.simulated_status}` | `{item.official_status}` | {steps} |")

    plan = report.real_world_validation_plan
    lines.extend(
        [
            "",
            "## True-Data Validation Checklist",
            "",
            "### Phase 0",
            *[f"- {step}" for step in plan.phase_0_steps],
            "",
            "### Multi-day Dry-run",
            *[f"- {step}" for step in plan.multi_day_dry_run_steps],
            "",
            "### Phase 3 / 4",
            *[f"- {step}" for step in plan.phase_3_4_steps],
            "",
            "### Phase 5",
            *[f"- {step}" for step in plan.phase_5_steps],
            "",
            "## Boundary",
            "",
            "- This report is a simulated rehearsal only.",
            "- Official lifecycle state is unchanged.",
            "- Scheduler write mode is not enabled.",
        ]
    )
    return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _summarize_replay(payload: dict[str, Any], path: str | Path | None) -> dict[str, Any]:
    days = payload.get("days")
    day_payloads = [day for day in days if isinstance(day, dict)] if isinstance(days, list) else []
    totals_raw = payload.get("totals")
    totals: dict[str, Any] = totals_raw if isinstance(totals_raw, dict) else {}
    final_outcome_raw = payload.get("final_outcome_summary")
    final_outcome: dict[str, Any] = final_outcome_raw if isinstance(final_outcome_raw, dict) else {}
    blocking_gaps = sorted(
        {
            str(gap)
            for day in day_payloads
            for gap in (day.get("blocking_gaps") or [])
            if str(gap).strip()
        }
    )
    diagnostics = sorted(
        {
            str(code)
            for day in day_payloads
            for code in (day.get("diagnostics") or [])
            if str(code).strip()
        }
    )
    return {
        "summary_path": str(path) if path is not None else None,
        "available": bool(payload),
        "replay_run_id": payload.get("replay_run_id"),
        "replay_mode": payload.get("replay_mode"),
        "source_label": payload.get("source_label"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "dry_run": bool(payload.get("dry_run")) if payload else None,
        "confirm": bool(payload.get("confirm")) if payload else None,
        "days": int(totals.get("days") or len(day_payloads)),
        "events_seen": int(totals.get("events_seen") or sum(int(day.get("events_seen") or 0) for day in day_payloads)),
        "events_inserted": int(
            totals.get("events_inserted") or sum(int(day.get("events_inserted") or 0) for day in day_payloads)
        ),
        "outcomes_created": int(
            totals.get("outcomes_created")
            or final_outcome.get("outcomes_created")
            or sum(int(day.get("outcomes_created") or 0) for day in day_payloads)
        ),
        "outcomes_pending": int(
            totals.get("outcomes_pending")
            or final_outcome.get("pending_insufficient_future_data")
            or sum(int(day.get("outcomes_pending") or 0) for day in day_payloads)
        ),
        "blocking_gaps": blocking_gaps,
        "diagnostics": diagnostics,
    }


def _summarize_scheduled_status(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    return {
        "status_path": str(root / "latest_status.json"),
        "available": bool(payload),
        "scheduled_task_observed": bool(payload),
        "task": payload.get("task"),
        "status": payload.get("status"),
        "decision_date": payload.get("decision_date"),
        "dry_run": bool(payload.get("dry_run")) if payload else None,
        "confirm": False if payload else None,
        "writes_evidence_db": bool(payload.get("writes_evidence_db")) if payload else None,
        "manual_record_credit": False if payload else None,
        "pipeline_summary_available": bool(payload.get("pipeline_summary_available")),
        "pipeline_warnings_count": int(payload.get("pipeline_warnings_count") or 0),
        "pipeline_errors_count": int(payload.get("pipeline_errors_count") or 0),
        "pipeline_blocking_gaps": list(payload.get("pipeline_blocking_gaps") or []),
        "pipeline_diagnostic_codes": list(payload.get("pipeline_diagnostic_codes") or []),
        "scheduler_readiness_after": payload.get("scheduler_readiness_after"),
    }


def _replay_tags(payload: dict[str, Any]) -> ReplayEvidenceTagSummary:
    days = payload.get("days")
    day_payloads = [day for day in days if isinstance(day, dict)] if isinstance(days, list) else []
    decision_dates = tuple(str(day.get("decision_date")) for day in day_payloads if day.get("decision_date"))
    replay_data_as_of = tuple(
        str(day.get("replay_data_as_of_date") or day.get("decision_date"))
        for day in day_payloads
        if day.get("replay_data_as_of_date") or day.get("decision_date")
    )
    final_outcome_raw = payload.get("final_outcome_summary")
    final_outcome: dict[str, Any] = final_outcome_raw if isinstance(final_outcome_raw, dict) else {}
    data_as_of_dates = tuple(
        str(value)
        for value in (final_outcome.get("data_as_of_date"), payload.get("end_date"))
        if value
    )
    return ReplayEvidenceTagSummary(
        replay_mode=str(payload.get("replay_mode") or "historical_replay"),
        source_label=str(payload.get("source_label") or "simulated_scheduler"),
        replay_run_id=str(payload.get("replay_run_id")) if payload.get("replay_run_id") else None,
        replay_decision_dates=decision_dates,
        replay_data_as_of_dates=replay_data_as_of,
        data_as_of_dates=tuple(dict.fromkeys(data_as_of_dates)),
    )


def _official_gate_summary(pre_v2_report: Any) -> dict[str, Any]:
    items = [item.to_dict() for item in pre_v2_report.items]
    return {
        "overall_status": pre_v2_report.overall_status,
        "production_scheduler_allowed": bool(pre_v2_report.production_scheduler_allowed),
        "weekly_history_observed": _observed(items, "weekly_history"),
        "multi_day_dry_run_observed": _observed(items, "multi_day_dry_run"),
        "items": items,
        "limitations": list(pre_v2_report.limitations),
    }


def _observed(items: list[dict[str, Any]], item_id: str) -> int:
    for item in items:
        if item.get("item_id") == item_id:
            return int(item.get("observed_count") or 0)
    return 0


def _phase_items(
    *,
    replay_summary: dict[str, Any],
    scheduled_summary: dict[str, Any],
    official_gate_summary: dict[str, Any],
    replay_tags: ReplayEvidenceTagSummary,
) -> tuple[SimulatedPhaseProgressItem, ...]:
    official_status = (
        MANUAL_VALIDATION_REQUIRED
        if official_gate_summary.get("overall_status") == "ready"
        else OFFICIAL_GATE_NOT_SATISFIED
    )
    replay_available = bool(replay_summary.get("available"))
    scheduled_available = bool(scheduled_summary.get("available"))
    replay_tag_dict = replay_tags.to_dict()
    common_steps = (
        "Use real weekly review history from the working-copy DB.",
        "Use reviewed multi-day dry-run records from real trading days.",
    )
    phase_0_status = SIMULATED_READY if replay_available or scheduled_available else SIMULATED_BLOCKED
    phase_1_status = SIMULATED_READY if replay_available else SIMULATED_DEGRADED
    phase_2_status = SIMULATED_READY if scheduled_available else SIMULATED_DEGRADED
    phase_3_status = SIMULATED_READY if replay_available else SIMULATED_DEGRADED
    phase_4_status = SIMULATED_READY if int(replay_summary.get("outcomes_created") or 0) > 0 else SIMULATED_DEGRADED
    phase_5_status = SIMULATED_READY if replay_available and scheduled_available else SIMULATED_BLOCKED
    return (
        SimulatedPhaseProgressItem(
            phase_id="phase_0",
            label="Simulated observability",
            simulated_status=phase_0_status,
            official_status=official_status,
            source_trace=("historical_replay_summary", "scheduled_dry_run_status", "pre_v2_readiness"),
            replay_tags=replay_tag_dict,
            next_real_world_steps=common_steps,
            evidence={
                "replay_days": replay_summary.get("days"),
                "events_seen": replay_summary.get("events_seen"),
                "weekly_history_observed": official_gate_summary.get("weekly_history_observed"),
                "multi_day_dry_run_observed": official_gate_summary.get("multi_day_dry_run_observed"),
            },
        ),
        SimulatedPhaseProgressItem(
            phase_id="phase_1",
            label="Workbench design input",
            simulated_status=phase_1_status,
            official_status=official_status,
            source_trace=("historical_replay_summary",),
            replay_tags=replay_tag_dict,
            next_real_world_steps=("Map real source gaps into Workbench evidence disclosures.",),
            evidence={
                "blocking_gaps": replay_summary.get("blocking_gaps", []),
                "diagnostics": replay_summary.get("diagnostics", []),
            },
        ),
        SimulatedPhaseProgressItem(
            phase_id="phase_2",
            label="Operating loop rehearsal",
            simulated_status=phase_2_status,
            official_status=official_status,
            source_trace=("scheduled_dry_run_status", "pre_v2_readiness"),
            replay_tags=replay_tag_dict,
            next_real_world_steps=("Record human-reviewed daily dry-run notes before counting gate progress.",),
            evidence=scheduled_summary,
        ),
        SimulatedPhaseProgressItem(
            phase_id="phase_3",
            label="Data source candidate dry-run",
            simulated_status=phase_3_status,
            official_status=official_status,
            source_trace=("historical_replay_summary", "scheduled_dry_run_status"),
            replay_tags=replay_tag_dict,
            next_real_world_steps=("Define source_id, available_date, quality, and missing_policy for each candidate source.",),
            evidence={
                "candidate_gap_reasons": _candidate_gap_reasons(replay_summary, scheduled_summary),
            },
        ),
        SimulatedPhaseProgressItem(
            phase_id="phase_4",
            label="Execution realism candidates",
            simulated_status=phase_4_status,
            official_status=official_status,
            source_trace=("historical_replay_summary",),
            replay_tags=replay_tag_dict,
            next_real_world_steps=("Validate execution realism candidates in a research-only sandbox.",),
            evidence={
                "outcomes_created": replay_summary.get("outcomes_created"),
                "outcomes_pending": replay_summary.get("outcomes_pending"),
                "candidate_models": [
                    "bid_ask_spread_assumption",
                    "lot_sizing_residual",
                    "locked_limit_execution",
                    "gap_execution_model",
                ],
            },
        ),
        SimulatedPhaseProgressItem(
            phase_id="phase_5",
            label="Scheduler approval package rehearsal",
            simulated_status=phase_5_status,
            official_status=OFFICIAL_GATE_NOT_SATISFIED,
            source_trace=("historical_replay_summary", "scheduled_dry_run_status", "pre_v2_readiness"),
            replay_tags=replay_tag_dict,
            next_real_world_steps=(
                "Complete real Phase 0 weekly and multi-day gates.",
                "Prepare backup, rollback, recovery, and explicit manual approval records.",
            ),
            evidence={
                "simulated_phase_5_status": phase_5_status,
                "official_phase_5_status": "blocked",
                "production_scheduler_allowed": False,
                "reason": "Phase 0 official weekly, multi-day, and manual approval gates are not satisfied.",
            },
        ),
    )


def _candidate_gap_reasons(replay_summary: dict[str, Any], scheduled_summary: dict[str, Any]) -> list[str]:
    reasons = [
        *[str(item) for item in replay_summary.get("blocking_gaps", [])],
        *[str(item) for item in replay_summary.get("diagnostics", [])],
        *[str(item) for item in scheduled_summary.get("pipeline_blocking_gaps", [])],
        *[str(item) for item in scheduled_summary.get("pipeline_diagnostic_codes", [])],
    ]
    return list(dict.fromkeys(reasons or ["no_blocking_source_gap_observed_in_rehearsal"]))


def _overall_simulated_status(items: tuple[SimulatedPhaseProgressItem, ...]) -> str:
    statuses = {item.simulated_status for item in items}
    if SIMULATED_BLOCKED in statuses:
        return SIMULATED_BLOCKED
    if SIMULATED_DEGRADED in statuses:
        return SIMULATED_DEGRADED
    return SIMULATED_READY


def _real_world_validation_plan() -> RealWorldValidationPlan:
    return RealWorldValidationPlan(
        phase_0_steps=(
            "Run weekly evidence operations against the working-copy DB.",
            "Save reviewed weekly history only after human confirmation.",
            "Accumulate at least three distinct weekly records.",
        ),
        multi_day_dry_run_steps=(
            "Check freshness and scheduled dry-run output on each real trading day.",
            "Run working-copy confirm smoke repeat=2 for the same day.",
            "Open Evidence Review or Workbench and record the reviewed daily note.",
            "Accumulate at least three reviewed trading-day records.",
        ),
        phase_3_4_steps=(
            "Promote replay gap reasons into a candidate source backlog.",
            "Define source_id, available_date, quality, and missing_policy before diagnostics.",
            "Keep execution realism candidates in research-only validation until accepted.",
        ),
        phase_5_steps=(
            "Verify official Phase 0 gates pass with real records.",
            "Complete backup, rollback, and recovery checklist.",
            "Record explicit manual approval before designing write-mode enablement.",
        ),
    )


def _utc_now_text() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
