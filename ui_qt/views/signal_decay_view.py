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
from ui_qt.workers.task_worker import TaskWorker


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

        filter_box = QGroupBox("Signal Decay Filters")
        form = QFormLayout(filter_box)
        self.observation_date_input = QLineEdit()
        self.scope_type_combo = QComboBox()
        self.scope_type_combo.addItems(["", "event_type", "event_family", "strategy_version", "profile"])
        self.scope_id_input = QLineEdit()
        self.event_type_input = QLineEdit()
        self.event_family_input = QLineEdit()
        self.strategy_version_id_input = QLineEdit()
        self.profile_id_input = QLineEdit()
        self.decay_status_combo = QComboBox()
        self.decay_status_combo.addItems(["", "stable", "watch", "decaying", "severe_decay", "insufficient_sample"])
        self.lifecycle_combo = QComboBox()
        self.lifecycle_combo.addItems(["", "none", "watch", "demote_candidate", "retire_candidate"])
        self.confidence_combo = QComboBox()
        self.confidence_combo.addItems(["", "low", "medium", "high"])
        self.min_sample_size_input = QSpinBox()
        self.min_sample_size_input.setRange(1, 100000)
        self.min_sample_size_input.setValue(10)
        for label, widget in (
            ("observation_date", self.observation_date_input),
            ("scope_type", self.scope_type_combo),
            ("scope_id", self.scope_id_input),
            ("event_type", self.event_type_input),
            ("event_family", self.event_family_input),
            ("strategy_version_id", self.strategy_version_id_input),
            ("profile_id", self.profile_id_input),
            ("decay_status", self.decay_status_combo),
            ("lifecycle_candidate", self.lifecycle_combo),
            ("confidence", self.confidence_combo),
            ("min_sample_size", self.min_sample_size_input),
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
            "scopes_evaluated": self._make_card("Scopes"),
            "stable_count": self._make_card("Stable"),
            "watch_count": self._make_card("Watch"),
            "decaying_count": self._make_card("Decaying"),
            "severe_decay_count": self._make_card("Severe"),
            "demote_candidate_count": self._make_card("Demote Candidate"),
            "retire_candidate_count": self._make_card("Retire Candidate"),
            "insufficient_sample_count": self._make_card("Insufficient"),
            "low_confidence_count": self._make_card("Low Confidence"),
            "warnings_count": self._make_card("Warnings"),
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

    def _request_from_controls(self) -> SignalDecayDashboardRequest:
        return SignalDecayDashboardRequest(
            observation_date=_text_or_none(self.observation_date_input),
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
        self.empty_state_label.setText(f"Signal decay evidence 載入失敗：{message.splitlines()[0]}")
        self.detail_panel.setPlainText("")

    def _on_table_row_clicked(self, index) -> None:
        row = self.table_model.row_at(index.row())
        if row is not None and self._current_result is not None:
            self._render_details(row, self._current_result)

    def _render_details(self, row, result: SignalDecayDashboardResult) -> None:
        self.detail_panel.setPlainText(
            "\n".join(
                [
                    f"scope: {row.signal_scope_type} = {row.signal_scope_id}",
                    f"sample short/long: {row.sample_size_short} / {row.sample_size_long}",
                    f"status/candidate/confidence: {row.decay_status} / {row.suggested_lifecycle_action} / {row.confidence}",
                    f"quality: {row.quality}",
                    f"warnings: {', '.join(row.warnings) or 'None'}",
                    "limitations: " + " ".join(result.limitations),
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
    text = widget.currentText().strip()
    return text or None
