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

from app_module.live_research_gap_dashboard_dtos import LiveResearchGapDashboardRequest, LiveResearchGapDashboardResult
from ui_qt.models.live_research_gap_table_model import LiveResearchGapTableModel
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.date_filter_edit import OptionalDateFilterEdit, date_filter_value
from ui_qt.workers.task_worker import TaskWorker


PORTFOLIO_MODE_ITEMS = (
    ("", ""),
    ("模擬", "simulated"),
    ("未知", "unknown"),
    ("實際", "real"),
)
DATA_QUALITY_ITEMS = (
    ("", ""),
    ("已觀測", "observed"),
    ("降級", "degraded"),
    ("缺失", "missing"),
)
CARD_TITLES = {
    "positions_seen": "持倉筆數",
    "positions_linked": "已連結",
    "missing_source_trace": "缺來源追蹤",
    "missing_research_run": "缺研究 Run",
    "missing_evidence_event": "缺事件",
    "missing_evidence_outcome": "缺結果",
    "simulated_count": "模擬",
    "unknown_count": "未知",
    "large_gap_count": "大落差",
    "warnings_count": "警告",
}


class LiveResearchGapView(QWidget):
    def __init__(self, dashboard_service, *, auto_refresh: bool = True, async_refresh: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.dashboard_service = dashboard_service
        self.async_refresh = async_refresh
        self._active_request_id = 0
        self._workers: list[TaskWorker] = []
        self._current_result: LiveResearchGapDashboardResult | None = None
        self._setup_ui()
        if auto_refresh:
            self.refresh_dashboard()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        body = QSplitter(Qt.Horizontal)
        root.addWidget(body, stretch=1)

        filter_box = QGroupBox("研究落差篩選")
        form = QFormLayout(filter_box)
        self.observation_date_input = OptionalDateFilterEdit()
        self.symbol_input = QLineEdit()
        self.portfolio_id_input = QLineEdit()
        self.source_type_input = QLineEdit()
        self.strategy_version_id_input = QLineEdit()
        self.portfolio_mode_combo = QComboBox()
        for label, value in PORTFOLIO_MODE_ITEMS:
            self.portfolio_mode_combo.addItem(label, value)
        self.attribution_category_input = QLineEdit()
        self.data_quality_combo = QComboBox()
        for label, value in DATA_QUALITY_ITEMS:
            self.data_quality_combo.addItem(label, value)
        for label, widget in (
            ("觀測日期", self.observation_date_input),
            ("股票代號", self.symbol_input),
            ("Portfolio ID", self.portfolio_id_input),
            ("來源類型", self.source_type_input),
            ("策略版本", self.strategy_version_id_input),
            ("持倉模式", self.portfolio_mode_combo),
            ("歸因類別", self.attribution_category_input),
            ("資料品質", self.data_quality_combo),
        ):
            form.addRow(label, widget)
        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        form.addRow(self.refresh_button)
        body.addWidget(filter_box)

        right = QWidget()
        layout = QVBoxLayout(right)
        grid = QGridLayout()
        self.cards = {
            "positions_seen": self._make_card(CARD_TITLES["positions_seen"]),
            "positions_linked": self._make_card(CARD_TITLES["positions_linked"]),
            "missing_source_trace": self._make_card(CARD_TITLES["missing_source_trace"]),
            "missing_research_run": self._make_card(CARD_TITLES["missing_research_run"]),
            "missing_evidence_event": self._make_card(CARD_TITLES["missing_evidence_event"]),
            "missing_evidence_outcome": self._make_card(CARD_TITLES["missing_evidence_outcome"]),
            "simulated_count": self._make_card(CARD_TITLES["simulated_count"]),
            "unknown_count": self._make_card(CARD_TITLES["unknown_count"]),
            "large_gap_count": self._make_card(CARD_TITLES["large_gap_count"]),
            "warnings_count": self._make_card(CARD_TITLES["warnings_count"]),
        }
        for index, widget in enumerate(self.cards.values()):
            grid.addWidget(widget, index // 5, index % 5)
        layout.addLayout(grid)

        self.empty_state_label = QLabel("")
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.warning};")
        layout.addWidget(self.empty_state_label)

        self.table_model = LiveResearchGapTableModel()
        self.summary_table = QTableView()
        self.summary_table.setModel(self.table_model)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setSelectionBehavior(QTableView.SelectRows)
        self.summary_table.setFont(QFont("Consolas", 9))
        self.summary_table.clicked.connect(self._on_table_row_clicked)
        layout.addWidget(self.summary_table, stretch=3)

        self.detail_panel = QTextEdit()
        self.detail_panel.setReadOnly(True)
        self.detail_panel.setFont(QFont("Consolas", 9))
        layout.addWidget(self.detail_panel, stretch=1)
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

    def _request_from_controls(self) -> LiveResearchGapDashboardRequest:
        return LiveResearchGapDashboardRequest(
            observation_date=date_filter_value(self.observation_date_input),
            symbol=_text_or_none(self.symbol_input),
            portfolio_id=_text_or_none(self.portfolio_id_input),
            source_type=_text_or_none(self.source_type_input),
            strategy_version_id=_text_or_none(self.strategy_version_id_input),
            portfolio_mode=_combo_or_none(self.portfolio_mode_combo),
            attribution_category=_text_or_none(self.attribution_category_input),
            data_quality=_combo_or_none(self.data_quality_combo),
        )

    def _on_dashboard_loaded(self, result: LiveResearchGapDashboardResult, request_id: int) -> None:
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
        self.empty_state_label.setText(f"研究落差證據載入失敗：{message.splitlines()[0]}")
        self.detail_panel.setPlainText("")

    def _on_table_row_clicked(self, index) -> None:
        row = self.table_model.row_at(index.row())
        if row is not None and self._current_result is not None:
            self._render_details(row, self._current_result)

    def _render_details(self, row, result: LiveResearchGapDashboardResult) -> None:
        self.detail_panel.setPlainText(
            "\n".join(
                [
                    f"股票 / 模式: {row.symbol} / {row.portfolio_mode}",
                    f"來源: {row.source_type or '缺失'} / {row.source_id or '缺失'}",
                    f"策略版本: {row.strategy_version_id or '無'}",
                    f"連結信心: {row.match_confidence}",
                    f"歸因: {', '.join(row.attribution_categories) or '無'}",
                    f"資料品質: {row.quality}",
                    f"警告: {', '.join(row.warnings) or '無'}",
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
