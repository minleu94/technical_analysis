from qa.full_app_healthcheck.candidate_bridge_policy import (
    evaluate_candidate_bridge_policy,
    render_candidate_bridge_policy_markdown,
)
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.test_inventory import get_candidate_bridge_files, is_allowed_in_bridge


def test_candidate_policy_maps_feature_candidates_without_allowing_bridge_directly():
    report = evaluate_candidate_bridge_policy()
    by_path = {item.path: item for item in report.items}

    decision = by_path["tests/test_ui_qt_decision_desk_main_integration.py"]

    assert decision.feature_id == "decision_desk"
    assert decision.decision == "eligible-full-mode-review"
    assert decision.allowed_modes == (HealthcheckMode.FULL,)
    assert decision.runner_action == "do-not-bridge-yet"
    assert "non-destructive evidence" in " ".join(decision.prerequisites)
    assert not is_allowed_in_bridge(decision.path)


def test_candidate_policy_keeps_full_only_feature_candidates_out_of_quick_mode():
    report = evaluate_candidate_bridge_policy()
    by_path = {item.path: item for item in report.items}

    decision = by_path["tests/test_ui_qt_research_lab_mode_driven_ui.py"]

    assert decision.feature_id == "research_lab"
    assert decision.allowed_modes == (HealthcheckMode.FULL,)
    assert any("Quick Mode" in note for note in decision.safety_notes)
    assert decision.runner_action == "do-not-bridge-yet"


def test_candidate_policy_marks_unmapped_candidates_for_tech_lead_review():
    report = evaluate_candidate_bridge_policy()
    by_path = {item.path: item for item in report.items}

    decision = by_path["tests/test_ui_qt_chart_payloads.py"]

    assert decision.feature_id is None
    assert decision.decision == "needs-feature-route"
    assert decision.likely_owner == "tech_lead"
    assert decision.allowed_modes == ()
    assert "FEATURE_ROUTES" in " ".join(decision.prerequisites)


def test_candidate_policy_markdown_is_a_review_plan_not_a_bridge_mutation():
    report = evaluate_candidate_bridge_policy()
    markdown = render_candidate_bridge_policy_markdown(report)

    assert "## Candidate Bridge Promote Policy" in markdown
    assert "Do not edit `qa/full_app_healthcheck/test_suite_bridge.py` automatically." in markdown
    assert f"{len(get_candidate_bridge_files())} candidate tests" in markdown
    assert "tests/test_ui_qt_decision_desk_main_integration.py" in markdown
