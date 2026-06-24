from __future__ import annotations

from dataclasses import dataclass


ALLOWED_CHECKLIST_STATUSES = frozenset({"checklist-only", "not-ready", "ready-for-review"})
ALLOWED_ITEM_CATEGORIES = frozenset({
    "runner",
    "closed-loop",
    "coverage",
    "ux",
    "risk-boundary",
    "documentation",
})


@dataclass(frozen=True)
class FullModeChecklistItem:
    item_id: str
    title: str
    category: str
    required_evidence: tuple[str, ...]
    manual_review_required: bool
    blocking_if_missing: bool
    owner_hint: str

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("item_id is required.")
        if not self.title:
            raise ValueError("title is required.")
        if self.category not in ALLOWED_ITEM_CATEGORIES:
            raise ValueError(f"Invalid category '{self.category}'.")
        if not self.required_evidence:
            raise ValueError("required_evidence is required.")
        if not self.owner_hint:
            raise ValueError("owner_hint is required.")


@dataclass(frozen=True)
class FullModeReleaseChecklist:
    checklist_id: str
    checklist_status: str
    checklist_only: bool
    activates_release_gate: bool
    mutates_runner_bridge: bool
    candidate_mode: str
    checklist_items: tuple[FullModeChecklistItem, ...]
    manual_only_gaps: tuple[str, ...]
    machine_evidence_requirements: tuple[str, ...]
    handoff_targets: tuple[str, ...]
    next_review_step: str

    def __post_init__(self) -> None:
        if not self.checklist_id:
            raise ValueError("checklist_id is required.")
        if self.checklist_status not in ALLOWED_CHECKLIST_STATUSES:
            raise ValueError(f"Invalid checklist_status '{self.checklist_status}'.")
        if not self.checklist_only:
            raise ValueError("E-4 must remain checklist-only.")
        if self.activates_release_gate:
            raise ValueError("E-4 must not activate a release gate.")
        if self.mutates_runner_bridge:
            raise ValueError("E-4 must not mutate runner bridge behavior.")
        if self.candidate_mode != "full":
            raise ValueError("candidate_mode must be full.")
        if not self.checklist_items:
            raise ValueError("checklist_items is required.")
        for item in self.checklist_items:
            if not isinstance(item, FullModeChecklistItem):
                raise TypeError("checklist_items must contain FullModeChecklistItem instances.")
        if not self.manual_only_gaps:
            raise ValueError("manual_only_gaps is required.")
        if not self.machine_evidence_requirements:
            raise ValueError("machine_evidence_requirements is required.")
        if not self.handoff_targets:
            raise ValueError("handoff_targets is required.")
        if not self.next_review_step:
            raise ValueError("next_review_step is required.")


