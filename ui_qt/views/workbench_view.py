from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Callable
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
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
from ui_qt.models.workbench_table_models import (
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
from ui_qt.widgets.theme_widgets import EmptyStatePanel, SectionPanel, WarningList


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
            ("warning", "Warnings"),
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
            "切到策略回測內的證據覆盤，不啟用 scheduler。",
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

        review_panel, self.review_section_title = self._panel_with_title("今日待判讀 / Today Review Queue")
        self.review_state_label = self._make_state_label()
        self.review_empty_state = EmptyStatePanel(
            "今日所有風險已確認",
            "今日待判讀佇列目前為空；可切到市場探索做研究，或等待下一次正式資料更新。",
        )
        self.review_table = self._make_table(self.review_model)
        self.review_table.doubleClicked.connect(
            lambda index: self._navigate_model_row(self.review_model, index.row())
        )
        review_panel.layout.addWidget(self.review_state_label)
        review_panel.layout.addWidget(self.review_empty_state)
        review_panel.layout.addWidget(self.review_table)
        content_layout.addWidget(review_panel)

        evidence_feed_panel, self.evidence_feed_section_title = self._panel_with_title(
            "背景證據流 / Background Evidence Feed"
        )
        self.evidence_feed_state_label = self._make_state_label()
        self.evidence_feed_table = self._make_table(self.evidence_feed_model)
        self.evidence_feed_table.doubleClicked.connect(
            lambda index: self._navigate_model_row(self.evidence_feed_model, index.row())
        )
        evidence_feed_panel.layout.addWidget(self.evidence_feed_state_label)
        evidence_feed_panel.layout.addWidget(self.evidence_feed_table)
        content_layout.addWidget(evidence_feed_panel)

        action_item_panel, self.action_item_section_title = self._panel_with_title(
            "只讀 Action Items / Read-only Manual Queue"
        )
        self.action_item_state_label = self._make_state_label()
        self.action_item_table = self._make_table(self.action_item_model)
        self.action_item_table.doubleClicked.connect(
            lambda index: self._navigate_model_row(self.action_item_model, index.row())
        )
        action_item_panel.layout.addWidget(self.action_item_state_label)
        action_item_panel.layout.addWidget(self.action_item_table)
        content_layout.addWidget(action_item_panel)

        operating_loop_panel, self.operating_loop_section_title = self._panel_with_title(
            "操作節奏 / Read-only Operating Loop"
        )
        self.operating_loop_state_label = self._make_state_label()
        self.operating_loop_table = self._make_table(self.operating_loop_model)
        self.operating_loop_table.doubleClicked.connect(
            lambda index: self._navigate_model_row(self.operating_loop_model, index.row())
        )
        operating_loop_panel.layout.addWidget(self.operating_loop_state_label)
        operating_loop_panel.layout.addWidget(self.operating_loop_table)
        content_layout.addWidget(operating_loop_panel)

        evidence_panel, self.evidence_section_title = self._panel_with_title("證據與品質 / Evidence Mode")
        self.data_quality_limitations_label = QLabel("")
        self.data_quality_limitations_label.setWordWrap(True)
        self.data_quality_limitations_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.data_quality_limitations_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 8px;"
        )
        self.evidence_table = self._make_table(self.evidence_model)
        evidence_panel.layout.addWidget(self.data_quality_limitations_label)
        evidence_panel.layout.addWidget(self.evidence_table)
        content_layout.addWidget(evidence_panel)

        checklist_panel, self.checklist_section_title = self._panel_with_title("每日檢查清單 / Daily Checklist")
        self.checklist_table = self._make_table(self.checklist_model)
        checklist_panel.layout.addWidget(self.checklist_table)
        content_layout.addWidget(checklist_panel)

        warnings_panel, self.warnings_section_title = self._panel_with_title("警告與降級來源 / Warnings")
        self.warning_list = WarningList()
        self.warning_list.setMinimumHeight(90)
        warnings_panel.layout.addWidget(self.warning_list)
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
                "操作節奏只呈現 DTO 狀態；不標記完成、不寫 DB、不啟用 scheduler。",
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
            label = QLabel("決策來源尚未載入；Workbench 仍維持唯讀，不補資料、不讀 DB、不啟用 scheduler。")
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
        if model is self.review_model and hasattr(item, "item_id"):
            self._viewed_review_item_ids.add(str(item.item_id))
            self.review_state_label.setText(self._review_queue_state_text(self._dashboard))
        target = getattr(item, "drilldown_target", "")
        self.navigate_to_drilldown_target(str(target))

    def render_dashboard(self, dashboard: WorkbenchDashboardDTO) -> None:
        self._dashboard = dashboard
        self.refresh_button.setEnabled(self.source_service is not None)
        self.boundary_banner.setText(
            "唯讀邊界：資料只能由 WorkbenchSourceService / WorkbenchDashboardDTO 供應；"
            "不寫 DB、不啟用 production scheduler、不是交易建議；"
            "不重算 scoring / portfolio / backtest / lifecycle。"
        )
        self._set_summary_blocks(dashboard)
        self.meta_label.setText(
            f"決策日期={dashboard.as_of_date.isoformat()} | "
            f"產生時間={dashboard.generated_at.isoformat()} | "
            f"來源模式={display_workbench_value(dashboard.source_mode)} | "
            f"允許寫入={_yes_no(dashboard.access_boundary.writes_allowed)} | "
            f"正式排程器={_yes_no(dashboard.access_boundary.production_scheduler_allowed)}"
        )
        self.status_model.set_rows(dashboard.status_strip)
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
        self.data_quality_limitations_label.setText(self._format_data_quality_limitations(dashboard))
        self.warning_list.set_warnings(tuple(_humanize_warning(item) for item in dashboard.warnings))
        self._resize_tables()

    def _display_pending_dashboard(self) -> None:
        self.refresh_button.setEnabled(self.source_service is not None)
        self.boundary_banner.setText(
            "唯讀邊界：等待 WorkbenchDashboardDTO；不是交易建議；production scheduler 維持關閉。"
        )
        self._set_summary_placeholder("等待 DTO", "尚未載入 WorkbenchDashboardDTO")
        self.meta_label.setText("工作台尚未載入。")
        self.data_quality_limitations_label.setText(
            "證據模式等待 WorkbenchDashboardDTO。UI 不直接讀 DB、不啟用 scheduler，也不執行 replay。"
        )
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
        self.review_model.set_rows(())
        self.review_state_label.setText(
            "今日待判讀佇列尚未載入；等待 WorkbenchDashboardDTO。UI 不讀 DB、不執行 replay。"
        )
        self.review_empty_state.setVisible(True)
        self.review_table.setVisible(False)
        self.action_item_model.set_rows(())
        self.operating_loop_model.set_rows(())
        self.warning_list.set_warnings(())

    def _display_exception_dashboard(self, error_message: str) -> None:
        self.boundary_banner.setText(
            "唯讀邊界：工作台載入降級；不是交易建議；production scheduler 維持關閉。"
        )
        self._set_summary_placeholder("載入降級", "請先確認 WorkbenchSourceService；Phase gate 不變")
        self.meta_label.setText(f"工作台載入失敗：{error_message}")
        self.data_quality_limitations_label.setText(
            "資料品質降級：WorkbenchSourceService 未回傳 dashboard DTO。"
        )
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
        self.review_model.set_rows(())
        self.review_state_label.setText(
            "今日待判讀佇列載入降級；請先確認 WorkbenchSourceService 問題。UI 不補 gate。"
        )
        self.review_empty_state.setVisible(True)
        self.review_table.setVisible(False)
        self.action_item_model.set_rows(())
        self.operating_loop_model.set_rows(())
        self.warning_list.set_warnings((f"workbench_source_degraded:{error_message}",))

    def _resize_tables(self) -> None:
        for table in (
            self.status_table,
            self.review_table,
            self.evidence_feed_table,
            self.action_item_table,
            self.operating_loop_table,
            self.evidence_table,
            self.checklist_table,
        ):
            table.resizeColumnsToContents()
            table.resizeRowsToContents()

    def _format_data_quality_limitations(self, dashboard: WorkbenchDashboardDTO) -> str:
        lines = [
            f"資料品質來源模式：{display_workbench_value(dashboard.source_mode)}。",
            "Workbench 維持唯讀：不重算 scoring、portfolio、backtest 或 lifecycle 邏輯。",
        ]
        replay_summary = _find_replay_summary(dashboard.evidence_summary)
        if replay_summary is not None:
            lines.append("Historical replay JSON summary 只作模擬證據揭露；UI 不讀 replay DB，也不執行 replay。")
            lines.extend(_humanize_replay_diagnostic(item) for item in replay_summary.diagnostics)
            lines.append(_format_phase0_gate_text(dashboard))
        else:
            lines.append(_format_phase0_gate_text(dashboard))
        return "\n".join(line for line in lines if line)

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

    def _set_summary_placeholder(self, value: str, detail: str) -> None:
        for key in self.summary_value_labels:
            self.summary_value_labels[key].setText(value)
            self.summary_detail_labels[key].setText(detail)

    def _overview_summary_text(self, dashboard: WorkbenchDashboardDTO) -> str:
        return (
            f"今日待判讀 {len(dashboard.review_items)} 筆｜人工待處理 {len(dashboard.action_items)} 筆｜"
            f"等待真實時間 {sum(1 for item in dashboard.daily_checklist if str(item.status) == 'waiting_for_time')} 項｜"
            f"Warnings {len(dashboard.warnings)} 則\n"
            f"{_format_phase0_gate_text(dashboard)}\n"
            "此總覽只彙整 WorkbenchDashboardDTO；不寫 DB、不補 gate、不產生買賣建議。"
        )

    def _review_queue_state_text(self, dashboard: WorkbenchDashboardDTO | None) -> str:
        if dashboard is None:
            return "今日待判讀佇列尚未載入；等待 WorkbenchDashboardDTO。"
        count = len(dashboard.review_items)
        if count == 0:
            return (
                "今日待判讀佇列為空；這只代表目前 DTO 沒有待判讀項目，"
                "不代表 Phase gate 已完成，也不是買賣建議。"
            )
        active_ids = {str(item.item_id) for item in dashboard.review_items}
        viewed_count = len(self._viewed_review_item_ids & active_ids)
        return (
            f"今日待判讀 {count} 筆；已查看 {viewed_count}/{count}。"
            "已查看只存在本次 UI session，不寫 DB、不標記完成。"
        )


