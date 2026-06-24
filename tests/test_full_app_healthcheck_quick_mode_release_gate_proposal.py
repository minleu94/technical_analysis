import inspect
import sys

import pytest

from qa.full_app_healthcheck.quick_mode_release_gate_proposal import (
    QuickModeReleaseGateProposal,
    ReleaseGateCriterion,
    generate_quick_mode_release_gate_proposal,
    render_quick_mode_release_gate_proposal_markdown,
)


def test_generate_quick_mode_release_gate_proposal_is_proposal_only():
    proposal = generate_quick_mode_release_gate_proposal()

    assert proposal.proposal_id == "quick_mode_release_gate_proposal_v1"
    assert proposal.gate_status == "proposal-only"
    assert proposal.proposal_only is True
    assert proposal.activates_ci_gate is False
    assert proposal.mutates_runner_bridge is False
    assert proposal.candidate_mode == "quick"
    assert len(proposal.required_criteria) >= 4
    assert proposal.manual_confirmation_points
    assert proposal.rollback_notes


def test_required_criteria_cover_runner_inventory_triage_and_release_owner():
    proposal = generate_quick_mode_release_gate_proposal()
    criterion_ids = {criterion.criterion_id for criterion in proposal.required_criteria}

    assert "quick_runner_passes" in criterion_ids
    assert "inventory_and_bridge_guardrails_pass" in criterion_ids
    assert "known_issue_triage_complete" in criterion_ids
    assert "release_owner_accepts_gate_scope" in criterion_ids
    assert all(criterion.blocking_if_missing for criterion in proposal.required_criteria)
    assert any(criterion.manual_confirmation_required for criterion in proposal.required_criteria)


def test_release_gate_criterion_rejects_incomplete_values():
    with pytest.raises(ValueError, match="required_evidence"):
        ReleaseGateCriterion(
            criterion_id="missing_evidence",
            title="Missing evidence",
            required_evidence=(),
            blocking_if_missing=True,
            manual_confirmation_required=False,
            owner_hint="Testing / QA Agent",
        )


def test_quick_mode_release_gate_proposal_rejects_activation_or_bridge_mutation():
    criterion = ReleaseGateCriterion(
        criterion_id="quick_runner_passes",
        title="Quick runner passes",
        required_evidence=("quick runner pass evidence",),
        blocking_if_missing=True,
        manual_confirmation_required=False,
        owner_hint="Testing / QA Agent",
    )

    with pytest.raises(ValueError, match="must not activate"):
        QuickModeReleaseGateProposal(
            proposal_id="bad_activation",
            gate_status="proposal-only",
            proposal_only=True,
            activates_ci_gate=True,
            mutates_runner_bridge=False,
            candidate_mode="quick",
            required_criteria=(criterion,),
            blocker_notes=("blocked",),
            manual_confirmation_points=("confirm",),
            rollback_notes=("rollback",),
            next_review_step="review",
        )

    with pytest.raises(ValueError, match="must not mutate"):
        QuickModeReleaseGateProposal(
            proposal_id="bad_bridge_mutation",
            gate_status="proposal-only",
            proposal_only=True,
            activates_ci_gate=False,
            mutates_runner_bridge=True,
            candidate_mode="quick",
            required_criteria=(criterion,),
            blocker_notes=("blocked",),
            manual_confirmation_points=("confirm",),
            rollback_notes=("rollback",),
            next_review_step="review",
        )


def test_render_quick_mode_release_gate_proposal_markdown_is_readable():
    proposal = generate_quick_mode_release_gate_proposal()

    markdown = render_quick_mode_release_gate_proposal_markdown(proposal)

    assert "# Quick Mode Release Gate Proposal" in markdown
    assert "`proposal-only`" in markdown
    assert "**Activates CI Gate**: `False`" in markdown
    assert "**Mutates Runner Bridge**: `False`" in markdown
    assert "quick_runner_passes" in markdown
    assert "Manual Confirmation Points" in markdown
    assert "Rollback Notes" in markdown
    assert "E-4 Full mode release checklist" in markdown


def test_quick_mode_release_gate_proposal_has_no_execution_or_write_side_effects():
    import qa.full_app_healthcheck.quick_mode_release_gate_proposal as module

    module_source = inspect.getsource(module)

    assert "Path(" not in module_source
    assert "write_text" not in module_source
    assert "write_bytes" not in module_source
    assert "open(" not in module_source
    assert ".write(" not in module_source
    assert "subprocess" not in module_source
    assert "test_suite_bridge" not in module_source
    assert "PySide6" not in module_source
    assert "QApplication" not in module_source
    assert "PySide6.QtWidgets" not in sys.modules
