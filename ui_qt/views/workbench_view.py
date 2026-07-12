from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Callable
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app_module.workbench_dtos import (
    WORKBENCH_LEGACY_DRILLDOWN_TARGETS,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceSummary,
)
from app_module.workbench_source_service import WorkbenchSourceService
from app_module.advice_dtos import AdviceClassification
from ui_qt.models.workbench_table_models import (
    AdvicePortfolioTableModel,
    AdviceCandidateTableModel,
    AdviceRecommendationTableModel,
    WorkbenchActionItemTableModel,
    WorkbenchChecklistTableModel,
    WorkbenchEvidenceFeedTableModel,
    WorkbenchEvidenceTableModel,
    WorkbenchOperatingLoopTableModel,
    WorkbenchReviewQueueTableModel,
    WorkbenchStatusStripTableModel,
    display_workbench_value,
)
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.widgets.theme_widgets import (
    CollapsibleSectionPanel,
    EmptyStatePanel,
    SectionPanel,
    WarningList,
    TimelineCard,
    StatusCard,
    MetricCard,
)
from ui_qt.views.workbench_presenter import (
    action_item_state_text as _action_item_state_text,
    evidence_feed_state_text as _evidence_feed_state_text,
    operating_loop_state_text as _operating_loop_state_text,
    review_queue_state_text,
)

WORKBENCH_TONES: dict[str, dict[str, str]] = {
    "ready": {"fg": "#22c55e", "bg": "#0d2116", "border": "#166534"},
    "observed": {"fg": "#22c55e", "bg": "#0d2116", "border": "#166534"},
    "passed": {"fg": "#22c55e", "bg": "#0d2116", "border": "#166534"},
    "done": {"fg": "#22c55e", "bg": "#0d2116", "border": "#166534"},
    "info": {"fg": "#38bdf8", "bg": "#0b1c27", "border": "#075985"},
    "manual_observed": {"fg": "#38bdf8", "bg": "#0b1c27", "border": "#075985"},
    "warning": {"fg": "#f59e0b", "bg": "#221a10", "border": "#92400e"},
    "degraded": {"fg": "#f59e0b", "bg": "#221a10", "border": "#92400e"},
    "waiting_for_time": {"fg": "#f59e0b", "bg": "#221a10", "border": "#92400e"},
    "manual_required": {"fg": "#f59e0b", "bg": "#221a10", "border": "#92400e"},
    "action_required": {"fg": "#f59e0b", "bg": "#221a10", "border": "#92400e"},
    "critical": {"fg": "#ef4444", "bg": "#2a1114", "border": "#991b1b"},
    "blocked": {"fg": "#ef4444", "bg": "#2a1114", "border": "#991b1b"},
    "missing": {"fg": "#ef4444", "bg": "#2a1114", "border": "#991b1b"},
    "off": {"fg": "#94a3b8", "bg": "#111827", "border": "#334155"},
    "neutral": {"fg": "#94a3b8", "bg": "#111827", "border": "#334155"},
}


