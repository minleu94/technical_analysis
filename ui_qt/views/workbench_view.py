from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app_module.workbench_dtos import WorkbenchDashboardDTO, WorkbenchEvidenceSummary
from app_module.workbench_source_service import WorkbenchSourceService
from ui_qt.models.workbench_table_models import (
    WorkbenchChecklistTableModel,
    WorkbenchEvidenceTableModel,
    WorkbenchReviewQueueTableModel,
    WorkbenchStatusStripTableModel,
)
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.widgets.theme_widgets import SectionPanel, WarningList


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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.source_service = source_service
        self.decision_date = decision_date
        self.replay_summary_json = replay_summary_json
        self._dashboard: WorkbenchDashboardDTO | None = None

        self.status_model = WorkbenchStatusStripTableModel()
        self.review_model = WorkbenchReviewQueueTableModel()
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

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setSpacing(10)
        content_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Unified Decision Workbench / 決策工作台")
        title_font = QFont()
        title_font.setPointSize(17)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")
        content_layout.addWidget(title)

        self.boundary_banner = QLabel("")
        self.boundary_banner.setWordWrap(True)
        self.boundary_banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.boundary_banner.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 8px;"
        )
        content_layout.addWidget(self.boundary_banner)

        self.refresh_button = QPushButton("重新載入唯讀 Workbench")
        self.refresh_button.setProperty("variant", "secondary")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        content_layout.addWidget(self.refresh_button)

        meta_panel, self.meta_section_title = self._panel_with_title("Workbench Source / 資料來源")
        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        meta_panel.layout.addWidget(self.meta_label)
        content_layout.addWidget(meta_panel)

        status_panel, self.status_section_title = self._panel_with_title("Status Strip / 狀態列")
        self.status_table = self._make_table(self.status_model)
        status_panel.layout.addWidget(self.status_table)
        content_layout.addWidget(status_panel)

        review_panel, self.review_section_title = self._panel_with_title("Today Review Queue / 今日待判讀")
        self.review_table = self._make_table(self.review_model)
        review_panel.layout.addWidget(self.review_table)
        content_layout.addWidget(review_panel)

        evidence_panel, self.evidence_section_title = self._panel_with_title("Evidence Mode / Data Quality / 證據與品質")
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

        checklist_panel, self.checklist_section_title = self._panel_with_title("Daily Checklist / 每日檢查清單")
        self.checklist_table = self._make_table(self.checklist_model)
        checklist_panel.layout.addWidget(self.checklist_table)
        content_layout.addWidget(checklist_panel)

        warnings_panel, self.warnings_section_title = self._panel_with_title("Warnings / Degraded Source / 降級來源")
        self.warning_list = WarningList()
        self.warning_list.setMinimumHeight(90)
        warnings_panel.layout.addWidget(self.warning_list)
        content_layout.addWidget(warnings_panel)
        content_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

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

    def refresh_dashboard(self) -> None:
        if self.source_service is None:
            self._display_exception_dashboard("WorkbenchSourceService unavailable")
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

    def render_dashboard(self, dashboard: WorkbenchDashboardDTO) -> None:
        self._dashboard = dashboard
        self.refresh_button.setEnabled(self.source_service is not None)
        self.boundary_banner.setText(
            "read-only boundary: data is supplied only by WorkbenchSourceService / "
            "WorkbenchDashboardDTO; writes are off; production scheduler is off; "
            "not trading advice; no recalculate scoring / portfolio / backtest / lifecycle."
        )
        self.meta_label.setText(
            f"as_of_date={dashboard.as_of_date.isoformat()} | "
            f"generated_at={dashboard.generated_at.isoformat()} | "
            f"source_mode={dashboard.source_mode} | "
            f"writes_allowed={dashboard.access_boundary.writes_allowed} | "
            f"production_scheduler_allowed={dashboard.access_boundary.production_scheduler_allowed}"
        )
        self.status_model.set_rows(dashboard.status_strip)
        self.review_model.set_rows(dashboard.review_items)
        self.evidence_model.set_rows(dashboard.evidence_summary)
        self.checklist_model.set_rows(dashboard.daily_checklist)
        self.data_quality_limitations_label.setText(self._format_data_quality_limitations(dashboard))
        self.warning_list.set_warnings(tuple(str(item) for item in dashboard.warnings))
        self._resize_tables()

    def _display_pending_dashboard(self) -> None:
        self.refresh_button.setEnabled(self.source_service is not None)
        self.boundary_banner.setText(
            "read-only boundary: waiting for WorkbenchDashboardDTO; not trading advice; "
            "production scheduler is off."
        )
        self.meta_label.setText("Workbench dashboard has not been loaded.")
        self.data_quality_limitations_label.setText(
            "Evidence mode waits for a WorkbenchDashboardDTO. No DB, scheduler, or replay execution occurs in the UI."
        )
        self.warning_list.set_warnings(())

    def _display_exception_dashboard(self, error_message: str) -> None:
        self.boundary_banner.setText(
            "read-only boundary: Workbench load degraded; not trading advice; production scheduler is off."
        )
        self.meta_label.setText(f"Workbench load failed: {error_message}")
        self.data_quality_limitations_label.setText(
            "Data quality is degraded because WorkbenchSourceService did not return a dashboard DTO."
        )
        self.warning_list.set_warnings((f"workbench_source_degraded:{error_message}",))

    def _resize_tables(self) -> None:
        for table in (self.status_table, self.review_table, self.evidence_table, self.checklist_table):
            table.resizeColumnsToContents()
            table.resizeRowsToContents()

    def _format_data_quality_limitations(self, dashboard: WorkbenchDashboardDTO) -> str:
        lines = [
            f"Data quality source_mode={dashboard.source_mode}.",
            "Workbench is read-only and does not recompute scoring, portfolio, backtest, or lifecycle logic.",
        ]
        replay_summary = _find_replay_summary(dashboard.evidence_summary)
        if replay_summary is not None:
            lines.append("Historical replay JSON summary is disclosed as simulated evidence only.")
            lines.extend(_humanize_replay_diagnostic(item) for item in replay_summary.diagnostics)
            lines.append(_format_phase0_gate_text(dashboard))
        else:
            lines.append(_format_phase0_gate_text(dashboard))
        return "\n".join(line for line in lines if line)


