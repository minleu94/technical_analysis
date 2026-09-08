import os
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QApplication, QBoxLayout, QWidget

from app_module.workbench_dtos import (
    WorkbenchAccessBoundary,
    WorkbenchActionItem,
    WorkbenchChecklistItem,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceFeedItem,
    WorkbenchEvidenceSummary,
    WorkbenchOperatingLoopStep,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)
from app_module.engineering_closure_dashboard_service import (
    EngineeringClosureDashboardService,
    EvidenceRehearsalDashboard,
)
from app_module.evidence_rehearsal_dtos import (
    CoverageMetric,
    EvidenceRehearsalReport,
    EvidenceRehearsalScenario,
    RehearsalArtifact,
)
from app_module.advice_dtos import (
    AdviceAction,
    AdviceDashboardDTO,
    AdviceMode,
    AdvicePolicyConfig,
    RecommendationAdviceDTO,
)
from ui_qt.models.workbench_table_models import (
    WorkbenchActionItemTableModel,
    WorkbenchEvidenceFeedTableModel,
    WorkbenchEvidenceTableModel,
    WorkbenchOperatingLoopTableModel,
)
from ui_qt.views.workbench_view import UnifiedDecisionWorkbenchView
from ui_qt.views.research_console_view import ResearchConsoleView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_evidence_subtab_hosts_read_only_research_console() -> None:
    app()
    view = UnifiedDecisionWorkbenchView(auto_refresh=False)

    evidence_page = view.subtabs.widget(2)
    assert isinstance(evidence_page, ResearchConsoleView)
    assert evidence_page.visible_text().count("formal_oos_allowed = False") == 1