class UnifiedDecisionWorkbenchView(QWidget):
    """Read-only Unified Decision Workbench shell backed only by Workbench DTOs."""

    def __init__(
        self,
        *,
        source_service: WorkbenchSourceService | None = None,
        dashboard: WorkbenchDashboardDTO | None = None,
        decision_date: str | None = None,
        replay_summary_json: str | Path | None = None,
        auto_refresh: bool = True,
        decision_source_widget: QWidget | None = None,
        navigate_to_daily_decision_callback: Callable[[], None] | None = None,
        navigate_to_market_explore_callback: Callable[[], None] | None = None,
        navigate_to_evidence_review_callback: Callable[[], None] | None = None,
        navigate_to_portfolio_callback: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.source_service = source_service
        self.decision_date = decision_date
        self.replay_summary_json = replay_summary_json
        self.decision_source_widget = decision_source_widget
        self.navigate_to_daily_decision_callback = navigate_to_daily_decision_callback
        self.navigate_to_market_explore_callback = navigate_to_market_explore_callback
        self.navigate_to_evidence_review_callback = navigate_to_evidence_review_callback
        self.navigate_to_portfolio_callback = navigate_to_portfolio_callback
        self._dashboard: WorkbenchDashboardDTO | None = None
        self._viewed_review_item_ids: set[str] = set()

        self.status_model = WorkbenchStatusStripTableModel()
        self.review_model = WorkbenchReviewQueueTableModel()
        self.evidence_feed_model = WorkbenchEvidenceFeedTableModel()
        self.action_item_model = WorkbenchActionItemTableModel()
        self.operating_loop_model = WorkbenchOperatingLoopTableModel()
        self.evidence_model = WorkbenchEvidenceTableModel()
        self.checklist_model = WorkbenchChecklistTableModel()
        self.advice_recommendation_model = AdviceRecommendationTableModel()
        self.advice_candidate_model = AdviceCandidateTableModel()
        self.advice_portfolio_model = AdvicePortfolioTableModel()

        self._setup_ui()
        if dashboard is not None:
            self.render_dashboard(dashboard)
        elif auto_refresh and self.source_service is not None:
            self.refresh_dashboard()
        else:
            self._display_pending_dashboard()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        self.subtabs = QTabWidget()
        layout.addWidget(self.subtabs)

        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        overview_layout.setSpacing(10)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        self.overview_layout = overview_layout

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setSpacing(10)
        content_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("決策工作台 / Unified Decision Workbench")
        title_font = QFont()
        title_font.setPointSize(17)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")
        content_layout.addWidget(title)

        self.priority_banner = QLabel("")
        self.priority_banner.setWordWrap(True)
        self.priority_banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content_layout.addWidget(self.priority_banner)

        self.summary_blocks: dict[str, QWidget] = {}
        self.summary_value_labels: dict[str, QLabel] = {}
        self.summary_detail_labels: dict[str, QLabel] = {}
        summary_row = QWidget()
        summary_layout = QHBoxLayout(summary_row)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        for key, label in (
            ("review", "今日待判讀"),
            ("action", "人工待處理"),
            ("waiting", "等待真實時間"),
            ("warning", "警告"),
        ):
            summary_layout.addWidget(self._make_summary_block(key, label), 1)
        content_layout.addWidget(summary_row)

        self.boundary_banner = QLabel("")
        self.boundary_banner.setWordWrap(True)
        self.boundary_banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.boundary_banner.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 8px;"
        )
        content_layout.addWidget(self.boundary_banner)

        advice_panel, self.advice_section_title = self._panel_with_title("正式 Advice / 唯讀呈現")
        self.advice_summary = self._make_state_label()
        self.advice_recommendation_table = self._make_table(self.advice_recommendation_model)
        self.advice_candidate_table = self._make_table(self.advice_candidate_model)
        self.advice_portfolio_table = self._make_table(self.advice_portfolio_model)
        advice_panel.layout.addWidget(self.advice_summary)
        advice_panel.layout.addWidget(self.advice_recommendation_table)
        self.advice_candidate_label = QLabel("Professional 研究候選（不屬於正式 Advice）")
        advice_panel.layout.addWidget(self.advice_candidate_label)
        advice_panel.layout.addWidget(self.advice_candidate_table)
        advice_panel.layout.addWidget(self.advice_portfolio_table)
        content_layout.addWidget(advice_panel)

        self.refresh_button = QPushButton("重新載入唯讀工作台")
        self.refresh_button.setProperty("variant", "secondary")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        content_layout.addWidget(self.refresh_button)

        drilldown_panel, self.drilldown_section_title = self._panel_with_title("操作下鑽 / Drill-down")
        drilldown_layout = QHBoxLayout()
        drilldown_layout.setContentsMargins(0, 0, 0, 0)
        drilldown_layout.setSpacing(8)
        self.daily_decision_button = self._make_drilldown_button(
            "開啟決策來源",
            self.navigate_to_daily_decision_callback,
            "切到 Workbench 內的決策來源頁，只讀取既有 service snapshot。",
        )
        self.market_explore_button = self._make_drilldown_button(
            "開啟市場探索",
            self.navigate_to_market_explore_callback,
            "切到市場探索工作區，供人工研究與比對。",
        )
        self.evidence_review_button = self._make_drilldown_button(
            "開啟證據覆盤",
            self.navigate_to_evidence_review_callback,
            "切到策略回測內的證據覆盤，不啟用排程器。",
        )
        self.portfolio_button = self._make_drilldown_button(
            "開啟持倉管理",
            self.navigate_to_portfolio_callback,
            "切到持倉管理頁做人工覆盤，不產生買賣建議。",
        )
        drilldown_layout.addWidget(self.daily_decision_button)
        drilldown_layout.addWidget(self.market_explore_button)
        drilldown_layout.addWidget(self.evidence_review_button)
        drilldown_layout.addWidget(self.portfolio_button)
        drilldown_layout.addStretch()
        drilldown_panel.layout.addLayout(drilldown_layout)
        content_layout.addWidget(drilldown_panel)

        meta_panel, self.meta_section_title = self._panel_with_title("資料來源 / Workbench Source")
        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        meta_panel.layout.addWidget(self.meta_label)
        content_layout.addWidget(meta_panel)

        status_panel, self.status_section_title = self._panel_with_title("狀態列 / Status Strip")
        self.status_table = self._make_table(self.status_model)
        status_panel.layout.addWidget(self.status_table)
        content_layout.addWidget(status_panel)

        primary_area = QWidget()
        primary_layout = QHBoxLayout(primary_area)
        primary_layout.setContentsMargins(0, 0, 0, 0)
        primary_layout.setSpacing(10)
        list_column = QWidget()
        list_layout = QVBoxLayout(list_column)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(10)

        review_panel, self.review_section_title = self._panel_with_title("今日待判讀 / Today Review Queue")
        self.review_state_label = self._make_state_label()
        self.review_empty_state = EmptyStatePanel(
            "今日所有風險已確認",
            "今日待判讀佇列目前為空；可切到市場探索做研究，或等待下一次正式資料更新。",
        )
        self.review_table = self._make_table(self.review_model)
        self.review_table.clicked.connect(lambda index: self._show_model_row_detail(self.review_model, index.row()))
        self.review_table.doubleClicked.connect(
            lambda index: self._navigate_model_row(self.review_model, index.row())
        )
        review_panel.layout.addWidget(self.review_state_label)
        review_panel.layout.addWidget(self.review_empty_state)
        review_panel.layout.addWidget(self.review_table)
        list_layout.addWidget(review_panel)

        evidence_feed_panel, self.evidence_feed_section_title = self._panel_with_title(
            "背景證據流 / Background Evidence Feed"
        )
        self.evidence_feed_state_label = self._make_state_label()
        self.evidence_feed_table = self._make_table(self.evidence_feed_model)
        self.evidence_feed_table.clicked.connect(
            lambda index: self._show_model_row_detail(self.evidence_feed_model, index.row())
        )
        self.evidence_feed_table.doubleClicked.connect(
            lambda index: self._navigate_model_row(self.evidence_feed_model, index.row())
        )
        evidence_feed_panel.layout.addWidget(self.evidence_feed_state_label)
        evidence_feed_panel.layout.addWidget(self.evidence_feed_table)
        list_layout.addWidget(evidence_feed_panel)

        action_item_panel, self.action_item_section_title = self._panel_with_title(
            "只讀 Action Items / Read-only Manual Queue"
        )
        self.action_item_state_label = self._make_state_label()
        self.action_item_table = self._make_table(self.action_item_model)
        self.action_item_table.clicked.connect(
            lambda index: self._show_model_row_detail(self.action_item_model, index.row())
        )
        self.action_item_table.doubleClicked.connect(
            lambda index: self._navigate_model_row(self.action_item_model, index.row())
        )
        action_item_panel.layout.addWidget(self.action_item_state_label)
        action_item_panel.layout.addWidget(self.action_item_table)
        list_layout.addWidget(action_item_panel)

        detail_panel, self.detail_section_title = self._panel_with_title("詳情檢視 / Inspector")
        detail_panel.setMinimumWidth(360)
        self.detail_title_label = QLabel("尚未選取項目")
        detail_title_font = QFont()
        detail_title_font.setPointSize(13)
        detail_title_font.setBold(True)
        self.detail_title_label.setFont(detail_title_font)
        self.detail_title_label.setWordWrap(True)
        self.detail_title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")
        self.detail_status_label = QLabel("")
        self.detail_status_label.setWordWrap(True)
        self.detail_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_status_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_secondary}; font-weight: 700;"
        )
        self.detail_body_label = QLabel("")
        self.detail_body_label.setWordWrap(True)
        self.detail_body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_body_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 10px; line-height: 135%;"
        )
        self.detail_drilldown_button = QPushButton("開啟下鑽")
        self.detail_drilldown_button.setProperty("variant", "secondary")
        self.detail_drilldown_button.clicked.connect(self._open_selected_detail_target)
        self._selected_detail_target = ""
        detail_panel.layout.addWidget(self.detail_title_label)
        detail_header_row = QWidget()
        detail_header_layout = QHBoxLayout(detail_header_row)
        detail_header_layout.setContentsMargins(0, 0, 0, 0)
        detail_header_layout.setSpacing(8)
        self.detail_status_badge = QLabel("")
        self.detail_status_badge.setAlignment(Qt.AlignCenter)
        self.detail_status_badge.setMinimumHeight(26)
        detail_header_layout.addWidget(self.detail_status_badge, 0)
        detail_header_layout.addWidget(self.detail_status_label, 1)
        detail_panel.layout.addWidget(detail_header_row)

        self.detail_summary_box = self._make_detail_box()
        self.detail_source_box = self._make_detail_box()
        self.detail_diagnostics_box = self._make_detail_box()
        detail_panel.layout.addWidget(self.detail_summary_box)
        detail_panel.layout.addWidget(self.detail_source_box)
        detail_panel.layout.addWidget(self.detail_diagnostics_box)
        self.detail_body_label.setVisible(False)
        detail_panel.layout.addWidget(self.detail_drilldown_button)
        detail_panel.layout.addStretch()

        primary_layout.addWidget(list_column, 3)
        primary_layout.addWidget(detail_panel, 2)
        content_layout.addWidget(primary_area)

        operating_loop_panel = CollapsibleSectionPanel(
            "操作節奏 / Read-only Operating Loop",
            collapsed=True,
        )
        self.operating_loop_collapsible = operating_loop_panel
        self.operating_loop_section_title = operating_loop_panel.title_label
        self.operating_loop_state_label = self._make_state_label()
        self.operating_loop_list = QWidget()
        self.operating_loop_list_layout = QVBoxLayout(self.operating_loop_list)
        self.operating_loop_list_layout.setContentsMargins(0, 0, 0, 0)
        self.operating_loop_list_layout.setSpacing(6)
        operating_loop_panel.content_layout.addWidget(self.operating_loop_state_label)
        operating_loop_panel.content_layout.addWidget(self.operating_loop_list)
        content_layout.addWidget(operating_loop_panel)

        evidence_panel = CollapsibleSectionPanel("證據與品質 / Evidence Mode", collapsed=True)
        self.evidence_collapsible = evidence_panel
        self.evidence_section_title = evidence_panel.title_label

        self.evidence_summary_row = QWidget()
        evidence_summary_layout = QHBoxLayout(self.evidence_summary_row)
        evidence_summary_layout.setContentsMargins(0, 0, 0, 0)
        evidence_summary_layout.setSpacing(10)
        self.evidence_boundary_card = MetricCard("邊界與 Gate 摘要", "")
        self.evidence_coverage_card = MetricCard("覆蓋率與缺口", "")
        self.evidence_boundary_card.value_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 12px; "
            "font-weight: normal; line-height: 145%;"
        )
        self.evidence_coverage_card.value_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 12px; "
            "font-weight: normal; line-height: 145%;"
        )
        self.evidence_boundary_card.value_label.setWordWrap(True)
        self.evidence_coverage_card.value_label.setWordWrap(True)
        evidence_summary_layout.addWidget(self.evidence_boundary_card, 1)
        evidence_summary_layout.addWidget(self.evidence_coverage_card, 1)

        self.evidence_table = self._make_table(self.evidence_model)
        self.evidence_table.clicked.connect(lambda index: self._show_model_row_detail(self.evidence_model, index.row()))
        evidence_panel.content_layout.addWidget(self.evidence_summary_row)
        evidence_panel.content_layout.addWidget(self.evidence_table)
        content_layout.addWidget(evidence_panel)

        checklist_panel = CollapsibleSectionPanel("每日檢查清單 / Daily Checklist", collapsed=True)
        self.checklist_collapsible = checklist_panel
        self.checklist_section_title = checklist_panel.title_label
        self.checklist_list = QWidget()
        self.checklist_list_layout = QVBoxLayout(self.checklist_list)
        self.checklist_list_layout.setContentsMargins(0, 0, 0, 0)
        self.checklist_list_layout.setSpacing(6)
        checklist_panel.content_layout.addWidget(self.checklist_list)
        content_layout.addWidget(checklist_panel)

        warnings_panel = CollapsibleSectionPanel("警告與降級來源", collapsed=True)
        self.warnings_collapsible = warnings_panel
        self.warnings_section_title = warnings_panel.title_label
        self.warning_list = WarningList()
        self.warning_list.setMinimumHeight(90)
        warnings_panel.content_layout.addWidget(self.warning_list)
        content_layout.addWidget(warnings_panel)
        content_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        overview_layout.addWidget(scroll_area)
        self.subtabs.addTab(overview_page, "總覽")
        self.subtabs.addTab(self._build_decision_source_page(), "決策來源")
        self.subtabs.addTab(
            self._build_navigation_page(
                "Evidence",
                "證據與品質細節留在總覽的 Evidence 區塊；需深挖時可開啟證據覆盤。",
                self.evidence_review_button,
            ),
            "Evidence",
        )
        self.subtabs.addTab(
            self._build_navigation_page(
                "持倉追蹤",
                "持倉與觀察清單摘要留在總覽；需實作檢查時切到持倉管理。",
                self.portfolio_button,
            ),
            "持倉追蹤",
        )
        self.subtabs.addTab(
            self._build_navigation_page(
                "操作節奏",
                "操作節奏只呈現 DTO 狀態；不標記完成、不寫 DB、不啟用排程器。",
                None,
            ),
            "操作節奏",
        )

    def _build_decision_source_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if self.decision_source_widget is None:
            label = QLabel("決策來源尚未載入；Workbench 仍維持唯讀，不補資料、不讀 DB、不啟用排程器。")
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
            layout.addWidget(label)
            layout.addStretch()
        else:
            layout.addWidget(self.decision_source_widget)
        return page

    def _build_navigation_page(
        self,
        title: str,
        body: str,
        button: QPushButton | None,
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        panel, _title = self._panel_with_title(title)
        label = QLabel(
            f"{body}\n\n"
            "此頁目前是摘要與下鑽入口，也是預留深挖區；完整資料與互動能力會等後續正式資料來源與功能切片補齊。"
        )
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
        panel.layout.addWidget(label)
        if button is not None:
            mirror_button = QPushButton(button.text())
            mirror_button.setProperty("variant", "secondary")
            mirror_button.setEnabled(button.isEnabled())
            mirror_button.setToolTip(button.toolTip())
            if button.isEnabled():
                mirror_button.clicked.connect(lambda _checked=False, source_button=button: source_button.click())
            panel.layout.addWidget(mirror_button)
        layout.addWidget(panel)
        layout.addStretch()
        return page

    def select_subtab(self, label: str) -> bool:
        for index in range(self.subtabs.count()):
            if self.subtabs.tabText(index) == label:
                self.subtabs.setCurrentIndex(index)
                return True
        return False

    def viewed_review_item_ids(self) -> set[str]:
        return set(self._viewed_review_item_ids)

    def _panel_with_title(self, title: str) -> tuple[SectionPanel, QLabel]:
        panel = SectionPanel(title)
        title_widget = panel.layout.itemAt(0).widget()
        if isinstance(title_widget, QLabel):
            return panel, title_widget
        fallback_title = QLabel(title)
        panel.layout.insertWidget(0, fallback_title)
        return panel, fallback_title

    def _make_table(self, model) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setMinimumHeight(110)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        apply_financial_table_style(table)
        return table

    def _make_detail_box(self) -> QLabel:
        label = QLabel("")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setStyleSheet(
            f"background: {WORKBENCH_TONES['neutral']['bg']}; "
            f"color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {WORKBENCH_TONES['neutral']['border']}; "
            f"border-left: 4px solid {WORKBENCH_TONES['neutral']['fg']}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 10px; line-height: 140%;"
        )
        return label

    def _make_state_label(self) -> QLabel:
        label = QLabel("")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 8px;"
        )
        return label

    def _make_summary_block(self, key: str, title: str) -> QWidget:
        block = QWidget()
        block.setObjectName("workbenchSummaryBlock")
        block.setStyleSheet(
            f"#workbenchSummaryBlock {{ background: {MIDNIGHT_ANALYST.surface_2}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        layout = QVBoxLayout(block)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_muted}; font-size: 10px; font-weight: 600;")
        value_label = QLabel("-")
        value_font = QFont()
        value_font.setPointSize(14)
        value_font.setBold(True)
        value_label.setFont(value_font)
        value_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")
        detail_label = QLabel("")
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 10px;")

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)
        self.summary_blocks[key] = block
        self.summary_value_labels[key] = value_label
        self.summary_detail_labels[key] = detail_label
        return block

    def _make_drilldown_button(
        self,
        text: str,
        callback: Callable[[], None] | None,
        tooltip: str,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", "secondary")
        button.setToolTip(tooltip)
        button.setEnabled(callback is not None)
        if callback is not None:
            button.clicked.connect(callback)
        return button

    def refresh_dashboard(self) -> None:
        if self.source_service is None:
            self._display_exception_dashboard("WorkbenchSourceService 不可用")
            return
        self.refresh_button.setEnabled(False)
        try:
            dashboard = self.source_service.inspect(
                decision_date=self.decision_date,
                replay_summary_json=self.replay_summary_json,
            )
        except Exception as exc:  # noqa: BLE001
            self._display_exception_dashboard(str(exc))
        else:
            self.render_dashboard(cast(WorkbenchDashboardDTO, dashboard))
        finally:
            self.refresh_button.setEnabled(True)

    def navigate_to_drilldown_target(self, target: str) -> bool:
        legacy_target = WORKBENCH_LEGACY_DRILLDOWN_TARGETS.get(str(target))
        callbacks: dict[str, Callable[[], None] | None] = {
            "daily_decision": self.navigate_to_daily_decision_callback,
            "evidence_review": self.navigate_to_evidence_review_callback,
            "portfolio": self.navigate_to_portfolio_callback,
        }
        callback = callbacks.get(str(legacy_target))
        if callback is None:
            return False
        callback()
        return True

    def _navigate_model_row(self, model, row: int) -> None:
        item = model.row_at(row)
        if item is None:
            return
        self._show_model_row_detail(model, row)
        if model is self.review_model and hasattr(item, "item_id"):
            self._viewed_review_item_ids.add(str(item.item_id))
            self.review_state_label.setText(self._review_queue_state_text(self._dashboard))
        target = getattr(item, "drilldown_target", "")
        self.navigate_to_drilldown_target(str(target))

    def _show_model_row_detail(self, model, row: int) -> None:
        item = model.row_at(row)
        if item is None:
            self._set_detail_placeholder("尚未選取項目", "請點選左側任一列查看完整來源追蹤與診斷訊號。")
            return
        title = _detail_title(item)
        status = _detail_status(item)
        target = str(getattr(item, "drilldown_target", "") or "")
        self._selected_detail_target = target
        self.detail_title_label.setText(_detail_display_title(title))
        self.detail_status_label.setText(
            f"狀態：{display_workbench_value(status)}"
            + (f" | 下鑽：{display_workbench_value(target)}" if target else "")
        )
        self._apply_detail_tone(status)
        self._set_detail_sections(item)
        self.detail_body_label.setText(_format_detail_body(item))
        self.detail_drilldown_button.setEnabled(bool(target))

    def _set_detail_placeholder(self, title: str, body: str) -> None:
        self._selected_detail_target = ""
        self.detail_title_label.setText(_detail_display_title(title))
        self.detail_status_label.setText("狀態：等待選取")
        self.detail_status_badge.setText("WAIT")
        self._apply_detail_tone("info")
        self.detail_summary_box.setText(f"重點摘要\n{body}")
        self.detail_source_box.setText("來源與邊界\n等待 WorkbenchDashboardDTO。")
        self.detail_diagnostics_box.setText("診斷訊號\n尚無可檢視項目。")
        self.detail_body_label.setText(body)
        self.detail_drilldown_button.setEnabled(False)

    def _open_selected_detail_target(self) -> None:
        target = self._selected_detail_target
        if target:
            self.navigate_to_drilldown_target(target)

    def render_dashboard(self, dashboard: WorkbenchDashboardDTO) -> None:
        self._dashboard = dashboard
        self.refresh_button.setEnabled(self.source_service is not None)
        self.boundary_banner.setText(
            "唯讀邊界：資料只能由 WorkbenchSourceService / WorkbenchDashboardDTO 供應；"
            "不寫 DB、不啟用正式排程器、不是交易建議；"
            "Advice 僅呈現已注入 DTO、不執行 Policy；"
            "不重算 scoring / portfolio / backtest / lifecycle。"
        )
        self._set_summary_blocks(dashboard)
        self._set_priority_banner(dashboard)
        self.meta_label.setText(
            f"決策日期={dashboard.as_of_date.isoformat()} | "
            f"產生時間={dashboard.generated_at.isoformat()} | "
            f"來源模式={display_workbench_value(dashboard.source_mode)} | "
            f"允許寫入={_yes_no(dashboard.access_boundary.writes_allowed)} | "
            f"正式排程器={_yes_no(dashboard.access_boundary.production_scheduler_allowed)}"
        )
        self.status_model.set_rows(dashboard.status_strip)
        self._render_advice(dashboard)
        self.review_model.set_rows(dashboard.review_items)
        self.review_state_label.setText(self._review_queue_state_text(dashboard))
        has_review_items = bool(dashboard.review_items)
        self.review_empty_state.setVisible(not has_review_items)
        self.review_table.setVisible(has_review_items)
        self.evidence_feed_model.set_rows(dashboard.background_evidence_feed)
        self.action_item_model.set_rows(dashboard.action_items)
        self.operating_loop_model.set_rows(dashboard.operating_loop_steps)
        self.evidence_feed_state_label.setText(_evidence_feed_state_text(dashboard))
        self.action_item_state_label.setText(_action_item_state_text(dashboard))
        self.operating_loop_state_label.setText(_operating_loop_state_text(dashboard))
        self.evidence_model.set_rows(dashboard.evidence_summary)
        self.checklist_model.set_rows(dashboard.daily_checklist)
        self._update_evidence_summary_cards(dashboard)
        self._render_operating_loop(dashboard.operating_loop_steps)
        self._render_checklist(dashboard.daily_checklist)
        self.warning_list.set_warnings(tuple(_humanize_warning(item) for item in dashboard.warnings))
        self._show_initial_detail(dashboard)
        self._resize_tables()

    def _render_advice(self, dashboard: WorkbenchDashboardDTO) -> None:
        advice = dashboard.advice_dashboard
        if advice is None:
            self.advice_summary.setText("尚未提供 AdviceDashboardDTO；唯讀工作台不執行 Policy 或核心計算。")
            self.advice_recommendation_model.set_rows(())
            self.advice_candidate_model.set_rows(())
            self.advice_portfolio_model.set_rows(())
            return
        formal_rows = tuple(
            row for row in advice.recommendations
            if row.classification is AdviceClassification.FORMAL_ADVICE
        )
        candidate_rows = tuple(
            row for row in advice.recommendations
            if row.classification is AdviceClassification.PROFESSIONAL_CANDIDATE
        )
        self.advice_summary.setText(
            "Advice 唯讀邊界：僅呈現已注入 AdviceDashboardDTO；"
            f"mode={advice.mode.value} | decision_date={advice.decision_date} | "
            f"data_as_of_date={advice.data_as_of_date} | "
            f"warnings={', '.join(advice.warnings) or 'none'} | "
            f"正式 Advice {len(formal_rows)} 筆 | Professional 研究候選 {len(candidate_rows)} 筆 | "
            + "；".join(
                f"{row.stock_code or 'portfolio'} {row.advice_action.value} "
                f"{', '.join(row.why_not_reasons or row.refusal_reasons)} "
                f"quality={row.data_quality} feasibility={row.execution_feasibility}"
                for row in formal_rows
            )
        )
        self.advice_recommendation_model.set_rows(formal_rows)
        self.advice_candidate_model.set_rows(candidate_rows)
        self.advice_portfolio_model.set_rows(advice.portfolio_rows)

    def _show_initial_detail(self, dashboard: WorkbenchDashboardDTO) -> None:
        if self.evidence_feed_model.rowCount() > 0:
            self._show_model_row_detail(self.evidence_feed_model, 0)
            return
        if self.review_model.rowCount() > 0:
            self._show_model_row_detail(self.review_model, 0)
            return
        if self.action_item_model.rowCount() > 0:
            self._show_model_row_detail(self.action_item_model, 0)
            return
        if self.operating_loop_model.rowCount() > 0:
            self._show_model_row_detail(self.operating_loop_model, 0)
            return
        self._set_detail_placeholder(
            "目前沒有可檢視項目",
            (
                f"決策日期：{dashboard.as_of_date.isoformat()}\n"
                "Workbench 仍維持唯讀；沒有清單列不代表 Phase gate 完成。"
            ),
        )

    def _display_pending_dashboard(self) -> None:
        self.refresh_button.setEnabled(self.source_service is not None)
        self.boundary_banner.setText(
            "唯讀邊界：等待 WorkbenchDashboardDTO；不是交易建議；正式排程器維持關閉。"
        )
        self._set_summary_placeholder("等待 DTO", "尚未載入 WorkbenchDashboardDTO")
        self.meta_label.setText("工作台尚未載入。")
        self.evidence_boundary_card.value_label.setText("等待 WorkbenchDashboardDTO。")
        self.evidence_coverage_card.value_label.setText("UI 不直接讀 DB、不啟用排程器，也不執行 replay。")
        self.evidence_feed_state_label.setText(
            "目前沒有背景證據列：等待 WorkbenchDashboardDTO；UI 不讀 DB、不執行 replay、不補資料。"
        )
        self.action_item_state_label.setText(
            "目前沒有人工待處理事項：等待 WorkbenchDashboardDTO；Workbench 不寫 DB、不標記完成，也不是買賣建議。"
        )
        self.operating_loop_state_label.setText(
            "尚未有操作節奏 payload：等待 WorkbenchDashboardDTO；只讀、不寫 DB、不標記完成。"
        )
        self.evidence_feed_model.set_rows(())
        self.advice_recommendation_model.set_rows(())
        self.advice_candidate_model.set_rows(())
        self.advice_portfolio_model.set_rows(())
        self.advice_summary.setText("等待 AdviceDashboardDTO；UI 不執行 Policy 或核心計算。")
        self.review_model.set_rows(())
        self.review_state_label.setText(
            "今日待判讀佇列尚未載入；等待 WorkbenchDashboardDTO。UI 不讀 DB、不執行 replay。"
        )
        self.review_empty_state.setVisible(True)
        self.review_table.setVisible(False)
        self.action_item_model.set_rows(())
        self.operating_loop_model.set_rows(())
        self.warning_list.set_warnings(())
        self._set_detail_placeholder("等待 DTO", "請先重新載入 WorkbenchDashboardDTO。")

    def _display_exception_dashboard(self, error_message: str) -> None:
        self.boundary_banner.setText(
            "唯讀邊界：工作台載入降級；不是交易建議；正式排程器維持關閉。"
        )
        self._set_summary_placeholder("載入降級", "請先確認 WorkbenchSourceService；Phase gate 不變")
        self.meta_label.setText(f"工作台載入失敗：{error_message}")
        self.evidence_boundary_card.value_label.setText("資料品質降級")
        self.evidence_coverage_card.value_label.setText("WorkbenchSourceService 未回傳 dashboard DTO。")
        self.evidence_feed_state_label.setText(
            "背景證據流降級：WorkbenchSourceService 未回傳 DTO；UI 不補值、不讀 DB、不執行 replay。"
        )
        self.action_item_state_label.setText(
            "Action Items 降級：來源不可用；只供人工確認載入問題，不寫 DB，也不是買賣建議。"
        )
        self.operating_loop_state_label.setText(
            "操作節奏降級：WorkbenchSourceService 未回傳 DTO；只供人工檢查載入問題，不寫 DB、不標記完成。"
        )
        self.evidence_feed_model.set_rows(())
        self.advice_recommendation_model.set_rows(())
        self.advice_candidate_model.set_rows(())
        self.advice_portfolio_model.set_rows(())
        self.advice_summary.setText("Advice 載入降級；UI 不執行 Policy 或核心計算。")
        self.review_model.set_rows(())
        self.review_state_label.setText(
            "今日待判讀佇列載入降級；請先確認 WorkbenchSourceService 問題。UI 不補 gate。"
        )
        self.review_empty_state.setVisible(True)
        self.review_table.setVisible(False)
        self.action_item_model.set_rows(())
        self.operating_loop_model.set_rows(())
        self.warning_list.set_warnings((f"workbench_source_degraded:{error_message}",))
        self._set_detail_placeholder("載入降級", f"WorkbenchSourceService 未回傳 DTO：{error_message}")

    def _resize_tables(self) -> None:
        for table in (
            self.status_table,
            self.review_table,
            self.evidence_feed_table,
            self.action_item_table,
            self.evidence_table,
            self.advice_recommendation_table,
            self.advice_portfolio_table,
        ):
            table.resizeColumnsToContents()
            table.resizeRowsToContents()
        self._fit_summary_table(self.evidence_feed_table, fixed_widths=(190, 92))
        self._fit_summary_table(self.action_item_table, fixed_widths=(104, 92, 130, 180))

    def _fit_summary_table(self, table: QTableView, *, fixed_widths: tuple[int, ...]) -> None:
        header = table.horizontalHeader()
        if table.model() is None or table.model().columnCount() <= len(fixed_widths):
            return
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for index, width in enumerate(fixed_widths):
            header.setSectionResizeMode(index, QHeaderView.Fixed)
            table.setColumnWidth(index, width)
        header.setSectionResizeMode(len(fixed_widths), QHeaderView.Stretch)

    def _update_evidence_summary_cards(self, dashboard: WorkbenchDashboardDTO) -> None:
        boundary_lines = [
            f"資料品質來源模式：{display_workbench_value(dashboard.source_mode)}",
            "Workbench 維持唯讀：不重算評分、持倉、回測或生命週期",
        ]
        coverage_lines = []
        replay_summary = _find_replay_summary(dashboard.evidence_summary)
        if replay_summary is not None:
            boundary_lines.append("歷史 replay 摘要只作研究證據揭露")
            for item in replay_summary.diagnostics:
                text = _localize_workbench_text(_humanize_replay_diagnostic(item))
                if "覆蓋" in text or "缺口" in text or "缺" in text:
                    coverage_lines.append(text)
                else:
                    boundary_lines.append(text)
            boundary_lines.append(_format_phase0_gate_text(dashboard))
        else:
            boundary_lines.append(_format_phase0_gate_text(dashboard))
            coverage_lines.append("等待 replay 摘要診斷載入。")

        self.evidence_boundary_card.value_label.setText(_format_card_lines(boundary_lines))
        self.evidence_coverage_card.value_label.setText(
            _format_card_lines(coverage_lines) if coverage_lines else "• 目前沒有額外覆蓋率缺口。"
        )

    def _render_operating_loop(self, steps) -> None:
        while self.operating_loop_list_layout.count():
            item = self.operating_loop_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, step in enumerate(steps):
            chips = []
            linked = getattr(step, "linked_item_ids", ())
            if linked:
                for l in linked:
                    chips.append((_localize_chip_label(str(l)), "info"))
            if str(getattr(step, "step_id", "")) == "multi_day_dry_run":
                chips.append(("每週歷史", "info"))
                chips.append(("來源缺口", "warning"))
            details = _format_detail_body(step)
            card = TimelineCard(
                index=i,
                step_num=i + 1,
                title=_localize_workbench_text(str(getattr(step, "label", getattr(step, "step_id", "")))),
                summary=_localize_workbench_text(str(getattr(step, "summary", ""))),
                status_text=display_workbench_value(str(getattr(step, "status", ""))),
                status_tone=str(getattr(step, "status", "")),
                details_text=details,
                chips=chips
            )
            card.clicked.connect(lambda idx=i: self._show_model_row_detail(self.operating_loop_model, idx))
            card.doubleClicked.connect(lambda idx=i: self._navigate_model_row(self.operating_loop_model, idx))
            self.operating_loop_list_layout.addWidget(card)

    def _render_checklist(self, checklist) -> None:
        while self.checklist_list_layout.count():
            item = self.checklist_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, item in enumerate(checklist):
            status = str(getattr(item, "status", ""))
            status_text = display_workbench_value(status)
            if status == "waiting_for_time":
                status_text = f"需要處理 / 需要人工覆盤 / {status_text}"
            card = StatusCard(
                index=i,
                title=_localize_workbench_text(str(getattr(item, "label", ""))),
                summary=_localize_workbench_text(str(getattr(item, "summary", ""))),
                status_text=status_text,
                status_tone=status,
            )
            card.clicked.connect(lambda idx=i: self._show_model_row_detail(self.checklist_model, idx))
            self.checklist_list_layout.addWidget(card)

    def _set_summary_blocks(self, dashboard: WorkbenchDashboardDTO) -> None:
        review_count = len(dashboard.review_items)
        action_count = len(dashboard.action_items)
        waiting_count = sum(
            1 for item in dashboard.daily_checklist if str(item.status) == "waiting_for_time"
        )
        warning_count = len(dashboard.warnings)
        self.summary_value_labels["review"].setText(f"{review_count} 筆")
        self.summary_detail_labels["review"].setText("今日需人工判讀；已查看只存在本次 UI session")
        self.summary_value_labels["action"].setText(f"{action_count} 筆")
        self.summary_detail_labels["action"].setText("只讀人工佇列；不寫 DB、不標記完成")
        self.summary_value_labels["waiting"].setText(f"{waiting_count} 項")
        self.summary_detail_labels["waiting"].setText(_format_phase0_ratio_text(dashboard))
        self.summary_value_labels["warning"].setText(f"{warning_count} 則")
        self.summary_detail_labels["warning"].setText("降級、缺口與 replay 限制需人工檢查")
        self._apply_summary_block_style("review", "info" if review_count else "ready")
        self._apply_summary_block_style("action", "warning" if action_count else "ready")
        self._apply_summary_block_style("waiting", "warning" if waiting_count else "ready")
        self._apply_summary_block_style("warning", "critical" if warning_count else "ready")

    def _apply_summary_block_style(self, key: str, status: str) -> None:
        tone = _workbench_tone(status)
        block = self.summary_blocks[key]
        block.setStyleSheet(
            f"#workbenchSummaryBlock {{ background: {tone['bg']}; "
            f"border: 1px solid {tone['border']}; border-left: 5px solid {tone['fg']}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        self.summary_value_labels[key].setStyleSheet(
            f"color: {tone['fg']}; font-size: 17px; font-weight: 800;"
        )
        self.summary_detail_labels[key].setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 11px; line-height: 135%;"
        )

    def _set_priority_banner(self, dashboard: WorkbenchDashboardDTO) -> None:
        review_count = len(dashboard.review_items)
        action_count = len(dashboard.action_items)
        warning_count = len(dashboard.warnings)
        waiting_count = sum(
            1 for item in dashboard.daily_checklist if str(item.status) == "waiting_for_time"
        )
        tone_key = "warning" if warning_count or action_count or waiting_count else "ready"
        tone = _workbench_tone(tone_key)
        self.priority_banner.setText(
            "今日重點："
            f"待判讀 {review_count} | 人工處理 {action_count} | "
            f"等待真實時間 {waiting_count} | 警告 {warning_count}。"
            "右側 Inspector 只顯示既有 DTO 證據，不寫入、不補 gate。"
        )
        self.priority_banner.setStyleSheet(
            f"background: {tone['bg']}; color: {MIDNIGHT_ANALYST.text_primary}; "
            f"border: 1px solid {tone['border']}; border-left: 6px solid {tone['fg']}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 10px 12px; "
            "font-size: 12px; font-weight: 700; line-height: 140%;"
        )

    def _set_summary_placeholder(self, value: str, detail: str) -> None:
        for key in self.summary_value_labels:
            self.summary_value_labels[key].setText(value)
            self.summary_detail_labels[key].setText(detail)
            self._apply_summary_block_style(key, "info")

    def _apply_detail_tone(self, status: str) -> None:
        tone = _workbench_tone(status)
        self.detail_status_badge.setText(display_workbench_value(status).upper())
        self.detail_status_badge.setStyleSheet(
            f"background: {tone['bg']}; color: {tone['fg']}; "
            f"border: 1px solid {tone['border']}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_badge}px; "
            "padding: 4px 10px; font-weight: 800;"
        )

    def _set_detail_sections(self, item) -> None:
        title = _detail_title(item)
        summary = _localize_workbench_text(str(getattr(item, "summary", "") or "無摘要。"))
        source_trace = _localize_workbench_text(
            str(getattr(item, "source_trace", getattr(item, "source", "")) or "未提供來源追蹤")
        )
        degraded_reason = _localize_workbench_text(str(getattr(item, "degraded_reason", "") or "無"))
        target = _localize_workbench_text(str(getattr(item, "drilldown_target", "") or "未提供"))
        diagnostics = getattr(item, "diagnostics", ())
        diagnostics_text = _format_detail_value(diagnostics) if diagnostics else "無額外診斷訊號。"
        self.detail_summary_box.setText(
            f"重點摘要\n{_localize_workbench_text(title)}\n{summary}"
        )
        self.detail_source_box.setText(
            "來源與邊界\n"
            f"來源追蹤：{source_trace}\n"
            f"降級原因：{degraded_reason}\n"
            f"下鑽目標：{target}\n"
            "唯讀邊界：不寫資料庫、不標記完成、不啟用排程器。"
        )
        self.detail_diagnostics_box.setText(
            f"診斷訊號\n{diagnostics_text}"
        )
        self._style_detail_box(self.detail_summary_box, "info")
        self._style_detail_box(self.detail_source_box, _detail_status(item) or "info")
        self._style_detail_box(self.detail_diagnostics_box, _detail_status(item) or "info")

    def _style_detail_box(self, label: QLabel, status: str) -> None:
        tone = _workbench_tone(status)
        label.setStyleSheet(
            f"background: {tone['bg']}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {tone['border']}; border-left: 4px solid {tone['fg']}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 10px; "
            "line-height: 140%; font-size: 11px;"
        )

    def _overview_summary_text(self, dashboard: WorkbenchDashboardDTO) -> str:
        return (
            f"今日待判讀 {len(dashboard.review_items)} 筆｜人工待處理 {len(dashboard.action_items)} 筆｜"
            f"等待真實時間 {sum(1 for item in dashboard.daily_checklist if str(item.status) == 'waiting_for_time')} 項｜"
            f"警告 {len(dashboard.warnings)} 則\n"
            f"{_format_phase0_gate_text(dashboard)}\n"
            "此總覽只彙整 WorkbenchDashboardDTO；不寫 DB、不補 gate、不產生買賣建議。"
        )

    def _review_queue_state_text(self, dashboard: WorkbenchDashboardDTO | None) -> str:
        return review_queue_state_text(dashboard, self._viewed_review_item_ids)


