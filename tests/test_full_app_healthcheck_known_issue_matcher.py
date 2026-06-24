from __future__ import annotations

from qa.full_app_healthcheck.known_issue_matcher import match_known_issues
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.reporting import HealthcheckResult, StepResult
from qa.full_app_healthcheck.result_interpreter import interpret_healthcheck_result


def test_match_daily_prices_sqlite_error_maps_to_data_audit_issue():
    matches = match_known_issues(
        "OperationalError: no such table: daily_prices in SQLite schema check"
    )

    assert len(matches) == 1
    assert matches[0].issue_id == "DATA-AUDIT-001"
    assert matches[0].category == "data_audit"
    assert matches[0].likely_owner == "data_audit"
    assert "Data Audit Agent" in matches[0].recommendation


def test_match_hidden_widget_layout_error_maps_to_execution_issue():
    matches = match_known_issues(
        "AssertionError: hidden widget layout made the action button not visible"
    )

    assert len(matches) == 1
    assert matches[0].issue_id == "UI-EXECUTION-001"
    assert matches[0].category == "ui_execution"
    assert matches[0].likely_owner == "execution"
    assert "Execution Agent" in matches[0].recommendation


def test_match_known_manual_gap_stays_known_manual_gap():
    matches = match_known_issues(
        "known manual gap: Equity curve zoom interaction still needs human inspection"
    )

    assert len(matches) == 1
    assert matches[0].issue_id == "KNOWN-MANUAL-GAP-001"
    assert matches[0].category == "known_manual_gap"
    assert matches[0].likely_owner == "testing_qa"


def test_unknown_text_returns_no_match():
    assert match_known_issues("plain pytest output without a known signal") == ()


def test_interpreter_adds_known_issue_summary_without_promoting_manual_gap_to_passed():
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="failed",
        evidence={
            "suites": [
                {
                    "id": "ui-research-workflow",
                    "title": "既有 Research Lab workflow 測試",
                    "returncode": 1,
                    "stdout_tail": "known manual gap: Equity curve zoom interaction needs human inspection",
                    "stderr_tail": "",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_170000",
        mode=HealthcheckMode.FULL,
        status="failed",
        steps=(step_result,),
    )

    interpretation = interpret_healthcheck_result(result)
    feature = interpretation.feature_results["research_lab"]

    assert feature.status != "passed"
    assert feature.status == "failed"
    assert feature.likely_owner == "testing_qa"
    assert "KNOWN-MANUAL-GAP-001" in feature.evidence_summary
    assert "manual gap" in feature.recommended_next_steps.lower()
