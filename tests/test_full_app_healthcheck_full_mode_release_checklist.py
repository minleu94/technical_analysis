import inspect
import pytest

from qa.full_app_healthcheck.full_mode_release_checklist import (
    FullModeChecklistItem,
    FullModeReleaseChecklist,
    generate_full_mode_release_checklist,
    render_full_mode_release_checklist_markdown,
)


def test_generate_full_mode_release_checklist_is_checklist_only():
    checklist = generate_full_mode_release_checklist()

    assert checklist.checklist_id == "full_mode_release_checklist_v1"
    assert checklist.checklist_status == "checklist-only"
    assert checklist.checklist_only is True
    assert checklist.activates_release_gate is False
    assert checklist.mutates_runner_bridge is False
    assert checklist.candidate_mode == "full"
    assert len(checklist.checklist_items) >= 5
    assert checklist.manual_only_gaps
    assert checklist.handoff_targets


def test_full_mode_release_checklist_covers_machine_and_manual_evidence():
    checklist = generate_full_mode_release_checklist()
    item_ids = {item.item_id for item in checklist.checklist_items}

    assert "full_runner_result_review" in item_ids
    assert "closed_loop_flow_diagnostics_review" in item_ids
    assert "coverage_burndown_review" in item_ids
    assert "manual_ux_gap_review" in item_ids
    assert "high_risk_boundary_review" in item_ids
    assert any(item.manual_review_required for item in checklist.checklist_items)
    assert any(not item.manual_review_required for item in checklist.checklist_items)


def test_full_mode_checklist_item_rejects_incomplete_values():
    with pytest.raises(ValueError, match="required_evidence"):
        FullModeChecklistItem(
            item_id="missing_evidence",
            title="Missing evidence",
            category="runner",
            required_evidence=(),
            manual_review_required=False,
            blocking_if_missing=True,
            owner_hint="Testing / QA Agent",
        )


def test_full_mode_release_checklist_rejects_gate_activation_or_bridge_mutation():
    item = FullModeChecklistItem(
        item_id="full_runner_result_review",
        title="Full runner result review",
        category="runner",
        required_evidence=("full runner evidence",),
        manual_review_required=True,
        blocking_if_missing=True,
        owner_hint="Testing / QA Agent",
    )

    with pytest.raises(ValueError, match="must not activate"):
        FullModeReleaseChecklist(
            checklist_id="bad_gate",
            checklist_status="checklist-only",
            checklist_only=True,
            activates_release_gate=True,
            mutates_runner_bridge=False,
            candidate_mode="full",
            checklist_items=(item,),
            manual_only_gaps=("manual gap",),
            machine_evidence_requirements=("machine evidence",),
            handoff_targets=("Tech Lead Agent",),
            next_review_step="review",
        )

    with pytest.raises(ValueError, match="must not mutate"):
        FullModeReleaseChecklist(
            checklist_id="bad_bridge",
            checklist_status="checklist-only",
            checklist_only=True,
            activates_release_gate=False,
            mutates_runner_bridge=True,
            candidate_mode="full",
            checklist_items=(item,),
            manual_only_gaps=("manual gap",),
            machine_evidence_requirements=("machine evidence",),
            handoff_targets=("Tech Lead Agent",),
            next_review_step="review",
        )


def test_render_full_mode_release_checklist_markdown_is_readable():
    checklist = generate_full_mode_release_checklist()

    markdown = render_full_mode_release_checklist_markdown(checklist)

    assert "# Full Mode Release Checklist" in markdown
    assert "`checklist-only`" in markdown
    assert "**Activates Release Gate**: `False`" in markdown
    assert "**Mutates Runner Bridge**: `False`" in markdown
    assert "full_runner_result_review" in markdown
    assert "Manual-only Gaps" in markdown
    assert "Machine Evidence Requirements" in markdown
    assert "Handoff Targets" in markdown


def test_full_mode_release_checklist_has_no_execution_or_write_side_effects():
    import qa.full_app_healthcheck.full_mode_release_checklist as module

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
    assert "MainWindow" not in module_source