def _detail_title(item) -> str:
    return str(
        getattr(
            item,
            "label",
            getattr(item, "title", getattr(item, "item_id", getattr(item, "step_id", "Workbench item"))),
        )
    )


def _detail_display_title(title: str) -> str:
    if title == "Replay summary diagnostics":
        return "Replay 摘要診斷"
    return _localize_workbench_text(title)


def _workbench_tone(status: str) -> dict[str, str]:
    return WORKBENCH_TONES.get(str(status), WORKBENCH_TONES["neutral"])


def _detail_status(item) -> str:
    return str(getattr(item, "status", getattr(item, "severity", "")) or "")


def _format_card_lines(lines: list[str]) -> str:
    return "\n".join(f"• {_localize_workbench_text(line)}" for line in lines if str(line).strip())


def _localize_chip_label(text: str) -> str:
    token_map = {
        "readiness_weekly_history": "每週歷史",
        "readiness_multi_day_dry_run": "多日 dry-run",
        "readiness_source_gaps": "來源缺口",
        "replay_summary_manual_review": "replay 覆盤",
        "weekly_history": "每週歷史",
        "multi_day_dry_run": "多日 dry-run",
        "manual_review_note": "人工註記",
        "scheduler_off": "排程關閉",
        "readiness_weekly_history": "每週歷史",
        "readiness_multi_day_dry_run": "多日 dry-run",
        "readiness_source_gaps": "來源缺口",
        "replay_summary_manual_review": "replay 覆盤",
        "manual_review_note": "人工註記",
        "watchlist_trigger": "觀察清單觸發",
        "portfolio_review": "持倉覆盤",
        "evidence_review": "證據覆盤",
    }
    return token_map.get(text, display_workbench_value(text))