def _dashboard_with_replay() -> WorkbenchDashboardDTO:
    return WorkbenchDashboardDTO(
        as_of_date=date(2026, 7, 6),
        generated_at=datetime(2026, 7, 6, 12, 0, 0),
        source_mode="read_only_sources_plus_historical_replay",
        access_boundary=WorkbenchAccessBoundary(),
        status_strip=(
            WorkbenchStatusItem(
                item_id="decision_snapshot",
                label="Daily Decision snapshot",
                value="2026-07-06",
                status="observed",
                summary="Read from WorkbenchSourceService.",
            ),
            WorkbenchStatusItem(
                item_id="evidence_gate",
                label="Evidence gate",
                value="waiting_for_time",
                status="info",
            ),
            WorkbenchStatusItem(
                item_id="scheduler",
                label="Production Scheduler",
                value="off",
                status="blocked",
                summary="production_scheduler_allowed=false",
            ),
        ),
        review_items=(
            WorkbenchReviewItem(
                item_id="watchlist_trigger",
                title="Watchlist trigger review",
                severity="warning",
                source="watchlist_trigger",
                summary="Human review required; no buy/sell recommendation is generated.",
                drilldown_target="evidence_mode",
                code="2603",
            ),
        ),
        evidence_summary=(
            WorkbenchEvidenceSummary(
                item_id="weekly_history",
                label="Weekly evidence operations history",
                status="waiting_for_time",
                summary="0/3 records observed.",
                diagnostics=("insufficient_weekly_history_records",),
            ),
            WorkbenchEvidenceSummary(
                item_id="historical_replay",
                label="Historical replay simulated evidence",
                status="degraded",
                summary=(
                    "118 days / 118056 events / 472224 outcomes; "
                    "source gap disclosed; payload gap disclosed; benchmark coverage disclosed."
                ),
                diagnostics=(
                    "simulated_scheduler",
                    "source_gap:source_missing_screening_matrix",
                    "source_gap_coverage:source_missing_screening_matrix=118/118",
                    "payload_gap:missing_industry_benchmark",
                    "outcome_maturity:ready=380736,pending_future_data=91488",
                    "benchmark_coverage:covered=380736,total=380736,missing=0",
                    "industry_benchmark_coverage:covered=2245,total=380736,missing=378491",
                    "missing_industry_benchmark:378491",
                    "pending_future_data:91488",
                    "replay_direction_assessment:market_benchmark_ready_but_industry_and_source_gaps_block_production_readiness",
                    "phase0_gate_not_satisfied:weekly_history_and_multi_day_dry_run_require_real_time_accumulation",
                ),
            ),
        ),
        market_context={"source_status": "ready", "overall_quality": "observed"},
        portfolio_watchlist_summary={"source_status": "ready"},
        daily_checklist=(
            WorkbenchChecklistItem(
                item_id="weekly_history",
                label="Phase 0 weekly history",
                status="waiting_for_time",
                summary="0/3; must accumulate in real time.",
            ),
            WorkbenchChecklistItem(
                item_id="multi_day_dry_run",
                label="Multi-day dry-run",
                status="waiting_for_time",
                summary="1/3; replay cannot replace this gate.",
            ),
            WorkbenchChecklistItem(
                item_id="scheduler_off",
                label="Scheduler write-mode",
                status="blocked",
                summary="Production scheduler remains off.",
            ),
        ),
        warnings=(
            "historical_replay / simulated_scheduler only supports design review.",
            "replay does not satisfy Phase 0 weekly or multi-day gates.",
            "degraded_source:decision_desk_snapshot_db_missing",
        ),
        background_evidence_feed=(
            WorkbenchEvidenceFeedItem(
                item_id="daily_decision_snapshot",
                label="Daily Decision snapshot",
                status="observed",
                summary="Snapshot payload already supplied by WorkbenchDashboardDTO.",
                source_trace="DecisionDeskSnapshot",
                degraded_reason="none",
                drilldown_target="daily_decision",
            ),
            WorkbenchEvidenceFeedItem(
                item_id="replay_summary_diagnostics",
                label="Replay summary diagnostics",
                status="degraded",
                summary="Replay summary exposes simulated scheduler and payload gaps.",
                source_trace="HistoricalReplaySummary",
                degraded_reason="missing_industry_benchmark",
                drilldown_target="evidence_review",
                diagnostics=("simulated_scheduler", "missing_industry_benchmark"),
            ),
        ),
        action_items=(
            WorkbenchActionItem(
                item_id="portfolio_alert_2330",
                title="Portfolio alert manual review",
                source_type="portfolio_alert",
                severity="warning",
                summary="Human review required; no action is applied.",
                source_trace="DecisionDeskSnapshot.portfolio_alerts",
                degraded_reason="portfolio_alert_requires_manual_review",
                drilldown_target="portfolio_review",
                code="2330",
            ),
        ),
        operating_loop_steps=(
            WorkbenchOperatingLoopStep(
                step_id="daily_start",
                label="每日先看",
                cadence="daily",
                status="manual_required",
                summary="今天先看 1 筆 review item；只讀，不寫 DB。",
                source_trace="WorkbenchDashboardDTO.review_items",
                linked_item_ids=("watchlist_trigger",),
                drilldown_target="daily_decision",
                guidance="先判讀今日待判讀與背景證據流。",
            ),
            WorkbenchOperatingLoopStep(
                step_id="manual_queue",
                label="人工處理佇列",
                cadence="daily",
                status="manual_required",
                summary="目前有 1 筆 Action Item 需要人工覆盤；不標記完成。",
                source_trace="WorkbenchDashboardDTO.action_items",
                linked_item_ids=("portfolio_alert_2330",),
                drilldown_target="portfolio_review",
                guidance="只檢查 source trace 與 degraded reason。",
            ),
            WorkbenchOperatingLoopStep(
                step_id="multi_day_dry_run",
                label="多日 dry-run",
                cadence="daily_until_3",
                status="waiting_for_time",
                summary="1/3；等待真實時間累積，replay 不可補齊。",
                source_trace="PreV2ReadinessReport.items.multi_day_dry_run",
                linked_item_ids=("multi_day_dry_run",),
                drilldown_target="evidence_review",
                guidance="只確認紀錄節奏，不執行 replay。",
            ),
            WorkbenchOperatingLoopStep(
                step_id="manual_review_note",
                label="人工覆盤註記",
                cadence="after_manual_review",
                status="manual_required",
                summary="手動在既有流程留下 note；Workbench 不寫 DB、不標記完成。",
                source_trace="WorkbenchDashboardDTO.daily_checklist.manual_review_note",
                linked_item_ids=("manual_review_note",),
                drilldown_target="evidence_review",
                guidance="需要 note 時下鑽到既有頁面處理。",
            ),
        ),
    )


