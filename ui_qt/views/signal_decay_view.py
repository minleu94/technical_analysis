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
    QSpinBox,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_module.signal_decay_dashboard_dtos import SignalDecayDashboardRequest, SignalDecayDashboardResult
from ui_qt.models.signal_decay_table_model import SignalDecayTableModel
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.date_filter_edit import OptionalDateFilterEdit, date_filter_value
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.workers.task_worker import TaskWorker


SCOPE_TYPE_ITEMS = (
    ("", ""),
    ("事件類型", "event_type"),
    ("事件家族", "event_family"),
    ("策略版本", "strategy_version"),
    ("Profile", "profile"),
)
DECAY_STATUS_ITEMS = (
    ("", ""),
    ("穩定", "stable"),
    ("觀察", "watch"),
    ("衰退", "decaying"),
    ("嚴重衰退", "severe_decay"),
    ("樣本不足", "insufficient_sample"),
)
LIFECYCLE_ITEMS = (
    ("", ""),
    ("無", "none"),
    ("觀察", "watch"),
    ("降級候選", "demote_candidate"),
    ("退場候選", "retire_candidate"),
)
CONFIDENCE_ITEMS = (
    ("", ""),
    ("低", "low"),
    ("中", "medium"),
    ("高", "high"),
)
CARD_TITLES = {
    "scopes_evaluated": "已評估範圍",
    "stable_count": "穩定",
    "watch_count": "觀察",
    "decaying_count": "衰退",
    "severe_decay_count": "嚴重",
    "demote_candidate_count": "降級候選",
    "retire_candidate_count": "退場候選",
    "insufficient_sample_count": "樣本不足",
    "low_confidence_count": "低信心",
    "warnings_count": "警告",
}


class SignalDecayView(QWidget):
    def __init__(self, dashboard_service, *, auto_refresh: bool = True, async_refresh: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.dashboard_service = dashboard_service
        self.async_refresh = async_refresh
        self._active_request_id = 0
        self._workers: list[TaskWorker] = []
        self._current_result: SignalDecayDashboardResult | None = None
        self._setup_ui()
        if auto_refresh:
            self.refresh_dashboard()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        body = QSplitter(Qt.Horizontal)
        root.addWidget(body, stretch=1)

        filter_box = QGroupBox("訊號衰退篩選")
        form = QFormLayout(filter_box)
        self.observation_date_input = OptionalDateFilterEdit()
        self.scope_type_combo = QComboBox()
        for label, value in SCOPE_TYPE_ITEMS:
            self.scope_type_combo.addItem(label, value)
        self.scope_id_input = QLineEdit()
        self.event_type_input = QLineEdit()
        self.event_family_input = QLineEdit()
        self.strategy_version_id_input = QLineEdit()
        self.profile_id_input = QLineEdit()
        self.decay_status_combo = QComboBox()
        for label, value in DECAY_STATUS_ITEMS:
            self.decay_status_combo.addItem(label, value)
        self.lifecycle_combo = QComboBox()
        for label, value in LIFECYCLE_ITEMS:
            self.lifecycle_combo.addItem(label, value)
        self.confidence_combo = QComboBox()
        for label, value in CONFIDENCE_ITEMS:
            self.confidence_combo.addItem(label, value)
        self.min_sample_size_input = QSpinBox()
        self.min_sample_size_input.setRange(1, 100000)
        self.min_sample_size_input.setValue(10)
        for label, widget in (
            ("觀測日期", self.observation_date_input),
            ("範圍類型", self.scope_type_combo),
            ("範圍 ID", self.scope_id_input),
            ("事件類型", self.event_type_input),
            ("事件家族", self.event_family_input),
            ("策略版本", self.strategy_version_id_input),
            ("Profile", self.profile_id_input),
            ("衰退狀態", self.decay_status_combo),
            ("生命週期候選", self.lifecycle_combo),
            ("信心", self.confidence_combo),
            ("最小樣本數", self.min_sample_size_input),
        ):
            form.addRow(label, widget)
        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.setProperty("variant", "primary")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        form.addRow(self.refresh_button)
        body.addWidget(filter_box)

        right = QWidget()
        layout = QVBoxLayout(right)
        grid = QGridLayout()
        self.cards = {
            "scopes_evaluated": self._make_card(CARD_TITLES["scopes_evaluated"]),
            "stable_count": self._make_card(CARD_TITLES["stable_count"]),
            "watch_count": self._make_card(CARD_TITLES["watch_count"]),
            "decaying_count": self._make_card(CARD_TITLES["decaying_count"]),
            "severe_decay_count": self._make_card(CARD_TITLES["severe_decay_count"]),
            "demote_candidate_count": self._make_card(CARD_TITLES["demote_candidate_count"]),
            "retire_candidate_count": self._make_card(CARD_TITLES["retire_candidate_count"]),
            "insufficient_sample_count": self._make_card(CARD_TITLES["insufficient_sample_count"]),
            "low_confidence_count": self._make_card(CARD_TITLES["low_confidence_count"]),
            "warnings_count": self._make_card(CARD_TITLES["warnings_count"]),
        }
        for index, widget in enumerate(self.cards.values()):
            grid.addWidget(widget, index // 5, index % 5)
        layout.addLayout(grid)

        self.empty_state_label = QLabel("")
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.warning};")
        layout.addWidget(self.empty_state_label)

        self.table_model = SignalDecayTableModel()
        self.summary_table = QTableView()
        self.summary_table.setModel(self.table_model)
        apply_financial_table_style(self.summary_table)
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

    def _request_from_controls(self) -> SignalDecayDashboardRequest:
        return SignalDecayDashboardRequest(
            observation_date=date_filter_value(self.observation_date_input),
            scope_type=_combo_or_none(self.scope_type_combo),
            scope_id=_text_or_none(self.scope_id_input),
            event_type=_text_or_none(self.event_type_input),
            event_family=_text_or_none(self.event_family_input),
            strategy_version_id=_text_or_none(self.strategy_version_id_input),
            profile_id=_text_or_none(self.profile_id_input),
            decay_status=_combo_or_none(self.decay_status_combo),
            suggested_lifecycle_action=_combo_or_none(self.lifecycle_combo),
            confidence=_combo_or_none(self.confidence_combo),
            min_sample_size=self.min_sample_size_input.value(),
        )

    def _on_dashboard_loaded(self, result: SignalDecayDashboardResult, request_id: int) -> None:
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
        self.empty_state_label.setText(f"訊號衰退證據載入失敗：{message.splitlines()[0]}")
        self.detail_panel.setPlainText("")

    def _on_table_row_clicked(self, index) -> None:
        row = self.table_model.row_at(index.row())
        if row is not None and self._current_result is not None:
            self._render_details(row, self._current_result)

    def _render_details(self, row, result: SignalDecayDashboardResult) -> None:
        self.detail_panel.setPlainText(
            "\n".join(
                [
                    f"範圍: {row.signal_scope_type} = {row.signal_scope_id}",
                    f"短窗 / 長窗樣本: {row.sample_size_short} / {row.sample_size_long}",
                    f"狀態 / 候選 / 信心: {row.decay_status} / {row.suggested_lifecycle_action} / {row.confidence}",
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