def _localize_workbench_text(text: str) -> str:
    replacements = {
        "manual_required": "需要人工覆盤",
        "waiting_for_time": "等待真實時間累積",
        "action_required": "需要處理",
        "blocked": "封鎖",
        "manual_observed": "人工已觀測",
        "passed": "通過",
        "missing": "缺漏",
        "degraded": "降級",
        "records observed": "筆已觀測",
        "record observed": "筆已觀測",
        "Weekly review history": "每週覆盤歷史",
        "Multi-day dry-run": "多日 dry-run",
        "Multi-day dry-run record": "多日 dry-run 紀錄",
        "Scheduler write-mode": "排程器寫入模式",
        "Production scheduler remains off": "正式排程器維持關閉",
        "must accumulate in real time": "必須靠真實時間累積",
        "replay cannot replace this gate": "replay 不可取代這個 gate",
        "review item": "待判讀項目",
        "Scheduler gate": "排程 Gate",
        "Replay summary gap": "Replay 摘要缺口",
        "Replay summary diagnostics": "Replay 摘要診斷",
        "Replay summary": "Replay 摘要",
        "diagnostics": "診斷訊號",
        "Decision snapshot freshness": "決策快照新鮮度",
        "Evidence gate status": "證據門檻狀態",
        "Manual review note": "人工覆盤註記",
        "source trace": "來源追蹤",
        "degraded reason": "降級原因",
        "read-only": "唯讀",
        "Read-only": "唯讀",
        "scheduler": "排程器",
        "production scheduler": "正式排程器",
        "simulated scheduler": "模擬排程器",
        "scoring": "評分",
        "portfolio": "持倉",
        "backtest": "回測",
        "lifecycle": "生命週期",
        "Historical replay JSON summary": "歷史 replay 摘要",
        "research evidence only": "僅供研究證據使用",
        "does not replace real weekly or multi-day scheduler gates": "不可取代真實每週或多日排程 gate",
        "Recommendations source uses only persisted results": "推薦來源只使用已保存結果",
        "Forward outcomes are capped by replay_data_as_of_date": "forward outcome 受 replay_data_as_of_date 限制",
        "Production scheduler remains separate and is not enabled by this replay": "正式排程器與 replay 分離，且不會被 replay 啟用",
        "Phase 0 weekly history": "Phase 0 每週歷史",
        "weekly history": "每週歷史",
        "multi-day dry-run": "多日 dry-run",
        "source gaps": "來源缺口",
        "source gap": "來源缺口",
        "readiness_weekly_history": "每週歷史",
        "readiness_multi_day_dry_run": "多日 dry-run",
        "readiness_source_gaps": "來源缺口",
        "replay_summary_manual_review": "replay 覆盤",
        "manual_review_note": "人工註記",
        "watchlist_trigger": "觀察清單觸發",
        "portfolio_review": "持倉覆盤",
        "evidence_review": "證據覆盤",
        "after_manual_review": "人工覆盤後",
        "daily_until_3": "每日直到 3 筆",
        "weekly_until_3": "每週直到 3 筆",
        "pending_future_data": "等待未來資料",
        "source_missing_screening_matrix": "缺 screening matrix 來源",
        "recommendation": "推薦",
        "evidence": "證據",
    }
    localized = str(text)
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        localized = localized.replace(source, target)
    return localized