def _empty_dashboard() -> WorkbenchDashboardDTO:
    return WorkbenchDashboardDTO(
        as_of_date=date(2026, 7, 6),
        generated_at=datetime(2026, 7, 6, 12, 0, 0),
        source_mode="read_only_sources",
        access_boundary=WorkbenchAccessBoundary(),
        status_strip=(
            WorkbenchStatusItem(
                item_id="scheduler",
                label="Production Scheduler",
                value="off",
                status="blocked",
                summary="production_scheduler_allowed=false",
            ),
        ),
        review_items=(),
        evidence_summary=(),
        market_context={"source_status": "missing"},
        portfolio_watchlist_summary={"source_status": "missing"},
        daily_checklist=(
            WorkbenchChecklistItem(
                item_id="scheduler_off",
                label="Scheduler write-mode",
                status="blocked",
                summary="Production scheduler remains off.",
            ),
        ),
        warnings=(),
        background_evidence_feed=(),
        action_items=(),
    )


class _FakeWorkbenchSourceService:
    def __init__(self, dashboard: WorkbenchDashboardDTO) -> None:
        self.dashboard = dashboard
        self.calls: list[dict[str, object]] = []

    def inspect(self, **kwargs):
        self.calls.append(kwargs)
        return self.dashboard


class _FlakyWorkbenchSourceService:
    def __init__(self, dashboard: WorkbenchDashboardDTO) -> None:
        self.dashboard = dashboard
        self.calls = 0

    def inspect(self, **kwargs):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError()
        return self.dashboard


class _AlwaysFailWorkbenchSourceService:
    def inspect(self, **kwargs):
        raise RuntimeError()


def test_workbench_evidence_table_model_has_no_diagnostics_column() -> None:
    app()
    replay = _dashboard_with_replay().evidence_summary[1]
    model = WorkbenchEvidenceTableModel((replay,))

    assert model.rowCount() == 1
    visible_fields = tuple(field for field, _label in model.COLUMNS)
    assert visible_fields == ("label", "status", "summary")


def test_workbench_refresh_preserves_last_good_dashboard_as_stale_and_focuses_retry() -> None:
    app()
    dashboard = _dashboard_with_replay()
    view = UnifiedDecisionWorkbenchView(
        source_service=_FlakyWorkbenchSourceService(dashboard),
        dashboard=dashboard,
        auto_refresh=False,
    )

    view.refresh_dashboard()
    view.refresh_dashboard()

    assert view._dashboard is dashboard
    assert view.review_model.rowCount() == 1
    assert "stale" in view.priority_banner.text()
    assert "最後成功載入" in view.priority_banner.text()
    assert "不把舊資料當成 current" in view.priority_banner.text()
    assert "workbench_source_stale" in view.warning_list.toPlainText()
    assert view.refresh_button.focusPolicy().value != 0


def test_workbench_initial_refresh_failure_is_unknown_and_does_not_claim_human_review() -> None:
    app()
    view = UnifiedDecisionWorkbenchView(
        source_service=_AlwaysFailWorkbenchSourceService(),
        auto_refresh=False,
    )

    view.refresh_dashboard()

    assert "狀態未知" in view.boundary_banner.text()
    assert "不能推定需要人工" in view.action_item_state_label.text()
    assert view.review_model.rowCount() == 0



def test_workbench_action_item_table_model_is_compact_but_keeps_raw_detail() -> None:
    app()
    action = _dashboard_with_replay().action_items[0]
    model = WorkbenchActionItemTableModel((action,))
    visible_fields = tuple(field for field, _label in model.COLUMNS)

    assert visible_fields == ("queue_group", "severity", "source_label", "title", "summary")
    assert model.rowCount() == 1
    assert model.data(model.index(0, model.column_index("severity"))) == "警告"
    assert model.data(model.index(0, model.column_index("title"))) == "Portfolio alert manual review"
    assert model.raw_value(0, "source_trace") == "DecisionDeskSnapshot.portfolio_alerts"
    assert model.raw_value(0, "degraded_reason") == "portfolio_alert_requires_manual_review"
    assert model.raw_value(0, "drilldown_target") == "portfolio_review"


def test_workbench_evidence_feed_table_model_is_compact_but_keeps_raw_detail() -> None:
    app()
    feed_item = _dashboard_with_replay().background_evidence_feed[1]
    model = WorkbenchEvidenceFeedTableModel((feed_item,))
    visible_fields = tuple(field for field, _label in model.COLUMNS)

    assert visible_fields == ("label", "status", "summary")
    assert model.rowCount() == 1
    assert model.data(model.index(0, model.column_index("status"))) == "降級"
    assert model.row_at(0).source_trace == "HistoricalReplaySummary"
    assert model.row_at(0).degraded_reason == "missing_industry_benchmark"
    assert model.row_at(0).diagnostics == ("simulated_scheduler", "missing_industry_benchmark")


