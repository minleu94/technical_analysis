from __future__ import annotations

import json
from pathlib import Path
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.reporting import HealthcheckResult, StepResult, write_reports
from qa.full_app_healthcheck.result_interpreter import (
    interpret_healthcheck_result,
    interpret_healthcheck_json,
    render_interpretation_markdown,
)


def test_interpret_quick_mode_success():
    # 模擬 Quick Mode 通過的情境
    # 只有 ui-update-workbench 與 ui-decision-desk 被執行，且 returncode=0
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="passed",
        evidence={
            "suites": [
                {
                    "id": "ui-update-workbench",
                    "title": "既有 UpdateView widget / contract 測試",
                    "returncode": 0,
                    "stdout_tail": "1 passed",
                    "stderr_tail": "",
                },
                {
                    "id": "ui-decision-desk",
                    "title": "既有 Daily Decision Desk UI 測試",
                    "returncode": 0,
                    "stdout_tail": "2 passed",
                    "stderr_tail": "",
                },
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="passed",
        steps=(step_result,),
    )

    interpretation = interpret_healthcheck_result(result)

    assert interpretation.overall_status == "passed"
    assert interpretation.mode == HealthcheckMode.QUICK

    # 檢查 UpdateView 與 Decision Desk 狀態
    assert interpretation.feature_results["update_view"].status == "passed"
    assert interpretation.feature_results["update_view"].likely_owner == "testing_qa"
    assert interpretation.feature_results["decision_desk"].status == "passed"
    assert interpretation.feature_results["decision_desk"].likely_owner == "testing_qa"

    # 檢查其他功能的狀態，因 quick_supported=False，應為 not_run 且 likely_owner=testing_qa
    assert interpretation.feature_results["research_lab"].status == "not_run"
    assert interpretation.feature_results["research_lab"].likely_owner == "testing_qa"
    assert interpretation.feature_results["market_regime"].status == "not_run"
    assert interpretation.feature_results["market_regime"].likely_owner == "testing_qa"
    assert interpretation.feature_results["smart_money"].status == "not_run"
    assert interpretation.feature_results["smart_money"].likely_owner == "testing_qa"
    assert interpretation.feature_results["registry_compare"].status == "not_run"
    assert interpretation.feature_results["registry_compare"].likely_owner == "testing_qa"


def test_interpret_data_audit_failure():
    # 模擬 UpdateView 的 ui-update-workbench 失敗，且 stdout/stderr 帶有 SQLite 錯誤字眼
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="failed",
        evidence={
            "suites": [
                {
                    "id": "ui-update-workbench",
                    "title": "既有 UpdateView widget / contract 測試",
                    "returncode": 1,
                    "stdout_tail": "OperationalError: no such table: daily_prices",
                    "stderr_tail": "SQLite database error",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="failed",
        steps=(step_result,),
    )

    interpretation = interpret_healthcheck_result(result)

    assert interpretation.overall_status == "needs_data_audit"
    uv_result = interpretation.feature_results["update_view"]
    assert uv_result.status == "needs_data_audit"
    assert uv_result.likely_owner == "data_audit"
    assert "daily price" in interpretation.data_audit_recommendations[0]


def test_interpret_execution_failure():
    # 模擬 Decision Desk 的 ui-decision-desk 失敗，帶有 widget 錯誤字眼
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="failed",
        evidence={
            "suites": [
                {
                    "id": "ui-decision-desk",
                    "title": "既有 Daily Decision Desk UI 測試",
                    "returncode": 1,
                    "stdout_tail": "AssertionError: Element is not visible",
                    "stderr_tail": "Failed to click button widget",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="failed",
        steps=(step_result,),
    )

    interpretation = interpret_healthcheck_result(result)

    assert interpretation.overall_status == "failed"
    dd_result = interpretation.feature_results["decision_desk"]
    assert dd_result.status == "failed"
    assert dd_result.likely_owner == "execution"


def test_interpret_unknown_suite_and_not_crash():
    # 模擬有未知的 suite ID
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="failed",
        evidence={
            "suites": [
                {
                    "id": "ui-unknown-suite-id",
                    "title": "未知的測試",
                    "returncode": 1,
                    "stdout_tail": "Some error",
                    "stderr_tail": "",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="failed",
        steps=(step_result,),
    )

    interpretation = interpret_healthcheck_result(result)

    assert len(interpretation.runner_failures) == 1
    assert interpretation.runner_failures[0]["id"] == "ui-unknown-suite-id"
    assert interpretation.overall_status == "failed"


def test_interpret_unknown_passing_suite_still_marks_runner_failure():
    # 未註冊的 suite 即使命令本身通過，也代表測試路由矩陣與 bridge 設定不一致。
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="passed",
        evidence={
            "suites": [
                {
                    "id": "ui-unregistered-passing-suite",
                    "title": "未註冊但通過的測試",
                    "returncode": 0,
                    "stdout_tail": "1 passed",
                    "stderr_tail": "",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="passed",
        steps=(step_result,),
    )

    interpretation = interpret_healthcheck_result(result)

    assert interpretation.runner_failures[0]["id"] == "ui-unregistered-passing-suite"
    assert interpretation.runner_failures[0]["error"] == "Unmatched suite id"
    assert interpretation.overall_status == "failed"


def test_runner_step_failure_without_suite_is_reported():
    step_result = StepResult(
        id="MISSING-ACTION",
        title="缺少 action 的 runner step",
        status="failed",
        evidence={"error": "找不到 action: assert_missing_widget", "type": "AssertionError"},
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="failed",
        steps=(step_result,),
    )

    interpretation = interpret_healthcheck_result(result)

    assert interpretation.overall_status == "failed"
    assert len(interpretation.runner_failures) == 1
    assert interpretation.runner_failures[0]["id"] == "MISSING-ACTION"
    assert interpretation.runner_failures[0]["error"] == "找不到 action: assert_missing_widget"


def test_interpret_healthcheck_json(tmp_path: Path):
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="passed",
        evidence={
            "suites": [
                {
                    "id": "ui-update-workbench",
                    "title": "既有 UpdateView widget / contract 測試",
                    "returncode": 0,
                    "stdout_tail": "OK",
                    "stderr_tail": "",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_150000",
        mode=HealthcheckMode.QUICK,
        status="passed",
        steps=(step_result,),
    )

    # 寫入 json 報告
    report_files = write_reports(result, tmp_path)

    # 解讀 json 報告
    interpretation = interpret_healthcheck_json(report_files.json)

    assert interpretation.overall_status == "passed"
    assert interpretation.mode == HealthcheckMode.QUICK
    assert interpretation.feature_results["update_view"].status == "passed"


def test_render_interpretation_markdown_quick_success():
    # 測試正常快速模式下的 Markdown 輸出
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="passed",
        evidence={
            "suites": [
                {
                    "id": "ui-update-workbench",
                    "title": "既有 UpdateView widget 測試",
                    "returncode": 0,
                    "stdout_tail": "1 passed",
                    "stderr_tail": "",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="passed",
        steps=(step_result,),
    )
    interpretation = interpret_healthcheck_result(result)
    markdown_report = render_interpretation_markdown(interpretation)

    # 驗證繁體中文標題與狀態存在
    assert "# Healthcheck 測試解讀報告" in markdown_report
    assert "## 功能檢驗結果" in markdown_report
    assert "## 功能解讀與行動指南" in markdown_report
    assert "- **檢查模式**: 快速檢查 (QUICK)" in markdown_report
    assert "- **總體狀態**: `通過 (passed)`" in markdown_report
    assert "UpdateView / 資料更新頁" in markdown_report
    assert "通過 (passed)" in markdown_report
    for symbol in ("\U0001f3af", "\U0001f50d", "\U0001f6a7", "\u274c"):
        assert symbol not in markdown_report


def test_render_interpretation_markdown_needs_data_audit():
    # 測試需要資料審計的 Markdown 輸出
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="failed",
        evidence={
            "suites": [
                {
                    "id": "ui-update-workbench",
                    "title": "既有 UpdateView widget 測試",
                    "returncode": 1,
                    "stdout_tail": "OperationalError: no such table: daily_prices",
                    "stderr_tail": "SQLite database error",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="failed",
        steps=(step_result,),
    )
    interpretation = interpret_healthcheck_result(result)
    markdown_report = render_interpretation_markdown(interpretation)

    assert "- **總體狀態**: `需要資料審計 (needs_data_audit)`" in markdown_report
    assert "## Data Audit 建議稽核項目" in markdown_report
    assert "Compare SQLite schema with daily price CSV integration" in markdown_report


def test_render_interpretation_markdown_runner_failures():
    # 測試帶有 Runner 異常的 Markdown 輸出
    step_result = StepResult(
        id="run_existing_suites_for_mode",
        title="執行既有測試套件",
        status="failed",
        evidence={
            "suites": [
                {
                    "id": "ui-unknown-suite-id",
                    "title": "未知的測試",
                    "returncode": 127,
                    "stdout_tail": "Command not found",
                    "stderr_tail": "Execution failed",
                }
            ]
        },
    )
    result = HealthcheckResult(
        run_id="20260623_120000",
        mode=HealthcheckMode.QUICK,
        status="failed",
        steps=(step_result,),
    )
    interpretation = interpret_healthcheck_result(result)
    markdown_report = render_interpretation_markdown(interpretation)

    assert "## 執行器異常或未識別套件 (Runner Failures)" in markdown_report
    assert "套件 ID**: `ui-unknown-suite-id`" in markdown_report
    assert "錯誤原因**: Unmatched suite id" in markdown_report
    assert "回傳碼**: `127`" in markdown_report
