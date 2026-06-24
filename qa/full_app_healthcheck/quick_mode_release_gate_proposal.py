from __future__ import annotations

from dataclasses import dataclass


ALLOWED_GATE_STATUSES = frozenset({"proposal-only", "not-ready", "candidate-ready"})


@dataclass(frozen=True)
class ReleaseGateCriterion:
    criterion_id: str
    title: str
    required_evidence: tuple[str, ...]
    blocking_if_missing: bool
    manual_confirmation_required: bool
    owner_hint: str

    def __post_init__(self) -> None:
        if not self.criterion_id:
            raise ValueError("criterion_id is required.")
        if not self.title:
            raise ValueError("title is required.")
        if not self.required_evidence:
            raise ValueError("required_evidence is required.")
        if not self.owner_hint:
            raise ValueError("owner_hint is required.")


@dataclass(frozen=True)
class QuickModeReleaseGateProposal:
    proposal_id: str
    gate_status: str
    proposal_only: bool
    activates_ci_gate: bool
    mutates_runner_bridge: bool
    candidate_mode: str
    required_criteria: tuple[ReleaseGateCriterion, ...]
    blocker_notes: tuple[str, ...]
    manual_confirmation_points: tuple[str, ...]
    rollback_notes: tuple[str, ...]
    next_review_step: str

    def __post_init__(self) -> None:
        if not self.proposal_id:
            raise ValueError("proposal_id is required.")
        if self.gate_status not in ALLOWED_GATE_STATUSES:
            raise ValueError(f"Invalid gate_status '{self.gate_status}'.")
        if not self.proposal_only:
            raise ValueError("E-3 must remain proposal-only.")
        if self.activates_ci_gate:
            raise ValueError("E-3 must not activate a CI or release gate.")
        if self.mutates_runner_bridge:
            raise ValueError("E-3 must not mutate runner bridge behavior.")
        if self.candidate_mode != "quick":
            raise ValueError("candidate_mode must be quick.")
        if not self.required_criteria:
            raise ValueError("required_criteria is required.")
        for criterion in self.required_criteria:
            if not isinstance(criterion, ReleaseGateCriterion):
                raise TypeError("required_criteria must contain ReleaseGateCriterion instances.")
        if not self.manual_confirmation_points:
            raise ValueError("manual_confirmation_points is required.")
        if not self.rollback_notes:
            raise ValueError("rollback_notes is required.")
        if not self.next_review_step:
            raise ValueError("next_review_step is required.")


def generate_quick_mode_release_gate_proposal() -> QuickModeReleaseGateProposal:
    return QuickModeReleaseGateProposal(
        proposal_id="quick_mode_release_gate_proposal_v1",
        gate_status="proposal-only",
        proposal_only=True,
        activates_ci_gate=False,
        mutates_runner_bridge=False,
        candidate_mode="quick",
        required_criteria=(
            ReleaseGateCriterion(
                criterion_id="quick_runner_passes",
                title="Quick healthcheck runner passes",
                required_evidence=(
                    "scripts/run_full_app_healthcheck.py --mode quick exits with success",
                    "result interpreter reports no failed or blocked direct bridge suite",
                ),
                blocking_if_missing=True,
                manual_confirmation_required=False,
                owner_hint="Testing / QA Agent",
            ),
            ReleaseGateCriterion(
                criterion_id="inventory_and_bridge_guardrails_pass",
                title="Inventory and bridge guardrails pass",
                required_evidence=(
                    "test inventory counts match pytest collection",
                    "write-risk and runner-owned tests remain rejected from bridge execution",
                ),
                blocking_if_missing=True,
                manual_confirmation_required=False,
                owner_hint="Testing / QA Agent",
            ),
            ReleaseGateCriterion(
                criterion_id="known_issue_triage_complete",
                title="Known issue triage is explicit",
                required_evidence=(
                    "known issue matcher can distinguish failure, blocked, manual gap, and unknown errors",
                    "handoff recommendation includes likely owner and next steps for non-passing evidence",
                ),
                blocking_if_missing=True,
                manual_confirmation_required=True,
                owner_hint="Testing / QA Agent",
            ),
            ReleaseGateCriterion(
                criterion_id="release_owner_accepts_gate_scope",
                title="Release owner accepts quick gate scope",
                required_evidence=(
                    "release owner confirms quick mode is a smoke gate, not full product certification",
                    "manual gaps and full-only coverage are documented before release use",
                ),
                blocking_if_missing=True,
                manual_confirmation_required=True,
                owner_hint="Tech Lead Agent",
            ),
        ),
        blocker_notes=(
            "Do not promote quick mode to a formal release gate while direct bridge failures are present.",
            "Do not treat manual gaps, full-only coverage, or service oracle evidence as quick-mode pass evidence.",
        ),
        manual_confirmation_points=(
            "Confirm quick mode is scoped to non-destructive smoke evidence only.",
            "Confirm release owner accepts remaining manual gaps before enabling any future gate.",
        ),
        rollback_notes=(
            "Keep the proposal detached from runner execution until a later approved implementation batch.",
            "If future gate activation causes noisy release blocking, revert only the activation layer and keep metadata.",
        ),
        next_review_step="E-4 Full mode release checklist can broaden release evidence after quick gate scope is reviewed.",
    )


def render_quick_mode_release_gate_proposal_markdown(
    proposal: QuickModeReleaseGateProposal,
) -> str:
    lines = [
        f"# Quick Mode Release Gate Proposal - `{proposal.proposal_id}`",
        "",
        f"- **Status**: `{proposal.gate_status}`",
        f"- **Candidate Mode**: `{proposal.candidate_mode}`",
        f"- **Proposal Only**: `{proposal.proposal_only}`",
        f"- **Activates CI Gate**: `{proposal.activates_ci_gate}`",
        f"- **Mutates Runner Bridge**: `{proposal.mutates_runner_bridge}`",
        "",
        "## Required Criteria",
        "",
        "| Criterion | Blocking | Manual Confirmation | Owner | Required Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]

    for criterion in proposal.required_criteria:
        evidence = "<br>".join(criterion.required_evidence)
        lines.append(
            f"| `{criterion.criterion_id}` - {criterion.title} | "
            f"`{criterion.blocking_if_missing}` | "
            f"`{criterion.manual_confirmation_required}` | "
            f"{criterion.owner_hint} | {evidence} |"
        )

    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {note}" for note in proposal.blocker_notes)
    lines.extend(["", "## Manual Confirmation Points", ""])
    lines.extend(f"- {point}" for point in proposal.manual_confirmation_points)
    lines.extend(["", "## Rollback Notes", ""])
    lines.extend(f"- {note}" for note in proposal.rollback_notes)
    lines.extend(["", "## Next Review Step", "", proposal.next_review_step])

    return "\n".join(lines)