def test_workbench_table_models_apply_semantic_status_colors() -> None:
    app()
    feed_item = _dashboard_with_replay().background_evidence_feed[1]
    model = WorkbenchEvidenceFeedTableModel((feed_item,))
    status_index = model.index(0, model.column_index("status"))
    summary_index = model.index(0, model.column_index("summary"))

    status_brush = model.data(status_index, Qt.ForegroundRole)
    row_background = model.data(summary_index, Qt.BackgroundRole)

    assert isinstance(status_brush, QBrush)
    assert status_brush.color() == QColor("#f59e0b")
    assert isinstance(row_background, QBrush)
    assert row_background.color() == QColor("#221a10")
    assert model.data(status_index, Qt.FontRole).bold() is True


def test_workbench_operating_loop_table_model_exposes_read_only_rhythm() -> None:
    app()
    step = _dashboard_with_replay().operating_loop_steps[1]
    model = WorkbenchOperatingLoopTableModel((step,))

    assert model.rowCount() == 1
    assert model.headerData(model.column_index("cadence"), Qt.Horizontal, Qt.DisplayRole) == "節奏"
    assert model.data(model.index(0, model.column_index("status"))) == "需要人工覆盤"
    assert "portfolio_alert_2330" in model.data(model.index(0, model.column_index("linked_item_ids")))
    assert model.data(model.index(0, model.column_index("drilldown_target"))) == "持倉覆盤"
    assert model.raw_value(0, "write_intent") is False


