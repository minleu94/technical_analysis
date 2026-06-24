from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.test_inventory import get_category


FORBIDDEN_OFFSCREEN_TERMS = frozenset(
    {"mainwindow", "write-risk", "migration", "backfill", "external fetch", "high-risk", "dry-run"}
)
FORBIDDEN_EVIDENCE_CATEGORIES = frozenset(
    {"write-risk-dry-run-required", "manual-only", "legacy-or-low-priority", "slow-e2e-or-environment"}
)


@dataclass(frozen=True)
class OffscreenWidgetCheck:
    check_id: str
    feature_id: str
    target_widget: str
    purpose: str
    assertion_scope: tuple[str, ...]
    safe_qtest_actions: tuple[str, ...]
    evidence_sources: tuple[str, ...]
    non_destructive: bool
    requires_main_window: bool = False

    def __post_init__(self) -> None:
        if self.feature_id not in FEATURE_ROUTES:
            raise ValueError(f"Unknown feature_id '{self.feature_id}' for OffscreenWidgetCheck '{self.check_id}'.")
        if not self.non_destructive:
            raise ValueError(f"OffscreenWidgetCheck '{self.check_id}' must be non-destructive.")
        if self.requires_main_window:
            raise ValueError(f"OffscreenWidgetCheck '{self.check_id}' must not require MainWindow.")

        searchable_text = " ".join(
            (
                self.check_id,
                self.feature_id,
                self.target_widget,
                self.purpose,
                *self.assertion_scope,
                *self.safe_qtest_actions,
                *self.evidence_sources,
            )
        ).lower()
        for term in FORBIDDEN_OFFSCREEN_TERMS:
            if term in searchable_text:
                raise ValueError(
                    f"OffscreenWidgetCheck '{self.check_id}' contains forbidden D-1 term '{term}'."
                )

        for source in self.evidence_sources:
            if source.startswith("tests/"):
                category = get_category(source)
                if category is None:
                    raise ValueError(
                        f"OffscreenWidgetCheck '{self.check_id}' references unknown evidence source '{source}'."
                    )
                if category in FORBIDDEN_EVIDENCE_CATEGORIES:
                    raise ValueError(
                        f"OffscreenWidgetCheck '{self.check_id}' references forbidden evidence category "
                        f"'{category}' via '{source}'."
                    )


WIDGET_CHECKS: tuple[OffscreenWidgetCheck, ...] = (
    OffscreenWidgetCheck(
        check_id="ui_check_update_view_status",
        feature_id="update_view",
        target_widget="UpdateView",
        purpose="Verify the visibility of daily data status checklist labels and refresh triggers.",
        assertion_scope=("Label visibility check", "Data overview values format", "Confirm sync dialogue mock check"),
        safe_qtest_actions=("QTest.mouseClick on Refresh Button", "QTest.keyClicks for Sync DateEdit fields"),
        evidence_sources=("tests/test_ui_qt_update_view_workbench.py",),
        non_destructive=True,
        requires_main_window=False,
    ),
    OffscreenWidgetCheck(
        check_id="ui_check_decision_desk_snapshot",
        feature_id="decision_desk",
        target_widget="DecisionDeskView",
        purpose="Check risk warning panel warnings count and color indicators for watchlist updates.",
        assertion_scope=("Watchlist quality indicator color", "Risk prompt warning count match", "Attribution labels layout"),
        safe_qtest_actions=("QTest.mouseClick on sector focus cards",),
        evidence_sources=("tests/test_ui_qt_decision_desk_view.py",),
        non_destructive=True,
        requires_main_window=False,
    ),
    OffscreenWidgetCheck(
        check_id="ui_check_research_lab_params",
        feature_id="research_lab",
        target_widget="ResearchWorkflowWidget",
        purpose="Verify parameter input forms and strategy config sliders are properly constructed offscreen.",
        assertion_scope=("Config list item counts", "Mock backtest run initiation contract"),
        safe_qtest_actions=("QTest.keyClicks on strategy name QLineEdit", "QTest.mouseClick on Reset button"),
        evidence_sources=("tests/test_ui_qt_research_workflow.py", "tests/test_ui_qt_research_lab_mode_driven_ui.py"),
        non_destructive=True,
        requires_main_window=False,
    ),
    OffscreenWidgetCheck(
        check_id="ui_check_market_regime_display",
        feature_id="market_regime",
        target_widget="MarketRegimeView",
        purpose="Verify regime match MA table columns and tooltip rendering offscreen.",
        assertion_scope=("MA cross table cell values format", "Regime breakdown dropdown listing"),
        safe_qtest_actions=("QTest.mouseClick on regime breakdown dropdown",),
        evidence_sources=("tests/test_ui_qt_market_regime_view.py",),
        non_destructive=True,
        requires_main_window=False,
    ),
    OffscreenWidgetCheck(
        check_id="ui_check_smart_money_broker_flows",
        feature_id="smart_money",
        target_widget="SmartMoneyFlowView",
        purpose="Check that broker flows list columns and sorting triggers operate offscreen.",
        assertion_scope=("Broker transaction list size and unit columns", "Multi-day sorting order check"),
        safe_qtest_actions=("QTest.mouseClick on Buy/Sell column headers to trigger sort",),
        evidence_sources=("tests/test_ui_qt_smart_money_flow_view.py",),
        non_destructive=True,
        requires_main_window=False,
    ),
    OffscreenWidgetCheck(
        check_id="ui_check_registry_compare_canvas",
        feature_id="registry_compare",
        target_widget="RunRegistryCompareView",
        purpose="Validate strategy normalized comparison chart rendering and table row counts.",
        assertion_scope=("Chart canvas geometry boundary checking", "Horizontal comparison table parameters format"),
        safe_qtest_actions=("QTest.mouseClick on run checklist check-boxes",),
        evidence_sources=("tests/test_ui_qt_run_registry_compare.py",),
        non_destructive=True,
        requires_main_window=False,
    ),
)


def get_all_offscreen_widget_checks() -> tuple[OffscreenWidgetCheck, ...]:
    """取得所有內建的 OffscreenWidgetCheck 指南。"""
    return WIDGET_CHECKS


def get_offscreen_widget_checks_for_feature(feature_id: str) -> tuple[OffscreenWidgetCheck, ...]:
    """取得特定 feature_id 的 OffscreenWidgetCheck 列表。"""
    return tuple(check for check in WIDGET_CHECKS if check.feature_id == feature_id)


def render_offscreen_widget_checks_markdown(checks: Sequence[OffscreenWidgetCheck]) -> str:
    """將 OffscreenWidgetCheck 列表渲染為 Markdown 格式。"""
    if not checks:
        return "- (None)"

    lines = []
    for check in checks:
        scopes = ", ".join(f"`{s}`" for s in check.assertion_scope)
        actions = ", ".join(f"`{action}`" for action in check.safe_qtest_actions)
        evidences = ", ".join(f"`{e}`" for e in check.evidence_sources)
        lines.append(
            f"- **Check ID**: `{check.check_id}` (Feature: `{check.feature_id}`, Widget: `{check.target_widget}`)\n"
            f"  - *Purpose*: {check.purpose}\n"
            f"  - *Assertion Scope*: {scopes}\n"
            f"  - *Safe QTest Actions*: {actions or 'None'}\n"
            f"  - *Evidence Sources*: {evidences}"
        )
    return "\n".join(lines)