def _format_detail_body(item) -> str:
    lines = [
        "唯讀邊界：此處只展示 WorkbenchDashboardDTO 既有欄位；不寫資料庫、不標記完成、不啟用排程器。",
        "",
    ]
    for label, field_name in (
        ("項目代號", "item_id"),
        ("步驟代號", "step_id"),
        ("摘要", "summary"),
        ("代碼", "code"),
        ("來源", "source"),
        ("來源類型", "source_type"),
        ("來源名稱", "source_label"),
        ("來源追蹤", "source_trace"),
        ("降級原因", "degraded_reason"),
        ("節奏", "cadence"),
        ("關聯項目", "linked_item_ids"),
        ("人工提示", "guidance"),
        ("下鑽目標", "drilldown_target"),
        ("寫入意圖", "write_intent"),
        ("診斷訊號", "diagnostics"),
    ):
        if not hasattr(item, field_name):
            continue
        value = getattr(item, field_name)
        if value is None or value == "" or value == ():
            continue
        lines.append(f"- {label}: {_format_detail_value(value)}")
    return "\n".join(lines)


def _format_detail_value(value: object) -> str:
    if isinstance(value, tuple):
        return "；".join(_format_detail_token(item) for item in value) or "無"
    if isinstance(value, list):
        return "；".join(_format_detail_token(item) for item in value) or "無"
    if isinstance(value, bool):
        return "是" if value else "否"
    return _format_detail_token(value)