def test_unified_workbench_view_renders_read_only_mvp_shell_and_replay_limits() -> None:
    app()
    clicked: list[str] = []
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
        navigate_to_daily_decision_callback=lambda: clicked.append("daily"),
        navigate_to_evidence_review_callback=lambda: clicked.append("evidence"),
        navigate_to_portfolio_callback=lambda: clicked.append("portfolio"),
    )

    assert view.status_model.rowCount() == 3
    assert view.review_model.rowCount() == 1
    assert view.evidence_feed_model.rowCount() == 2
    assert view.action_item_model.rowCount() == 1
    assert view.operating_loop_model.rowCount() == 4
    assert view.evidence_model.rowCount() == 2
    assert view.checklist_model.rowCount() == 3
    assert "唯讀邊界" in view.boundary_banner.text()
    assert "不是交易建議" in view.boundary_banner.text()
    assert "不重算 scoring" in view.boundary_banner.text()
    assert view.summary_value_labels["review"].text() == "1 筆"
    assert view.summary_value_labels["action"].text() == "1 筆"
    assert view.summary_value_labels["waiting"].text() == "2 項"
    assert view.summary_value_labels["warning"].text() == "3 則"
    assert "weekly history 0/3" in view.summary_detail_labels["waiting"].text()
    assert "multi-day dry-run 1/3" in view.summary_detail_labels["waiting"].text()
    overview_margins = view.overview_layout.contentsMargins()
    assert overview_margins.left() >= 12
    assert overview_margins.top() >= 12
    assert "狀態列" in view.status_section_title.text()
    assert "今日待判讀" in view.review_section_title.text()
    assert "背景證據流" in view.evidence_feed_section_title.text()
    assert "只讀 Action Items" in view.action_item_section_title.text()
    assert "操作節奏" in view.operating_loop_section_title.text()
    assert "證據與品質" in view.evidence_section_title.text()
    assert "每日檢查清單" in view.checklist_section_title.text()
    assert [view.subtabs.tabText(i) for i in range(view.subtabs.count())] == [
        "總覽",
        "決策來源",
        "Evidence",
        "持倉追蹤",
        "操作節奏",
    ]
    assert view.select_subtab("決策來源") is True
    assert view.subtabs.tabText(view.subtabs.currentIndex()) == "決策來源"
    assert view.daily_decision_button.text() == "開啟市場總覽"
    assert view.evidence_review_button.text() == "開啟證據覆盤"
    assert view.portfolio_button.text() == "開啟持倉管理"
    evidence_page_text = " ".join(
        label.text() for label in view.subtabs.widget(2).findChildren(type(view.boundary_banner))
    )
    assert "Research Console" in evidence_page_text
    assert "formal_oos_allowed = False" in evidence_page_text
    assert "projection_missing" in evidence_page_text

    view.daily_decision_button.click()
    view.evidence_review_button.click()
    view.portfolio_button.click()
    assert clicked == ["daily", "evidence", "portfolio"]

    waiting_tooltip = view.summary_blocks["waiting"].toolTip()
    assert "目前有 2 項仍在等待" in waiting_tooltip
    assert "第 1 週" not in waiting_tooltip
    assert "不可用 fixture" in waiting_tooltip

    boundary_text = view.evidence_boundary_card.value_label.text()
    coverage_text = view.evidence_coverage_card.value_label.text()
    data_quality_text = boundary_text + "\n" + coverage_text

    assert "模擬排程器" in data_quality_text
    assert "來源缺口" in data_quality_text
    assert "payload 缺口" in data_quality_text
    assert "結果成熟度" in data_quality_text
    assert "市場基準覆蓋" in data_quality_text
    assert "產業基準覆蓋" in data_quality_text
    assert "缺產業基準" in data_quality_text
    assert "等待未來資料" in data_quality_text
    assert "方向判讀" in data_quality_text
    assert "Phase 0 每週歷史 0/3" in data_quality_text
    assert "多日 dry-run 1/3" in data_quality_text
    assert "replay 不可取代" in data_quality_text
    assert "降級來源" in view.warning_list.toPlainText()
    loop_text = view.operating_loop_state_label.text()
    assert "今天要看" in loop_text
    assert "人工處理" in loop_text
    assert "等待真實時間累積" in loop_text
    assert "只讀" in loop_text
    assert "不標記完成" in loop_text
    operating_loop_text = " ".join(
        label.text() for label in view.operating_loop_list.findChildren(type(view.boundary_banner))
    )
    assert "需要人工覆盤" in operating_loop_text
    assert "等待真實時間累積" in operating_loop_text
    assert "manual_required" not in operating_loop_text
    assert "waiting_for_time" not in operating_loop_text
    assert "觀察清單觸發" in operating_loop_text
    assert "唯讀邊界" in operating_loop_text
    assert "read-only boundary" not in operating_loop_text

    checklist_text = " ".join(
        label.text() for label in view.checklist_list.findChildren(type(view.boundary_banner))
    )
    assert "封鎖" in checklist_text
    assert "等待真實時間累積" in checklist_text
    assert "blocked" not in checklist_text
    assert "action_required" not in checklist_text
    assert "waiting_for_time" not in checklist_text

    view.warning_list.set_warnings(("source gap warning", "manual waiting"))
    warning_text = " ".join(label.text() for label in view.warning_list.findChildren(type(view.boundary_banner)))
    assert "缺漏來源" in warning_text
    assert "需要人工覆盤" in warning_text
    assert "Missing Source" not in warning_text
    assert "Manual Review Required" not in warning_text


def test_workbench_decision_source_page_is_navigation_only_and_does_not_own_dashboard() -> None:
    app()
    duplicate_dashboard = QWidget()
    duplicate_dashboard.setObjectName("duplicateDecisionDesk")
    clicked: list[str] = []

    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
        decision_source_widget=duplicate_dashboard,
        navigate_to_daily_decision_callback=lambda: clicked.append("market-overview"),
    )

    decision_page = view.subtabs.widget(1)
    page_text = " ".join(
        label.text() for label in decision_page.findChildren(type(view.boundary_banner))
    )
    assert "市場總覽" in page_text
    assert "唯一" in page_text
    assert not hasattr(view, "decision_source_widget")
    assert duplicate_dashboard.parent() is None
    assert view.findChild(QWidget, "duplicateDecisionDesk") is None

    navigation_button = next(
        button
        for button in decision_page.findChildren(type(view.daily_decision_button))
        if button.text() == "開啟市場總覽"
    )
    navigation_button.click()
    assert clicked == ["market-overview"]


