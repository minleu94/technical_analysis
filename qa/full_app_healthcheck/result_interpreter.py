from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.reporting import HealthcheckResult, StepResult
from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.handoff_contract import build_handoff_recommendations, render_handoff_markdown
from qa.full_app_healthcheck.known_issue_matcher import match_known_issues


@dataclass(frozen=True)
class FeatureInterpretation:
    feature_id: str
    display_name: str
    status: str  # 'passed', 'failed', 'not_run', 'partial', 'needs_data_audit'
    matched_suite_ids: list[str]
    failed_suite_ids: list[str]
    evidence_summary: str
    likely_owner: str  # 'testing_qa', 'data_audit', 'execution', 'tech_lead', 'manual'
    recommended_next_steps: str
    known_gaps: list[str]


@dataclass(frozen=True)
class HealthcheckInterpretation:
    overall_status: str
    mode: HealthcheckMode
    feature_results: dict[str, FeatureInterpretation]
    runner_failures: list[dict[str, Any]]
    data_audit_recommendations: list[str]
    manual_gaps: list[str]


def interpret_healthcheck_result(result: HealthcheckResult) -> HealthcheckInterpretation:
    """讀取 HealthcheckResult 並將其解讀成功能層級之判讀報告。"""
    # 1. 收集所有已執行的測試套件
    suites_run: list[dict[str, Any]] = []
    runner_failures: list[dict[str, Any]] = []
    for step in result.steps:
        if step.evidence and "suites" in step.evidence:
            suites_run.extend(step.evidence["suites"])
        elif step.status != "passed":
            runner_failures.append(
                {
                    "id": step.id,
                    "title": step.title,
                    "step_status": step.status,
                    "error": step.evidence.get("error", "") if step.evidence else "",
                    "type": step.evidence.get("type", "") if step.evidence else "",
                    "evidence": step.evidence,
                }
            )

    feature_results: dict[str, FeatureInterpretation] = {}
    matched_suite_ids_by_feature: dict[str, list[str]] = {fid: [] for fid in FEATURE_ROUTES}
    failed_suite_ids_by_feature: dict[str, list[str]] = {fid: [] for fid in FEATURE_ROUTES}
    suites_by_feature: dict[str, list[dict[str, Any]]] = {fid: [] for fid in FEATURE_ROUTES}

    # 2. 將執行過的 suites 對應回功能
    for suite in suites_run:
        suite_id = suite.get("id")
        matched = False
        for fid, route in FEATURE_ROUTES.items():
            if suite_id in route.direct_bridge_suite_ids:
                matched = True
                suites_by_feature[fid].append(suite)
                if suite_id not in matched_suite_ids_by_feature[fid]:
                    matched_suite_ids_by_feature[fid].append(suite_id)
                if suite.get("returncode") != 0:
                    if suite_id not in failed_suite_ids_by_feature[fid]:
                        failed_suite_ids_by_feature[fid].append(suite_id)
        if not matched:
            runner_failures.append({
                "id": suite_id,
                "error": "Unmatched suite id",
                "suite": suite
            })

    # 3. 判定每個功能的狀態與歸屬
    for fid, route in FEATURE_ROUTES.items():
        matched_suites = suites_by_feature[fid]

        if not matched_suites:
            # 沒跑到任何測試
            if result.mode == HealthcheckMode.QUICK and not route.quick_supported:
                status = "not_run"
                likely_owner = "testing_qa"
                evidence_summary = "該功能不支援 Quick Mode，測試未運行"
                recommended_next_steps = "不需處理。此功能需在 Full Mode 下進行測試。"
            else:
                status = "not_run"
                likely_owner = "testing_qa"
                evidence_summary = "在此模式下未運行任何匹配的測試套件"
                recommended_next_steps = f"請檢查 Manifest，確保註冊了 {', '.join(route.direct_bridge_suite_ids)}。"
        else:
            failed_suites = [s for s in matched_suites if s.get("returncode") != 0]
            if not failed_suites:
                status = "passed"
                likely_owner = "testing_qa"
                evidence_summary = f"所有跑過的測試套件 ({', '.join(matched_suite_ids_by_feature[fid])}) 皆順利通過"
                recommended_next_steps = "無。功能目前狀態正常。"
            else:
                # 收集錯誤日誌
                err_text_parts = []
                for fs in failed_suites:
                    err_text_parts.append(fs.get("stdout_tail", ""))
                    err_text_parts.append(fs.get("stderr_tail", ""))
                err_text = "\n".join(err_text_parts).lower()
                known_issue_matches = tuple(match_known_issues(err_text))
                known_issue_summary = "; ".join(
                    f"{match.issue_id}: {match.title} ({match.confidence})"
                    for match in known_issue_matches
                )
                known_issue_recommendations = " ".join(
                    match.recommendation for match in known_issue_matches
                )

                # 關鍵字解析偏向
                data_keywords = ["filenotfounderror", "sqlite", "csv", "schema", "available_date", "broker_flows", "daily_prices", "fundamental"]
                ui_keywords = ["widget", "tab", "button", "assertionerror", "layout", "visible"]

                has_data_error = any(kw in err_text for kw in data_keywords)
                has_ui_error = any(kw in err_text for kw in ui_keywords)
                has_data_match = any(match.category == "data_audit" for match in known_issue_matches)
                has_ui_match = any(match.category == "ui_execution" for match in known_issue_matches)
                has_manual_gap_match = any(match.category == "known_manual_gap" for match in known_issue_matches)

                if has_data_match or has_data_error:
                    status = "needs_data_audit"
                    likely_owner = "data_audit"
                    evidence_summary = f"測試套件失敗。偵測到資料/資料庫相關錯誤。詳細: {failed_suites[0].get('id')}"
                    recommended_next_steps = "請交接給 Data Audit Agent 稽核相關資料新鮮度、Available Date 及 SQLite Schema。"
                elif has_ui_match or has_ui_error:
                    status = "failed"
                    likely_owner = "execution"
                    evidence_summary = f"測試套件失敗。偵測到 UI/元件/斷言相關錯誤。詳細: {failed_suites[0].get('id')}"
                    recommended_next_steps = "請交接給 Execution Agent 修復 UI 排版、元件可見性或對話框綁定邏輯。"
                elif has_manual_gap_match:
                    status = "failed"
                    likely_owner = "testing_qa"
                    evidence_summary = f"測試套件失敗。對應已知手動測試缺口。詳細: {failed_suites[0].get('id')}"
                    recommended_next_steps = "保留為 manual gap，不可自動標記為通過；由 Testing / QA Agent 彙整缺口與後續人工驗證。"
                else:
                    status = "failed"
                    likely_owner = "execution"
                    evidence_summary = f"測試套件失敗，原因未知。詳細: {failed_suites[0].get('id')}"
                    recommended_next_steps = "請交接給 Execution Agent 排查 stderr 錯誤資訊。"

                if known_issue_summary:
                    evidence_summary = f"{evidence_summary} 已知問題: {known_issue_summary}"
                    recommended_next_steps = f"{recommended_next_steps} 已知問題建議: {known_issue_recommendations}"

        feature_results[fid] = FeatureInterpretation(
            feature_id=fid,
            display_name=route.display_name,
            status=status,
            matched_suite_ids=matched_suite_ids_by_feature[fid],
            failed_suite_ids=failed_suite_ids_by_feature[fid],
            evidence_summary=evidence_summary,
            likely_owner=likely_owner,
            recommended_next_steps=recommended_next_steps,
            known_gaps=list(route.known_gaps),
        )

    # 4. 判定整體狀態與收集 summaries
    overall_status = "passed"
    statuses = [fr.status for fr in feature_results.values()]
    runner_has_failure = bool(runner_failures)
    if "failed" in statuses or runner_has_failure:
        overall_status = "failed"
    elif "needs_data_audit" in statuses:
        overall_status = "needs_data_audit"
    elif all(s == "not_run" for s in statuses):
        overall_status = "not_run"
    elif "partial" in statuses:
        overall_status = "partial"
    elif result.status == "failed":
        overall_status = "failed"

    # 收集 Data Audit 推薦
    data_audit_recommendations: list[str] = []
    for fid, fr in feature_results.items():
        if fr.status == "needs_data_audit":
            route = FEATURE_ROUTES[fid]
            for trigger in route.data_audit_triggers:
                if trigger not in data_audit_recommendations:
                    data_audit_recommendations.append(trigger)

    # 收集 Manual Gaps
    manual_gaps: list[str] = []
    for fid, fr in feature_results.items():
        # 已知 gap 均可放入 manual_gaps 中
        for gap in fr.known_gaps:
            if gap not in manual_gaps:
                manual_gaps.append(gap)

    return HealthcheckInterpretation(
        overall_status=overall_status,
        mode=result.mode,
        feature_results=feature_results,
        runner_failures=runner_failures,
        data_audit_recommendations=data_audit_recommendations,
        manual_gaps=manual_gaps,
    )