def _find_replay_summary(items: tuple[WorkbenchEvidenceSummary, ...]) -> WorkbenchEvidenceSummary | None:
    for item in items:
        if item.item_id == "historical_replay":
            return item
    return None


def _evidence_feed_state_text(dashboard: WorkbenchDashboardDTO) -> str:
    count = len(dashboard.background_evidence_feed)
    if count == 0:
        return (
            "目前沒有背景證據列；這只代表 WorkbenchDashboardDTO payload 為空。"
            "Workbench 不讀 DB、不執行 replay、不補資料，也不代表 gate 已通過。"
        )
    if any(
        _is_degraded_status(item.status) or _has_degraded_reason(item.degraded_reason)
        for item in dashboard.background_evidence_feed
    ):
        return (
            f"背景證據流降級：{count} 筆來源中包含 missing / degraded / warning。"
            "請依 source trace 與 diagnostics 人工檢查；Workbench 不補值、不重跑 pipeline、不讀 replay DB。"
        )
    return (
        f"背景證據流已載入 {count} 筆唯讀來源。"
        "這是既有 DTO / service payload 的彙整，不是交易建議。"
    )


def _action_item_state_text(dashboard: WorkbenchDashboardDTO) -> str:
    count = len(dashboard.action_items)
    if count == 0:
        return (
            "目前沒有人工待處理事項；這不代表可以交易或 Phase gate 已通過。"
            "Workbench 不寫 DB、不標記完成、不套用 lifecycle，也不是買賣建議。"
        )
    if any(
        _is_degraded_status(item.severity) or _has_degraded_reason(item.degraded_reason)
        for item in dashboard.action_items
    ):
        return (
            f"Action Items 降級：佇列包含 {count} 筆資料缺口、警示或 waiting_for_time 項目。"
            "只供人工覆盤排序，不是買賣建議；Workbench 不寫 DB、不套用 lifecycle。"
        )
    return (
        f"Action Items 已載入 {count} 筆人工待處理事項。"
        "佇列只供人工檢查 source trace，不會自動建立 repository 或寫入狀態。"
    )