def test_unified_workbench_view_renders_blocked_rehearsal_without_ready_claim() -> None:
    app()
    rehearsal_dashboard = EvidenceRehearsalDashboard(
        tier="shadow_comparison",
        status="blocked",
        coverage=(
            CoverageMetric(
                source_id="p0_source",
                total_count=4,
                observed_count=0,
                degraded_count=0,
                missing_count=2,
                future_blocked_count=0,
                immature_label_count=2,
                coverage_bp=0,
            ),
        ),
        blockers=(
            "source_outage:p0_source",
            "insufficient_sample",
            "coverage_missing:p0_source=2",
        ),
    )

    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        evidence_rehearsal_dashboard=rehearsal_dashboard,
        auto_refresh=False,
    )

    rehearsal_text = (
        view.evidence_rehearsal_summary_label.text()
        + "\n"
        + view.evidence_rehearsal_detail_label.text()
    )
    assert "工程／Replay／Shadow；不是 forward evidence" in rehearsal_text
    assert "Shadow comparison：有" in rehearsal_text
    assert "Forward handoff：pending" in rehearsal_text
    assert "source_outage:p0_source" in rehearsal_text
    assert "insufficient_sample" in rehearsal_text
    assert "clean" not in rehearsal_text.lower()
    assert "ready" not in rehearsal_text.lower()
    assert "apply" not in rehearsal_text.lower()
    assert "promote" not in rehearsal_text.lower()


@pytest.mark.parametrize(
    "current_status",
    ("outage", "insufficient", "missing", "degraded", "blocked", "insufficient_sample"),
)
def test_unified_workbench_view_renders_status_only_rehearsal_as_blocked(
    current_status: str,
) -> None:
    app()
    rehearsal_report = EvidenceRehearsalReport(
        scenario=EvidenceRehearsalScenario(
            scenario_id=f"{current_status}-rehearsal",
            decision_date="2026-07-13",
            source_db_path="C:/fixture/source.sqlite",
            working_copy_db_path="C:/fixture/working-copy.sqlite",
            tier="engineering_fixture",
        ),
        artifacts=(
            RehearsalArtifact(
                artifact_id=f"artifact-{current_status}",
                decision_date="2026-07-13",
                available_date="2026-07-13",
                tier="engineering_fixture",
                current_status=current_status,
            ),
        ),
    )
    rehearsal_dashboard = EngineeringClosureDashboardService().compose(rehearsal_report)

    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        evidence_rehearsal_dashboard=rehearsal_dashboard,
        auto_refresh=False,
    )
    rehearsal_text = (
        view.evidence_rehearsal_summary_label.text()
        + "\n"
        + view.evidence_rehearsal_detail_label.text()
    )

    assert rehearsal_dashboard.status == "blocked"
    assert f"artifact_status:{current_status}" in rehearsal_text
    assert "status：已阻擋" in rehearsal_text
    assert "ready" not in rehearsal_text.lower()


def test_unified_workbench_view_renders_injected_advice_without_source_refresh() -> None:
    app()
    advice = AdviceDashboardDTO(
        decision_date="2026-07-06",
        data_as_of_date="2026-07-06",
        mode=AdviceMode.GUIDED,
        policy=AdvicePolicyConfig(),
        recommendations=(
            RecommendationAdviceDTO(
                stock_code="2330",
                advice_action=AdviceAction.NO_NEW_POSITION,
                why_not_reasons=("evidence_quality_missing",),
                data_quality="MISSING",
                execution_feasibility="NOT_FEASIBLE",
            ),
        ),
    )
    view = UnifiedDecisionWorkbenchView(
        dashboard=replace(_dashboard_with_replay(), advice_dashboard=advice),
        auto_refresh=False,
    )

    assert "NO_NEW_POSITION" in view.advice_summary.text()
    assert "evidence_quality_missing" in view.advice_summary.text()
    assert view.advice_recommendation_model.rowCount() == 1


def test_unified_workbench_overview_uses_detail_inspector_and_collapsible_sections() -> None:
    app()
    clicked: list[str] = []
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
        navigate_to_evidence_review_callback=lambda: clicked.append("evidence"),
    )

    assert "詳情檢視" in view.detail_section_title.text()
    assert "Daily Decision snapshot" in view.detail_title_label.text()
    assert "DecisionDeskSnapshot" in view.detail_body_label.text()

    view._show_model_row_detail(view.evidence_feed_model, 1)

    detail_text = view.detail_body_label.text()
    assert "Replay 摘要診斷" in view.detail_title_label.text()
    assert "降級" in view.detail_status_badge.text()
    assert "#f59e0b" in view.detail_status_badge.styleSheet()
    assert "重點摘要" in view.detail_summary_box.text()
    assert "來源與邊界" in view.detail_source_box.text()
    assert "診斷訊號" in view.detail_diagnostics_box.text()
    assert "HistoricalReplaySummary" in detail_text
    assert "缺產業基準" in detail_text
    assert "模擬 排程器" in detail_text or "模擬排程器" in detail_text
    assert "唯讀邊界" in detail_text
    assert "simulated_scheduler" not in detail_text
    assert "missing_industry_benchmark" not in detail_text
    assert "read-only" not in detail_text
    assert view.detail_drilldown_button.isEnabled() is True

    view.detail_drilldown_button.click()
    assert clicked == ["evidence"]

    assert view.evidence_collapsible.is_collapsed() is True
    view.evidence_collapsible.toggle_button.click()
    assert view.evidence_collapsible.is_collapsed() is False
    view.evidence_collapsible.toggle_button.click()
    assert view.evidence_collapsible.is_collapsed() is True