def _format_detail_token(value: object) -> str:
    raw = str(value)
    display = display_workbench_value(raw)
    if raw == display:
        return _localize_workbench_text(raw)
    return _localize_workbench_text(display.replace(f"（{raw}）", ""))


def _find_replay_summary(items: tuple[WorkbenchEvidenceSummary, ...]) -> WorkbenchEvidenceSummary | None:
    for item in items:
        if item.item_id == "historical_replay":
            return item
    return None












def _humanize_replay_diagnostic(token: str) -> str:
    text = str(token)
    if text == "simulated_scheduler":
        return "模擬排程器：replay 來自模擬排程器，不是正式排程器。"
    if text.startswith("source_gap:"):
        return f"來源缺口：{display_workbench_value(text.split(':', 1)[1])}"
    if text.startswith("source_gap_coverage:"):
        return display_workbench_value(text)
    if text.startswith("payload_gap:"):
        return f"payload 缺口：{display_workbench_value(text.split(':', 1)[1])}"
    if text.startswith("outcome_maturity:"):
        return display_workbench_value(text)
    if text.startswith("benchmark_coverage:"):
        return display_workbench_value(text)
    if text.startswith("industry_benchmark_coverage:"):
        return display_workbench_value(text)
    if text.startswith("missing_industry_benchmark:"):
        return display_workbench_value(text)
    if text.startswith("pending_future_data:"):
        return display_workbench_value(text)
    if text.startswith("phase0_gate_not_satisfied:"):
        return display_workbench_value(text)
    if text.startswith("replay_direction_assessment:"):
        return display_workbench_value(text)
    return display_workbench_value(text)


