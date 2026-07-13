"""Read-only Workbench projection for Gate 2-7 engineering closure."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from app_module.engineering_gate_registry import EngineeringGateItem
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
