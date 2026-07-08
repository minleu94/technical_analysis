import os
import sys
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QApplication

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
from ui_qt.models.workbench_table_models import (
    WorkbenchActionItemTableModel,
    WorkbenchEvidenceFeedTableModel,
    WorkbenchEvidenceTableModel,
    WorkbenchOperatingLoopTableModel,
)
from ui_qt.views.workbench_view import UnifiedDecisionWorkbenchView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


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


def test_workbench_evidence_table_model_exposes_replay_diagnostics() -> None:
    app()
    replay = _dashboard_with_replay().evidence_summary[1]
    model = WorkbenchEvidenceTableModel((replay,))

    assert model.rowCount() == 1
    assert model.headerData(model.column_index("diagnostics"), Qt.Horizontal, Qt.DisplayRole) == "診斷"
    diagnostics = model.data(model.index(0, model.column_index("diagnostics")))
    assert "模擬" in diagnostics
    assert "等待未來資料" in diagnostics
    assert model.raw_value(0, "diagnostics") == replay.diagnostics


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
    assert view.daily_decision_button.text() == "開啟決策來源"
    assert view.evidence_review_button.text() == "開啟證據覆盤"
    assert view.portfolio_button.text() == "開啟持倉管理"
    evidence_page_text = " ".join(
        label.text() for label in view.subtabs.widget(2).findChildren(type(view.boundary_banner))
    )
    assert "摘要與下鑽入口" in evidence_page_text
    assert "預留深挖區" in evidence_page_text

    view.daily_decision_button.click()
    view.evidence_review_button.click()
    view.portfolio_button.click()
    assert clicked == ["daily", "evidence", "portfolio"]

    data_quality_text = view.data_quality_limitations_label.text()
    assert "模擬 scheduler" in data_quality_text
    assert "來源缺口" in data_quality_text
    assert "payload 缺口" in data_quality_text
    assert "結果成熟度" in data_quality_text
    assert "市場基準覆蓋" in data_quality_text
    assert "產業基準覆蓋" in data_quality_text
    assert "缺產業基準" in data_quality_text
    assert "等待未來資料" in data_quality_text
    assert "方向判讀" in data_quality_text
    assert "Phase 0 weekly history 0/3" in data_quality_text
    assert "multi-day dry-run 1/3" in data_quality_text
    assert "replay 不可取代" in data_quality_text
    assert "降級來源" in view.warning_list.toPlainText()
    loop_text = view.operating_loop_state_label.text()
    assert "今天要看" in loop_text
    assert "人工處理" in loop_text
    assert "等待真實時間累積" in loop_text
    assert "只讀" in loop_text
    assert "不標記完成" in loop_text


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
    assert "Replay summary diagnostics" in view.detail_title_label.text()
    assert "降級" in view.detail_status_badge.text()
    assert "#f59e0b" in view.detail_status_badge.styleSheet()
    assert "重點摘要" in view.detail_summary_box.text()
    assert "來源與邊界" in view.detail_source_box.text()
    assert "診斷訊號" in view.detail_diagnostics_box.text()
    assert "HistoricalReplaySummary" in detail_text
    assert "missing_industry_benchmark" in detail_text
    assert "simulated_scheduler" in detail_text
    assert "read-only" in detail_text
    assert view.detail_drilldown_button.isEnabled() is True

    view.detail_drilldown_button.click()
    assert clicked == ["evidence"]

    assert view.evidence_collapsible.is_collapsed() is True
    view.evidence_collapsible.toggle_button.click()
    assert view.evidence_collapsible.is_collapsed() is False
    view.evidence_collapsible.toggle_button.click()
    assert view.evidence_collapsible.is_collapsed() is True


def test_unified_workbench_overview_uses_high_contrast_priority_treatments() -> None:
    app()
    view = UnifiedDecisionWorkbenchView(
        dashboard=_dashboard_with_replay(),
        auto_refresh=False,
    )

    assert "今日重點" in view.priority_banner.text()
    assert "人工處理 1" in view.priority_banner.text()
    assert "Warnings 3" in view.priority_banner.text()
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