def _format_phase0_gate_text(dashboard: WorkbenchDashboardDTO) -> str:
    weekly = _ratio_for_item(dashboard, "weekly_history") or "尚未就緒"
    dry_run = _ratio_for_item(dashboard, "multi_day_dry_run") or "尚未就緒"
    return (
        f"Phase 0 每週歷史 {weekly} 與多日 dry-run {dry_run} 仍是真實時間 gate；"
        "replay 不可取代。"
    )


def _format_phase0_ratio_text(dashboard: WorkbenchDashboardDTO) -> str:
    weekly = _ratio_for_item(dashboard, "weekly_history") or "尚未就緒"
    dry_run = _ratio_for_item(dashboard, "multi_day_dry_run") or "尚未就緒"
    return f"weekly history {weekly}｜multi-day dry-run {dry_run}"


def _ratio_for_item(dashboard: WorkbenchDashboardDTO, item_id: str) -> str | None:
    for item in dashboard.daily_checklist:
        if item.item_id != item_id:
            continue
        match = re.search(r"\b\d+/\d+\b", f"{item.label} {item.summary}")
        return match.group(0) if match else None
    for item in dashboard.evidence_summary:
        if item.item_id != item_id:
            continue
        match = re.search(r"\b\d+/\d+\b", f"{item.label} {item.summary}")
        return match.group(0) if match else None
    return None


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def _humanize_warning(token: object) -> str:
    text = str(token)
    if text.startswith("workbench_source_degraded:"):
        return "工作台來源降級：" + text.split(":", 1)[1]
    if text.startswith("degraded_source:"):
        return "降級來源：" + display_workbench_value(text.split(":", 1)[1])
    if "historical_replay" in text or text in {
        "simulated_scheduler",
        "not_production_readiness",
        "missing_industry_benchmark",
        "pending_insufficient_future_data",
    }:
        return _localize_workbench_text(display_workbench_value(text))
    return _localize_workbench_text(display_workbench_value(text))