def interpret_healthcheck_json(path: Path) -> HealthcheckInterpretation:
    """讀取 reporting 輸出的 JSON 報告並解讀。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    steps: list[StepResult] = []
    for step_data in data.get("steps", []):
        steps.append(
            StepResult(
                id=step_data.get("id"),
                title=step_data.get("title"),
                status=step_data.get("status"),
                evidence=step_data.get("evidence", {}),
            )
        )

    result = HealthcheckResult(
        run_id=data.get("run_id"),
        mode=HealthcheckMode(data.get("mode")),
        status=data.get("status"),
        steps=tuple(steps),
    )
    return interpret_healthcheck_result(result)


def _markdown_table_cell(value: object) -> str:
    """Escape minimal Markdown table syntax while preserving readable report text."""
    return str(value).replace("\n", "<br>").replace("|", "\\|")


def render_interpretation_markdown(interpretation: HealthcheckInterpretation) -> str:
    """將 HealthcheckInterpretation 轉譯為易於閱讀的繁體中文 Markdown 報告。"""
    status_map = {
        "passed": "通過 (passed)",
        "failed": "失敗 (failed)",
        "not_run": "未運行 (not_run)",
        "needs_data_audit": "需要資料審計 (needs_data_audit)",
        "partial": "部分通過 (partial)"
    }

    overall_status_zh = status_map.get(interpretation.overall_status, interpretation.overall_status)
    mode_zh = "快速檢查 (QUICK)" if interpretation.mode == HealthcheckMode.QUICK else "完整檢查 (FULL)"

    lines = [
        "# Healthcheck 測試解讀報告",
        "",
        f"- **檢查模式**: {mode_zh}",
        f"- **總體狀態**: `{overall_status_zh}`",
        "",
        "## 功能檢驗結果",
        "",
        "| 功能名稱 | 狀態 | 建議歸屬角色 | 執行套件數 | 失敗套件數 |",
        "|---|---|---|---|---|",
    ]

    for fid, fr in interpretation.feature_results.items():
        status_zh = status_map.get(fr.status, fr.status)
        matched_cnt = len(fr.matched_suite_ids)
        failed_cnt = len(fr.failed_suite_ids)
        display_name = _markdown_table_cell(fr.display_name)
        likely_owner = _markdown_table_cell(fr.likely_owner)
        lines.append(f"| {display_name} | `{status_zh}` | `{likely_owner}` | {matched_cnt} | {failed_cnt} |")

    lines.append("")
    lines.append("## 功能解讀與行動指南")
    lines.append("")

    for fid, fr in interpretation.feature_results.items():
        if fr.status == "not_run" and interpretation.mode == HealthcheckMode.QUICK and fr.evidence_summary == "該功能不支援 Quick Mode，測試未運行":
            continue

        lines.append(f"### {fr.display_name}")
        lines.append(f"- **狀態**: `{status_map.get(fr.status, fr.status)}` (責任人: `{fr.likely_owner}`)")
        lines.append(f"- **證據摘要**: {fr.evidence_summary}")
        lines.append(f"- **建議下一步**: {fr.recommended_next_steps}")
        if fr.matched_suite_ids:
            lines.append(f"- **關聯測試套件**: {', '.join(fr.matched_suite_ids)}")
        if fr.failed_suite_ids:
            lines.append(f"- **失敗測試套件**: `{', '.join(fr.failed_suite_ids)}`")
        lines.append("")

    if interpretation.data_audit_recommendations:
        lines.append("## Data Audit 建議稽核項目")
        lines.append("")
        for rec in interpretation.data_audit_recommendations:
            lines.append(f"- [ ] {rec}")
        lines.append("")

    if interpretation.manual_gaps:
        lines.append("## 已知手動測試缺口 (Manual Gaps)")
        lines.append("")
        for gap in interpretation.manual_gaps:
            lines.append(f"- {gap}")
        lines.append("")

    handoff_recommendations = build_handoff_recommendations(interpretation)
    lines.append("## Handoff Recommendations")
    lines.append("")
    lines.append(render_handoff_markdown(handoff_recommendations))
    lines.append("")

    if interpretation.runner_failures:
        lines.append("## 執行器異常或未識別套件 (Runner Failures)")
        lines.append("")
        for fail in interpretation.runner_failures:
            lines.append(f"- **套件 ID**: `{fail.get('id')}`")
            lines.append(f"  - **錯誤原因**: {fail.get('error')}")
            suite = fail.get("suite", {})
            if suite and suite.get("returncode") is not None:
                lines.append(f"  - **回傳碼**: `{suite.get('returncode')}`")
        lines.append("")

    return "\n".join(lines)
