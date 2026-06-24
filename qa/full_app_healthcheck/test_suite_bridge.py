from __future__ import annotations

from dataclasses import dataclass

from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.test_inventory import is_allowed_in_bridge


# python command
PYTHON = ".\\.venv\\Scripts\\python.exe"


@dataclass(frozen=True)
class ExistingSuite:
    id: str
    title: str
    modes: tuple[HealthcheckMode, ...]
    command: tuple[str, ...]
    non_destructive: bool
    path: str = ""  # Path relative to project root. Empty for non-test scripts.
    covered_healthcheck_ids: tuple[str, ...] = ()
    covered_flow_ids: tuple[str, ...] = ()


def build_existing_suite_registry() -> tuple[ExistingSuite, ...]:
    registry = (
        ExistingSuite(
            id="ui-update-workbench",
            title="既有 UpdateView widget / contract 測試",
            modes=(HealthcheckMode.QUICK, HealthcheckMode.FULL),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_update_view_workbench.py", "-q", "-o", "addopts="),
            non_destructive=True,
            path="tests/test_ui_qt_update_view_workbench.py",
        ),
        ExistingSuite(
            id="ui-decision-desk",
            title="既有 Daily Decision Desk UI 測試",
            modes=(HealthcheckMode.QUICK, HealthcheckMode.FULL),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_decision_desk_view.py", "-q", "-o", "addopts="),
            non_destructive=True,
            path="tests/test_ui_qt_decision_desk_view.py",
        ),
        ExistingSuite(
            id="ui-research-workflow",
            title="既有 Research Lab / Recommendation / Watchlist 跨頁 workflow 測試",
            modes=(HealthcheckMode.FULL,),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_research_workflow.py", "-q", "-o", "addopts="),
            non_destructive=True,
            path="tests/test_ui_qt_research_workflow.py",
            covered_healthcheck_ids=("B-004", "B-005", "B-038", "B-039", "B-041", "X-004"),
            covered_flow_ids=("research-validation-loop",),
        ),
        ExistingSuite(
            id="ui-market-regime-view",
            title="既有 Market Regime 規則匹配度 / tooltip UI 測試",
            modes=(HealthcheckMode.FULL,),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_market_regime_view.py", "-q", "-o", "addopts="),
            non_destructive=True,
            path="tests/test_ui_qt_market_regime_view.py",
            covered_healthcheck_ids=("M-001", "M-002", "MARKET-ISSUE-002"),
            covered_flow_ids=("data-market-state-loop",),
        ),
        ExistingSuite(
            id="ui-run-registry-compare",
            title="既有 Research Registry 比較頁 UI 測試",
            modes=(HealthcheckMode.FULL,),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_run_registry_compare.py", "-q", "-o", "addopts="),
            non_destructive=True,
            path="tests/test_ui_qt_run_registry_compare.py",
            covered_healthcheck_ids=("B-039", "B-041", "BACKTEST-ISSUE-021"),
            covered_flow_ids=("research-validation-loop",),
        ),
        ExistingSuite(
            id="ui-smart-money-flow",
            title="既有 Smart Money Flow UI 測試",
            modes=(HealthcheckMode.FULL,),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_smart_money_flow_view.py", "-q", "-o", "addopts="),
            non_destructive=True,
            path="tests/test_ui_qt_smart_money_flow_view.py",
            covered_healthcheck_ids=("M-017", "M-019", "M-022", "MARKET-ISSUE-004", "MARKET-ISSUE-005"),
            covered_flow_ids=("data-market-state-loop", "portfolio-check-loop"),
        ),
        ExistingSuite(
            id="qa-update-tab",
            title="既有 Data Update Tab QA script",
            modes=(HealthcheckMode.FULL,),
            command=(PYTHON, "scripts\\qa_validate_update_tab.py"),
            non_destructive=True,
            path="",  # QA script, not part of test inventory.
            covered_healthcheck_ids=("U-001", "U-006", "U-020", "UPDATE-ISSUE-030", "UPDATE-ISSUE-031"),
            covered_flow_ids=("data-market-state-loop",),
        ),
    )

    for suite in registry:
        # Enforce that pytest files are registered in direct bridge allowlist
        if suite.path and suite.path.startswith("tests/"):
            if not is_allowed_in_bridge(suite.path):
                raise ValueError(f"測試檔案 {suite.path} 不在 direct bridge 允許清冊中，禁止橋接。")

    return registry


def suites_for_mode(mode: HealthcheckMode) -> tuple[ExistingSuite, ...]:
    suites = tuple(suite for suite in build_existing_suite_registry() if mode in suite.modes)
    unsafe = [suite.id for suite in suites if not suite.non_destructive]
    if unsafe:
        raise ValueError(f"非破壞 runner 不可呼叫會寫資料的既有測試: {', '.join(unsafe)}")
    return suites