def generate_full_mode_release_checklist() -> FullModeReleaseChecklist:
    return FullModeReleaseChecklist(
        checklist_id="full_mode_release_checklist_v1",
        checklist_status="checklist-only",
        checklist_only=True,
        activates_release_gate=False,
        mutates_runner_bridge=False,
        candidate_mode="full",
        checklist_items=(
            FullModeChecklistItem(
                item_id="full_runner_result_review",
                title="Full healthcheck runner result review",
                category="runner",
                required_evidence=(
                    "full mode healthcheck result has been reviewed by Testing / QA Agent",
                    "result interpreter output separates passed, failed, blocked, and manual-gap evidence",
                ),
                manual_review_required=True,
                blocking_if_missing=True,
                owner_hint="Testing / QA Agent",
            ),
            FullModeChecklistItem(
                item_id="closed_loop_flow_diagnostics_review",
                title="Closed-loop flow diagnostics review",
                category="closed-loop",
                required_evidence=(
                    "flow diagnostics report covers data market, research validation, portfolio review, and daily decision loops",
                    "each closed-loop flow lists evidence, gaps, commands, and handoff owner",
                ),
                manual_review_required=True,
                blocking_if_missing=True,
                owner_hint="Testing / QA Agent",
            ),
            FullModeChecklistItem(
                item_id="coverage_burndown_review",
                title="Coverage burn-down review",
                category="coverage",
                required_evidence=(
                    "coverage burn-down identifies fully covered, oracle-only, and gap features",
                    "new or unresolved gaps are explicit before release review",
                ),
                manual_review_required=False,
                blocking_if_missing=True,
                owner_hint="Testing / QA Agent",
            ),
            FullModeChecklistItem(
                item_id="manual_ux_gap_review",
                title="Manual UX gap review",
                category="ux",
                required_evidence=(
                    "known UX gap mapping is reviewed for unclear copy, missing entrypoints, occlusion, and unclear next steps",
                    "manual-only UX risks are listed with recommended next step",
                ),
                manual_review_required=True,
                blocking_if_missing=True,
                owner_hint="Testing / QA Agent",
            ),
            FullModeChecklistItem(
                item_id="high_risk_boundary_review",
                title="High-risk boundary review",
                category="risk-boundary",
                required_evidence=(
                    "high-risk dry-run dialog plans remain metadata-only",
                    "write-risk, migration, backfill, and real service actions remain outside full mode checklist execution",
                ),
                manual_review_required=True,
                blocking_if_missing=True,
                owner_hint="Tech Lead Agent",
            ),
            FullModeChecklistItem(
                item_id="documentation_handoff_review",
                title="Documentation and handoff review",
                category="documentation",
                required_evidence=(
                    "roadmap, inventory classification, and handoff prompt are synchronized",
                    "release review identifies owner for unknown failures or manual gaps",
                ),
                manual_review_required=True,
                blocking_if_missing=True,
                owner_hint="Documentation Agent",
            ),
        ),
        manual_only_gaps=(
            "Visible / interactive mode remains manual-only until explicitly approved.",
            "Full mode evidence does not certify write-risk dry-runs, migrations, or real data apply paths.",
        ),
        machine_evidence_requirements=(
            "pytest collection count matches test inventory classification",
            "quick healthcheck remains passing before full checklist review",
            "run history comparison can identify regressions and fixed suites between runs",
        ),
        handoff_targets=(
            "Testing / QA Agent",
            "Tech Lead Agent",
            "Documentation Agent",
            "Data Audit Agent when failures involve SQLite / CSV freshness or schema integrity",
        ),
        next_review_step="Post-E-4 release review must decide whether any checklist item becomes an actual gate.",
    )


def render_full_mode_release_checklist_markdown(checklist: FullModeReleaseChecklist) -> str:
    lines = [
        f"# Full Mode Release Checklist - `{checklist.checklist_id}`",
        "",
        f"- **Status**: `{checklist.checklist_status}`",
        f"- **Candidate Mode**: `{checklist.candidate_mode}`",
        f"- **Checklist Only**: `{checklist.checklist_only}`",
        f"- **Activates Release Gate**: `{checklist.activates_release_gate}`",
        f"- **Mutates Runner Bridge**: `{checklist.mutates_runner_bridge}`",
        "",
        "## Checklist Items",
        "",
        "| Item | Category | Blocking | Manual Review | Owner | Required Evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for item in checklist.checklist_items:
        evidence = "<br>".join(item.required_evidence)
        lines.append(
            f"| `{item.item_id}` - {item.title} | `{item.category}` | "
            f"`{item.blocking_if_missing}` | `{item.manual_review_required}` | "
            f"{item.owner_hint} | {evidence} |"
        )

    lines.extend(["", "## Manual-only Gaps", ""])
    lines.extend(f"- {gap}" for gap in checklist.manual_only_gaps)
    lines.extend(["", "## Machine Evidence Requirements", ""])
    lines.extend(f"- {requirement}" for requirement in checklist.machine_evidence_requirements)
    lines.extend(["", "## Handoff Targets", ""])
    lines.extend(f"- {target}" for target in checklist.handoff_targets)
    lines.extend(["", "## Next Review Step", "", checklist.next_review_step])

    return "\n".join(lines)
