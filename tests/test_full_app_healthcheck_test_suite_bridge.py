from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.test_suite_bridge import (
    ExistingSuite,
    build_existing_suite_registry,
    suites_for_mode,
)


def test_existing_suite_registry_reuses_current_ui_and_qa_tests():
    suites = build_existing_suite_registry()
    ids = {suite.id for suite in suites}

    assert "ui-update-workbench" in ids
    assert "ui-decision-desk" in ids
    assert "ui-research-workflow" in ids
    assert "ui-market-regime-view" in ids
    assert "ui-run-registry-compare" in ids
    assert "ui-smart-money-flow" in ids
    assert "qa-update-tab" in ids


def test_quick_mode_uses_fast_non_destructive_existing_tests():
    suites = suites_for_mode(HealthcheckMode.QUICK)
    commands = [" ".join(suite.command) for suite in suites]

    assert any("tests/test_ui_qt_update_view_workbench.py" in command for command in commands)
    assert any("tests/test_ui_qt_decision_desk_view.py" in command for command in commands)
    assert all(suite.non_destructive for suite in suites)


def test_full_mode_includes_broader_existing_ui_contract_tests():
    suites = suites_for_mode(HealthcheckMode.FULL)
    commands = [" ".join(suite.command) for suite in suites]

    assert any("tests/test_ui_qt_research_workflow.py" in command for command in commands)
    assert any("tests/test_ui_qt_market_regime_view.py" in command for command in commands)
    assert any("tests/test_ui_qt_run_registry_compare.py" in command for command in commands)
    assert any("tests/test_ui_qt_smart_money_flow_view.py" in command for command in commands)
    assert all(suite.non_destructive for suite in suites)


def test_existing_suites_expose_covered_healthcheck_ids_and_flow_ids():
    suites = build_existing_suite_registry()
    coverage_ids = {
        coverage_id
        for suite in suites
        for coverage_id in suite.covered_healthcheck_ids
    }
    flow_ids = {flow_id for suite in suites for flow_id in suite.covered_flow_ids}

    assert "M-001" in coverage_ids
    assert "M-002" in coverage_ids
    assert "B-038" in coverage_ids
    assert "B-039" in coverage_ids
    assert "B-041" in coverage_ids
    assert "research-validation-loop" in flow_ids


def test_existing_suite_command_is_explicit_and_not_shell_joined():
    suite = ExistingSuite(
        id="sample",
        title="sample",
        modes=(HealthcheckMode.QUICK,),
        command=(".\\.venv\\Scripts\\python.exe", "-m", "pytest", "tests/test_ui_qt_update_view_workbench.py", "-q", "-o", "addopts="),
        non_destructive=True,
    )

    assert suite.command[0].endswith("python.exe")
    assert "&&" not in suite.command