def test_unified_workbench_reflows_narrow_layout_and_expands_dto_fields() -> None:
    app()
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
    )
    view.show()
    app().processEvents()

    view.resize(1366, 768)
    assert view.primary_layout.direction() == QBoxLayout.LeftToRight
    assert view.detail_panel.minimumWidth() == 360

    view.resize(390, 844)
    assert view.primary_layout.direction() == QBoxLayout.TopToBottom
    assert view.detail_panel.minimumWidth() == 0
    assert view.review_table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert view.detail_body_label.isHidden() is True

    view.detail_technical_button.click()
    assert view.detail_body_label.isHidden() is False
    assert "snapshot hash：未知" in view.detail_body_label.text()
    assert "schema 版本：未知" in view.detail_body_label.text()

    view.detail_technical_button.click()
    assert view.detail_body_label.isHidden() is True


def test_unified_workbench_overview_uses_high_contrast_priority_treatments() -> None:
    app()
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
    )

    assert "今日重點" in view.priority_banner.text()
    assert "人工處理 1" in view.priority_banner.text()
    assert "警告 3" in view.priority_banner.text()
    assert "#f59e0b" in view.priority_banner.styleSheet()
    assert "#ef4444" in view.summary_blocks["warning"].styleSheet()
    assert "#38bdf8" in view.summary_blocks["review"].styleSheet()
    assert "font-size: 17px" in view.summary_value_labels["warning"].styleSheet()


def test_unified_workbench_view_displays_empty_and_degraded_queue_state_copy() -> None:
    app()
    empty_view = UnifiedDecisionWorkbenchView(
        dashboard=_empty_dashboard(),
        auto_refresh=False,
    )

    assert "沒有背景證據列" in empty_view.evidence_feed_state_label.text()
    assert "不讀 DB" in empty_view.evidence_feed_state_label.text()
    assert "沒有人工待處理事項" in empty_view.action_item_state_label.text()
    assert "不是買賣建議" in empty_view.action_item_state_label.text()
    assert "不寫 DB" in empty_view.action_item_state_label.text()
    assert "今日所有風險已確認" in empty_view.review_empty_state.title_label.text()
    assert "市場探索" in empty_view.review_empty_state.body_label.text()
    assert empty_view.review_empty_state.isHidden() is False
    assert empty_view.review_table.isHidden() is True

    degraded_view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
    )

    assert "降級" in degraded_view.evidence_feed_state_label.text()
    assert "不補值" in degraded_view.evidence_feed_state_label.text()
    assert "降級" in degraded_view.action_item_state_label.text()
    assert "只供人工覆盤排序" in degraded_view.action_item_state_label.text()
    assert "不是買賣建議" in degraded_view.action_item_state_label.text()


def test_unified_workbench_view_does_not_call_machine_only_gaps_confirmed() -> None:
    app()
    machine_only = replace(
        _empty_dashboard(),
        action_items=(
            WorkbenchActionItem(
                item_id="missing_source",
                title="官方來源缺件",
                source_type="pre_v2_readiness",
                severity="action_required",
                summary="來源尚未提供。",
                source_trace="PreV2ReadinessReport",
                degraded_reason="source_missing_screening_matrix",
                drilldown_target="evidence_review",
                queue_group="evidence_gate",
            ),
        ),
    )

    view = UnifiedDecisionWorkbenchView(dashboard=machine_only, auto_refresh=False)

    assert view.review_model.rowCount() == 0
    assert "機器狀態待處理" in view.review_empty_state.title_label.text()
    assert "不能解讀為風險已確認" in view.review_empty_state.body_label.text()
    assert "人工處理 0" in view.priority_banner.text()


