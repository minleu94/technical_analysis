"""Read-only Workbench projection for Gate 2-7 engineering closure."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from app_module.engineering_gate_registry import EngineeringGateItem
from app_module.evidence_rehearsal_dtos import (
    CoverageMetric,
    EvidenceRehearsalReport,
    EvidenceRehearsalScenario,
    RehearsalArtifact,
)
from app_module.gate_2_to_7_closeout_verifier import Gate2To7CloseoutReport
from app_module.workbench_dtos import WorkbenchActionItem


@dataclass(frozen=True)
class EngineeringClosureGateRow:
    item_id: str
    category: str
    title: str
    status: str
    owner: str
    earliest_validation_date: str
    progress_bp: int
    next_command: str
    required_artifacts: tuple[str, ...]
    completion_rules: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class EngineeringClosureDashboardDTO:
    engineering_package_status: str
    external_validation_status: str
    satisfied_requirements: int
    total_requirements: int
    open_gate_count: int
    category_counts: dict[str, int]
    status_counts: dict[str, int]
    gates: tuple[EngineeringClosureGateRow, ...]
    closeout_blockers: tuple[str, ...]
    read_only: bool = True
    write_actions_allowed: bool = False
    production_scheduler_allowed: bool = False
    formal_product_closeout: bool = False


@dataclass(frozen=True)
class EvidenceRehearsalDashboard:
    """唯讀 rehearsal 投影；絕不把工程或回放結果當成 forward 證據。"""

    tier: str
    status: str
    coverage: tuple[CoverageMetric, ...]
    blockers: tuple[str, ...]
    disclosure: str = "工程／Replay／Shadow；不是 forward evidence"
    write_intent: bool = False
    shadow_comparison_present: bool = False
    forward_handoff_pending: bool = True


class EngineeringClosureDashboardService:
    def build(
        self,
        *,
        closeout: Gate2To7CloseoutReport,
        gates: Iterable[EngineeringGateItem],
    ) -> EngineeringClosureDashboardDTO:
        items = tuple(sorted(gates, key=lambda item: (item.category, item.item_id)))
        rows = tuple(
            EngineeringClosureGateRow(
                item_id=item.item_id,
                category=item.category,
                title=item.title,
                status=item.status,
                owner=item.owner,
                earliest_validation_date=item.earliest_validation_date,
                progress_bp=item.progress_bp,
                next_command=item.validation_commands[0],
                required_artifacts=item.required_artifacts,
                completion_rules=item.completion_rules,
                prohibited_actions=item.prohibited_actions,
                notes=item.notes,
            )
            for item in items
        )
        category_counts = Counter(item.category for item in items)
        status_counts = Counter(item.status for item in items)
        return EngineeringClosureDashboardDTO(
            engineering_package_status=closeout.engineering_package_status,
            external_validation_status=closeout.external_validation_status,
            satisfied_requirements=closeout.satisfied_count,
            total_requirements=closeout.requirement_count,
            open_gate_count=sum(item.status != "complete" for item in items),
            category_counts=dict(sorted(category_counts.items())),
            status_counts=dict(sorted(status_counts.items())),
            gates=rows,
            closeout_blockers=closeout.blockers,
        )

    def compose(self, rehearsal_report: EvidenceRehearsalReport) -> EvidenceRehearsalDashboard:
        """將既有 rehearsal report 投影為 Control Center 可顯示的唯讀狀態。"""
        coverage = rehearsal_report.coverage_metrics
        blockers = _rehearsal_blockers(rehearsal_report)
        return EvidenceRehearsalDashboard(
            tier=rehearsal_report.scenario.tier,
            status="blocked" if blockers else "rehearsal_only",
            coverage=coverage,
            blockers=blockers,
            shadow_comparison_present=(
                rehearsal_report.scenario.tier == "shadow_comparison"
                or any(item.tier == "shadow_comparison" for item in rehearsal_report.artifacts)
            ),
        )

    def load_rehearsal_report(self, report_path: str | Path) -> EvidenceRehearsalDashboard:
        """Load a controlled JSON package only; this boundary never opens a database."""
        path = Path(report_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"controlled rehearsal report is unreadable: {path}") from error
        if not isinstance(payload, Mapping):
            raise ValueError("controlled rehearsal report must be a JSON object")
        report = _report_from_payload(payload)
        dashboard = self.compose(report)
        external_blockers = _external_projection_blockers(payload)
        blockers = tuple(sorted(set((*dashboard.blockers, *external_blockers))))
        return replace(
            dashboard,
            status="blocked" if blockers else dashboard.status,
            blockers=blockers,
            shadow_comparison_present=(
                dashboard.shadow_comparison_present
                or "p0_source_shadow" in payload
                or "ml_shadow" in payload
            ),
        )

    def to_workbench_action_items(
        self, dashboard: EngineeringClosureDashboardDTO
    ) -> tuple[WorkbenchActionItem, ...]:
        actions = []
        for index, item in enumerate(dashboard.gates):
            if item.status == "complete":
                continue
            severity = "warning" if item.status in {"open", "in_progress", "rejected"} else "info"
            actions.append(
                WorkbenchActionItem(
                    item_id=f"engineering_gate:{item.item_id}",
                    title=item.title,
                    source_type="engineering_closure_gate",
                    severity=severity,
                    summary=(
                        f"owner={item.owner}; earliest={item.earliest_validation_date}; "
                        f"progress={item.progress_bp}/10000; next={item.next_command}"
                    ),
                    source_trace=f"EngineeringGateRegistry:{item.item_id}",
                    degraded_reason="; ".join(item.prohibited_actions),
                    drilldown_target="evidence_review",
                    queue_group="engineering_closure",
                    source_label=item.category,
                    sort_rank=5000 + index,
                    code=item.status,
                    write_intent=False,
                )
            )
        return tuple(actions)


def _rehearsal_blockers(rehearsal_report: EvidenceRehearsalReport) -> tuple[str, ...]:
    blockers: list[str] = []
    for metric in rehearsal_report.coverage_metrics:
        if metric.degraded_count:
            blockers.append(f"coverage_degraded:{metric.source_id}={metric.degraded_count}")
        if metric.missing_count:
            blockers.append(f"coverage_missing:{metric.source_id}={metric.missing_count}")
        if metric.future_blocked_count:
            blockers.append(
                f"coverage_future_blocked:{metric.source_id}={metric.future_blocked_count}"
            )
        if metric.immature_label_count:
            blockers.append(
                f"coverage_immature_label:{metric.source_id}={metric.immature_label_count}"
            )
    for artifact in rehearsal_report.artifacts:
        if artifact.missing_state:
            blockers.append(f"missing_state:{artifact.missing_state}")
        if artifact.current_status in {
            "blocked",
            "degraded",
            "insufficient",
            "insufficient_sample",
            "missing",
            "outage",
        }:
            blockers.append(f"artifact_status:{artifact.current_status}")
        blockers.extend(artifact.diagnostics)
    return tuple(sorted(set(blockers)))


def _report_from_payload(payload: Mapping[str, Any]) -> EvidenceRehearsalReport:
    report_payload = payload.get("rehearsal_report", payload)
    if not isinstance(report_payload, Mapping):
        raise ValueError("rehearsal_report must be an object")
    scenario_payload = report_payload.get("scenario")
    if not isinstance(scenario_payload, Mapping):
        raise ValueError("rehearsal_report.scenario must be an object")
    scenario = EvidenceRehearsalScenario(**dict(scenario_payload))
    metrics = tuple(
        CoverageMetric(**dict(item))
        for item in report_payload.get("coverage_metrics", ())
        if isinstance(item, Mapping)
    )
    artifacts = tuple(
        RehearsalArtifact(**_artifact_kwargs(item))
        for item in report_payload.get("artifacts", ())
        if isinstance(item, Mapping)
    )
    return EvidenceRehearsalReport(scenario=scenario, coverage_metrics=metrics, artifacts=artifacts)


def _artifact_kwargs(payload: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(payload)
    for name in ("parent_artifact_ids", "diagnostics"):
        if name in values:
            values[name] = tuple(values[name])
    return values


def _external_projection_blockers(payload: Mapping[str, Any]) -> tuple[str, ...]:
    blockers: list[str] = []
    source_shadow = payload.get("p0_source_shadow")
    if isinstance(source_shadow, Mapping):
        items = source_shadow.get("items", ())
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping):
                    blockers.extend(str(value) for value in item.get("blockers", ()) if value)
    ml_shadow = payload.get("ml_shadow")
    if isinstance(ml_shadow, Mapping):
        status = ml_shadow.get("status")
        if isinstance(status, str) and status not in {"shadow_ready", "not_provided"}:
            blockers.append(f"ml_shadow:{status}")
    return tuple(sorted(set(blockers)))