def _operating_loop_state_text(dashboard: WorkbenchDashboardDTO) -> str:
    count = len(dashboard.operating_loop_steps)
    if count == 0:
        return (
            "尚未有操作節奏 payload；等待 WorkbenchDashboardDTO。"
            "Workbench 維持只讀，不寫 DB、不標記完成、不啟用 scheduler。"
        )
    manual_count = sum(
        1
        for item in dashboard.operating_loop_steps
        if str(item.status) in {"manual_required", "warning", "action_required"}
    )
    waiting_count = sum(1 for item in dashboard.operating_loop_steps if str(item.status) == "waiting_for_time")
    return (
        f"操作節奏已載入 {count} 步：今天要看、人工處理與等待真實時間累積已串接；"
        f"人工處理 {manual_count} 步，等待真實時間累積 {waiting_count} 步。"
        "Workbench 只讀，不寫 DB、不標記完成、不套用 lifecycle。"
    )


def _is_degraded_status(status: str) -> bool:
    return str(status) in {
        "critical",
        "warning",
        "degraded",
        "missing",
        "blocked",
        "action_required",
        "waiting_for_time",
    }


def _has_degraded_reason(reason: str) -> bool:
    text = str(reason).strip()
    return bool(text and text != "none")


def _humanize_replay_diagnostic(token: str) -> str:
    text = str(token)
    if text == "simulated_scheduler":
        return "模擬 scheduler：replay 來自 simulated scheduler，不是 production scheduler。"
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
        f"Phase 0 weekly history {weekly} 與 multi-day dry-run {dry_run} 仍是真實時間 gate；"
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
        return display_workbench_value(text)
    return display_workbench_value(text)
