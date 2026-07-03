from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QTableView, QTextEdit, QVBoxLayout, QWidget

from app_module.evidence_operations_history_dashboard_dtos import (
    EvidenceOperationsHistoryDashboardRequest,
    EvidenceOperationsHistoryDashboardResult,
)
from ui_qt.models.evidence_operations_history_table_model import EvidenceOperationsHistoryTableModel
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.date_filter_edit import OptionalDateFilterEdit, date_filter_value
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.workers.task_worker import TaskWorker


CARD_TITLES = {
    "reviews_count": "週報紀錄",
    "needs_manual_review_count": "需人工覆盤",
    "coverage_only_count": "僅覆蓋率",
    "ready_for_closeout_count": "可收尾",
    "production_scheduler_allowed_count": "Scheduler 啟用",
    "warnings_count": "警告",
}


class EvidenceOperationsHistoryView(QWidget):
    def __init__(
        self,
        dashboard_service,
        *,
        auto_refresh: bool = True,
        async_refresh: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.dashboard_service = dashboard_service
        self.async_refresh = async_refresh
        self._active_request_id = 0
        self._workers: list[TaskWorker] = []
        self._current_result: EvidenceOperationsHistoryDashboardResult | None = None
        self._setup_ui()
        if auto_refresh:
            self.refresh_dashboard()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        filter_row = QGridLayout()
        self.start_date_input = OptionalDateFilterEdit()
        self.end_date_input = OptionalDateFilterEdit()
        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.setProperty("variant", "primary")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        filter_row.addWidget(QLabel("開始日"), 0, 0)
        filter_row.addWidget(self.start_date_input, 0, 1)
        filter_row.addWidget(QLabel("結束日"), 0, 2)
        filter_row.addWidget(self.end_date_input, 0, 3)
        filter_row.addWidget(self.refresh_button, 0, 4)
        root.addLayout(filter_row)

        cards = QGridLayout()
        self.cards = {field: self._make_card(title) for field, title in CARD_TITLES.items()}
        for index, widget in enumerate(self.cards.values()):
            cards.addWidget(widget, index // 3, index % 3)
        root.addLayout(cards)

        self.empty_state_label = QLabel("")
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.warning};")
        root.addWidget(self.empty_state_label)

        self.table_model = EvidenceOperationsHistoryTableModel()
        self.summary_table = QTableView()
        self.summary_table.setModel(self.table_model)
        apply_financial_table_style(self.summary_table)
        self.summary_table.setSelectionBehavior(QTableView.SelectRows)
        self.summary_table.setFont(QFont("Consolas", 9))
        self.summary_table.clicked.connect(self._on_table_row_clicked)
        root.addWidget(self.summary_table, stretch=3)

        self.detail_panel = QTextEdit()
        self.detail_panel.setReadOnly(True)
        self.detail_panel.setFont(QFont("Consolas", 9))
        root.addWidget(self.detail_panel, stretch=1)

    def refresh_dashboard(self) -> None:
        request = EvidenceOperationsHistoryDashboardRequest(
            start_date=date_filter_value(self.start_date_input),
            end_date=date_filter_value(self.end_date_input),
        )
        self._active_request_id += 1
        request_id = self._active_request_id
        self.refresh_button.setEnabled(False)
        if self.async_refresh:
            worker = TaskWorker(self.dashboard_service.load_dashboard, request)
            worker.finished.connect(lambda result, rid=request_id: self._on_dashboard_loaded(result, rid))
            worker.error.connect(lambda message, rid=request_id: self._on_dashboard_error(message, rid))
            worker.finished.connect(lambda _result, item=worker: self._release_worker(item))
            worker.error.connect(lambda _message, item=worker: self._release_worker(item))
            self._workers.append(worker)
            worker.start()
            return
        try:
            self._on_dashboard_loaded(self.dashboard_service.load_dashboard(request), request_id=request_id)
        except Exception as exc:  # noqa: BLE001
            self._on_dashboard_error(str(exc), request_id=request_id)

    def _on_dashboard_loaded(self, result: EvidenceOperationsHistoryDashboardResult, request_id: int) -> None:
        if request_id != self._active_request_id:
            return
        self.refresh_button.setEnabled(True)
        self._current_result = result
        for field_name, card in self.cards.items():
            self._set_card(card, card.property("title"), getattr(result.cards, field_name))
        self.empty_state_label.setText(result.empty_state_message)
        self.table_model.set_rows(result.rows)
        self.summary_table.resizeColumnsToContents()
        if result.rows:
            self._render_details(result.rows[0], result)
        else:
            self.detail_panel.setPlainText("\n".join(result.limitations))

    def _on_dashboard_error(self, message: str, request_id: int) -> None:
        if request_id != self._active_request_id:
            return
        self.refresh_button.setEnabled(True)
        self.table_model.set_rows(())
        self.empty_state_label.setText(f"Evidence operations history 載入失敗：{message.splitlines()[0]}")
        self.detail_panel.setPlainText("")

    def _on_table_row_clicked(self, index) -> None:
        row = self.table_model.row_at(index.row())
        if row is not None and self._current_result is not None:
            self._render_details(row, self._current_result)

    def _render_details(self, row, result: EvidenceOperationsHistoryDashboardResult) -> None:
        self.detail_panel.setPlainText(
            "\n".join(
                [
                    f"週期: {row.period_start} 至 {row.period_end}",
                    f"覆盤狀態: {row.review_status}",
                    f"Scheduler readiness: {row.scheduler_readiness}",
                    f"production scheduler allowed: {str(row.production_scheduler_allowed).lower()}",
                    f"Decision Quality reviews: {row.decision_quality_reviews_count}",
                    f"Signal Decay observations: {row.signal_decay_observations_count}",
                    f"Manual lifecycle candidates: {row.manual_lifecycle_candidate_count}",
                    f"Warnings: {row.warnings_count}",
                    f"Record ID: {row.review_id}",
                    "限制: " + " ".join(result.limitations),
                ]
            )
        )

    def _make_card(self, title: str) -> QLabel:
        card = QLabel(f"{title}\n0")
        card.setProperty("title", title)
        card.setAlignment(Qt.AlignCenter)
        card.setMinimumHeight(58)
        card.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_primary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-radius: 6px; padding: 6px;"
        )
        return card

    def _set_card(self, card: QLabel, title: str, value: int) -> None:
        card.setText(f"{title}\n{value}")

    def _release_worker(self, worker: TaskWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