def test_unified_workbench_view_routes_action_item_targets_to_legacy_pages() -> None:
    app()
    clicked: list[str] = []
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
        navigate_to_daily_decision_callback=lambda: clicked.append("daily"),
        navigate_to_evidence_review_callback=lambda: clicked.append("evidence"),
        navigate_to_portfolio_callback=lambda: clicked.append("portfolio"),
    )

    assert view.navigate_to_drilldown_target("portfolio_review") is True
    assert view.navigate_to_drilldown_target("daily_decision") is True
    assert view.navigate_to_drilldown_target("evidence_review") is True
    assert view.navigate_to_drilldown_target("evidence_mode") is True
    assert view.navigate_to_drilldown_target("unknown_target") is False
    assert clicked == ["portfolio", "daily", "evidence", "evidence"]


def test_workbench_review_queue_marks_viewed_in_memory_only() -> None:
    app()
    clicked: list[str] = []
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
        navigate_to_evidence_review_callback=lambda: clicked.append("evidence"),
    )

    view._navigate_model_row(view.review_model, 0)

    assert clicked == ["evidence"]
    assert view.viewed_review_item_ids() == {"watchlist_trigger"}
    assert "已查看 1/1" in view.review_state_label.text()


def test_unified_workbench_view_refreshes_only_through_source_service() -> None:
    app()
    service = _FakeWorkbenchSourceService(_dashboard_with_replay())
    view = UnifiedDecisionWorkbenchView(
        source_service=service,
        decision_date="2026-07-06",
        replay_summary_json=Path("replay_summary.json"),
        auto_refresh=False,
    )

    view.refresh_dashboard()

    assert service.calls == [
        {
            "decision_date": "2026-07-06",
            "replay_summary_json": Path("replay_summary.json"),
        }
    ]
    assert view.evidence_model.rowCount() == 2


def test_workbench_today_action_center_prioritizes_data_and_uses_navigation_only() -> None:
    app()
    clicked: list[str] = []
    view = UnifiedDecisionWorkbenchView(
        dashboard=_empty_dashboard(),
        auto_refresh=False,
        navigate_to_daily_decision_callback=lambda: clicked.append("market"),
        navigate_to_portfolio_callback=lambda: clicked.append("portfolio"),
        navigate_to_update_callback=lambda: clicked.append("update"),
        navigate_to_recommendation_callback=lambda: clicked.append("recommendation"),
    )

    assert view.today_action_title.text() == "今日行動中心"
    assert "資料待確認" in view.today_action_status_labels["data"].text()
    assert view.primary_action_button.text() == "先確認資料狀態"
    assert "不會自動更新資料" in view.today_action_hint_label.text()

    view.primary_action_button.click()
    view.today_action_buttons["advice"].click()

    assert clicked == ["update", "recommendation"]


def test_workbench_today_action_center_prioritizes_existing_portfolio_review() -> None:
    app()
    clicked: list[str] = []
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
        navigate_to_daily_decision_callback=lambda: clicked.append("market"),
        navigate_to_portfolio_callback=lambda: clicked.append("portfolio"),
        navigate_to_update_callback=lambda: clicked.append("update"),
        navigate_to_recommendation_callback=lambda: clicked.append("recommendation"),
    )

    assert "待覆盤 1 項" in view.today_action_status_labels["portfolio"].text()
    assert view.primary_action_button.text() == "先檢查持倉事項"
    assert "只導覽" in view.today_action_hint_label.text()

    view.primary_action_button.click()
    view.today_action_buttons["market"].click()

    assert clicked == ["portfolio", "market"]


def test_workbench_view_does_not_import_db_scheduler_or_domain_calculation_modules() -> None:
    view_source = Path("ui_qt/views/workbench_view.py").read_text(encoding="utf-8")
    model_source = Path("ui_qt/models/workbench_table_models.py").read_text(encoding="utf-8")
    combined = view_source + "\n" + model_source
    blocked_patterns = [
        "sqlite3",
        "data_module.db_manager",
        "app_module.recommendation_service",
        "app_module.backtest_service",
        "app_module.portfolio_service",
        "decision_module.scoring_engine",
        "decision_module.stock_screener",
        "portfolio_module",
        "backtest_module",
        "runtime_scheduler",
        "QTimer",
    ]

    assert "app_module.workbench_dtos" in view_source
    assert "app_module.workbench_source_service" in view_source
    for pattern in blocked_patterns:
        assert pattern not in combined
