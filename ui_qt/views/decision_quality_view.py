from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_module.decision_quality_dashboard_dtos import DecisionQualityDashboardRequest, DecisionQualityDashboardResult
from ui_qt.models.decision_quality_table_model import DecisionQualityTableModel
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.date_filter_edit import OptionalDateFilterEdit, date_filter_value
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.workers.task_worker import TaskWorker


SEVERITY_ITEMS = (
    ("", ""),
    ("低", "low"),
    ("中", "medium"),
    ("高", "high"),
)
STATUS_ITEMS = (
    ("", ""),
    ("待處理", "open"),
    ("已覆盤", "reviewed"),
    ("已略過", "dismissed"),
)
CARD_TITLES = {
    "decision_quality_score": "決策品質",
    "process_adherence_score": "流程遵循",
    "evidence_usage_score": "證據使用",
    "risk_discipline_score": "風險紀律",
    "review_completeness_score": "覆盤完整度",
    "open_items": "待處理",
    "reviewed_items": "已覆盤",
    "dismissed_items": "已略過",
    "warnings_count": "警告",
}


class DecisionQualityView(QWidget):
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
        self._current_result: DecisionQualityDashboardResult | None = None
        self._setup_ui()
        if auto_refresh:
            self.refresh_dashboard()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        body = QSplitter(Qt.Horizontal)
        root.addWidget(body, stretch=1)

        filter_box = QGroupBox("決策品質篩選")
        filter_layout = QFormLayout(filter_box)
        self.review_type_input = QLineEdit()
        self.start_date_input = OptionalDateFilterEdit()
        self.end_date_input = OptionalDateFilterEdit()
        self.symbol_input = QLineEdit()
        self.portfolio_id_input = QLineEdit()
        self.item_type_input = QLineEdit()
        self.severity_combo = QComboBox()
        for label, value in SEVERITY_ITEMS:
            self.severity_combo.addItem(label, value)
        self.status_combo = QComboBox()
        for label, value in STATUS_ITEMS:
            self.status_combo.addItem(label, value)
        self.min_score_input = QLineEdit()
        self.min_score_input.setPlaceholderText("0-10000")
        for label, widget in (
            ("覆盤類型", self.review_type_input),
            ("開始日期", self.start_date_input),
            ("結束日期", self.end_date_input),
            ("股票代號", self.symbol_input),
            ("Portfolio ID", self.portfolio_id_input),
            ("項目類型", self.item_type_input),
            ("嚴重度", self.severity_combo),
            ("狀態", self.status_combo),
            ("最低分數", self.min_score_input),
        ):
            filter_layout.addRow(label, widget)
        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.setProperty("variant", "primary")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        filter_layout.addRow(self.refresh_button)
        body.addWidget(filter_box)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        cards = QGridLayout()
        self.cards = {
            "decision_quality_score": self._make_card(CARD_TITLES["decision_quality_score"]),
            "process_adherence_score": self._make_card(CARD_TITLES["process_adherence_score"]),
            "evidence_usage_score": self._make_card(CARD_TITLES["evidence_usage_score"]),
            "risk_discipline_score": self._make_card(CARD_TITLES["risk_discipline_score"]),
            "review_completeness_score": self._make_card(CARD_TITLES["review_completeness_score"]),
            "open_items": self._make_card(CARD_TITLES["open_items"]),
            "reviewed_items": self._make_card(CARD_TITLES["reviewed_items"]),
            "dismissed_items": self._make_card(CARD_TITLES["dismissed_items"]),
            "warnings_count": self._make_card(CARD_TITLES["warnings_count"]),
        }
        for index, widget in enumerate(self.cards.values()):
            cards.addWidget(widget, index // 5, index % 5)
        right_layout.addLayout(cards)

        self.empty_state_label = QLabel("")
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.warning};")
        right_layout.addWidget(self.empty_state_label)

        self.table_model = DecisionQualityTableModel()
        self.summary_table = QTableView()
        self.summary_table.setModel(self.table_model)
        apply_financial_table_style(self.summary_table)
        self.summary_table.setSelectionBehavior(QTableView.SelectRows)
        self.summary_table.setFont(QFont("Consolas", 9))
        self.summary_table.clicked.connect(self._on_table_row_clicked)
        right_layout.addWidget(self.summary_table, stretch=3)

        self.detail_panel = QTextEdit()
        self.detail_panel.setReadOnly(True)
        self.detail_panel.setFont(QFont("Consolas", 9))
        right_layout.addWidget(self.detail_panel, stretch=1)
        body.addWidget(right)
        body.setSizes([260, 900])

    def refresh_dashboard(self) -> None:
        request = self._request_from_controls()
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

    def _request_from_controls(self) -> DecisionQualityDashboardRequest:
        return DecisionQualityDashboardRequest(
            review_type=_text_or_none(self.review_type_input),
            start_date=date_filter_value(self.start_date_input),
            end_date=date_filter_value(self.end_date_input),
            symbol=_text_or_none(self.symbol_input),
            portfolio_id=_text_or_none(self.portfolio_id_input),
            item_type=_text_or_none(self.item_type_input),
            severity=_combo_or_none(self.severity_combo),
            status=_combo_or_none(self.status_combo),
            min_score=_int_or_none(self.min_score_input),
        )

    def _on_dashboard_loaded(self, result: DecisionQualityDashboardResult, request_id: int) -> None:
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
        self.empty_state_label.setText(f"決策品質證據載入失敗：{message.splitlines()[0]}")
        self.detail_panel.setPlainText("")

    def _on_table_row_clicked(self, index) -> None:
        row = self.table_model.row_at(index.row())
        if row is not None and self._current_result is not None:
            self._render_details(row, self._current_result)

    def _render_details(self, row, result: DecisionQualityDashboardResult) -> None:
        self.detail_panel.setPlainText(
            "\n".join(
                [
                    f"項目類型: {row.item_type}",
                    f"股票 / 來源: {row.symbol or '全部'} / {row.source_type or '未知'}",
                    f"嚴重度 / 狀態: {row.severity} / {row.status}",
                    f"原因代碼: {', '.join(row.reason_codes) or '無'}",
                    f"相關落差 ID: {row.related_gap_id or '無'}",
                    f"相關衰退 ID: {row.related_decay_id or '無'}",
                    f"資料品質: {row.quality}",
                    f"警告: {', '.join(row.warnings) or '無'}",
                    f"覆盤問題: {row.suggested_review_question}",
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


def _text_or_none(widget: QLineEdit) -> str | None:
    text = widget.text().strip()
    return text or None


def _combo_or_none(widget: QComboBox) -> str | None:
    data = widget.currentData()
    text = str(data).strip() if data is not None else widget.currentText().strip()
    return text or None


def _int_or_none(widget: QLineEdit) -> int | None:
    text = widget.text().strip()
    return int(text) if text else None