def _find_replay_summary(items: tuple[WorkbenchEvidenceSummary, ...]) -> WorkbenchEvidenceSummary | None:
    for item in items:
        if item.item_id == "historical_replay":
            return item
    return None


def _humanize_replay_diagnostic(token: str) -> str:
    text = str(token)
    if text == "simulated_scheduler":
        return "simulated_scheduler: replay came from a simulated scheduler, not production scheduler."
    if text.startswith("source_gap:"):
        return f"source gap: {text.split(':', 1)[1]}"
    if text.startswith("payload_gap:"):
        return f"payload gap: {text.split(':', 1)[1]}"
    if text.startswith("outcome_maturity:"):
        return "outcome maturity: " + text.split(":", 1)[1].replace("pending_future_data", "pending future-data")
    if text.startswith("benchmark_coverage:"):
        return "benchmark coverage: " + text.split(":", 1)[1]
    if text.startswith("missing_industry_benchmark:"):
        return "missing industry benchmark: " + text.split(":", 1)[1]
    if text.startswith("pending_future_data:"):
        return "pending future-data: " + text.split(":", 1)[1]
    if text.startswith("phase0_gate_not_satisfied:"):
        return "Phase 0 gate limitation: " + text.split(":", 1)[1]
    return text


def _format_phase0_gate_text(dashboard: WorkbenchDashboardDTO) -> str:
    weekly = _ratio_for_item(dashboard, "weekly_history") or "not ready"
    dry_run = _ratio_for_item(dashboard, "multi_day_dry_run") or "not ready"
    return (
        f"Phase 0 weekly history {weekly} and multi-day dry-run {dry_run} remain real-time gates; "
        "replay cannot replace them."
    )


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
