from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
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

from app_module.forward_performance_dashboard_dtos import (
    DASHBOARD_STATUS_INSUFFICIENT_SAMPLE,
    DASHBOARD_STATUS_MISSING_BENCHMARK,
    SUPPORTED_DASHBOARD_GROUP_BY,
    ForwardPerformanceDashboardRequest,
    ForwardPerformanceDashboardResult,
    ForwardPerformanceDashboardRow,
)
from ui_qt.models.forward_performance_table_model import ForwardPerformanceTableModel
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.workers.task_worker import TaskWorker


class ForwardPerformanceView(QWidget):
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
        self._current_result: ForwardPerformanceDashboardResult | None = None
        self._setup_ui()
        if auto_refresh:
            self.refresh_dashboard()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel("Forward Performance Evidence")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")
        root.addWidget(title)

        self.boundary_label = QLabel(
            "這是 research evidence，不是買賣建議。Close-to-close forward return 不代表實盤可執行績效。"
        )
        self.boundary_label.setWordWrap(True)
        self.boundary_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.warning}; background: {MIDNIGHT_ANALYST.surface_2}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-radius: 6px; padding: 7px;"
        )
        root.addWidget(self.boundary_label)

        body = QSplitter(Qt.Horizontal)
        root.addWidget(body, stretch=1)

        filter_box = QGroupBox("Filters")
        filter_layout = QFormLayout(filter_box)
        filter_layout.setContentsMargins(10, 10, 10, 10)
        filter_layout.setSpacing(6)

        self.start_date_input = QLineEdit()
        self.start_date_input.setPlaceholderText("YYYY-MM-DD")
        self.end_date_input = QLineEdit()
        self.end_date_input.setPlaceholderText("YYYY-MM-DD")
        self.event_type_input = QLineEdit()
        self.event_family_input = QLineEdit()
        self.source_type_input = QLineEdit()
        self.symbol_input = QLineEdit()
        self.regime_input = QLineEdit()
        self.sector_input = QLineEdit()
        self.profile_id_input = QLineEdit()
        self.strategy_version_id_input = QLineEdit()

        self.window_days_input = QSpinBox()
        self.window_days_input.setRange(1, 252)
        self.window_days_input.setValue(20)
        self.min_sample_size_input = QSpinBox()
        self.min_sample_size_input.setRange(1, 100000)
        self.min_sample_size_input.setValue(10)
        self.group_by_combo = QComboBox()
        self.group_by_combo.addItems(list(SUPPORTED_DASHBOARD_GROUP_BY))
        self.group_by_combo.setCurrentText("event_type")

        filter_layout.addRow("start_date", self.start_date_input)
        filter_layout.addRow("end_date", self.end_date_input)
        filter_layout.addRow("event_type", self.event_type_input)
        filter_layout.addRow("event_family", self.event_family_input)
        filter_layout.addRow("source_type", self.source_type_input)
        filter_layout.addRow("symbol", self.symbol_input)
        filter_layout.addRow("regime", self.regime_input)
        filter_layout.addRow("sector", self.sector_input)
        filter_layout.addRow("profile_id", self.profile_id_input)
        filter_layout.addRow("strategy_version_id", self.strategy_version_id_input)
        filter_layout.addRow("window_days", self.window_days_input)
        filter_layout.addRow("group_by", self.group_by_combo)
        filter_layout.addRow("min_sample_size", self.min_sample_size_input)

        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        filter_layout.addRow(self.refresh_button)
        body.addWidget(filter_box)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        card_grid = QGridLayout()
        self.total_events_card = self._make_card("Total Events")
        self.ready_outcomes_card = self._make_card("Ready Outcomes")
        self.pending_outcomes_card = self._make_card("Pending Outcomes")
        self.missing_outcomes_card = self._make_card("Missing Outcomes")
        self.groups_ready_card = self._make_card("Groups Ready")
        self.groups_insufficient_card = self._make_card("Insufficient Groups")
        self.groups_degraded_card = self._make_card("Degraded Groups")
        self.missing_benchmark_card = self._make_card("Missing Benchmark")
        self.missing_industry_card = self._make_card("Missing Industry")
        self.warnings_card = self._make_card("Warnings")
        for index, widget in enumerate(
            (
                self.total_events_card,
                self.ready_outcomes_card,
                self.pending_outcomes_card,
                self.missing_outcomes_card,
                self.groups_ready_card,
                self.groups_insufficient_card,
                self.groups_degraded_card,
                self.missing_benchmark_card,
                self.missing_industry_card,
                self.warnings_card,
            )
        ):
            card_grid.addWidget(widget, index // 5, index % 5)
        right_layout.addLayout(card_grid)

        self.empty_state_label = QLabel("")
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.warning};")
        right_layout.addWidget(self.empty_state_label)

        self.table_model = ForwardPerformanceTableModel()
        self.summary_table = QTableView()
        self.summary_table.setModel(self.table_model)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setSortingEnabled(False)
        self.summary_table.setSelectionBehavior(QTableView.SelectRows)
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setFont(QFont("Consolas", 9))
        self.summary_table.clicked.connect(self._on_table_row_clicked)
        right_layout.addWidget(self.summary_table, stretch=3)

        self.detail_panel = QTextEdit()
        self.detail_panel.setReadOnly(True)
        self.detail_panel.setMinimumHeight(150)
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
            worker.finished.connect(lambda _result, item=worker: self._workers.remove(item) if item in self._workers else None)
            worker.error.connect(lambda _message, item=worker: self._workers.remove(item) if item in self._workers else None)
            self._workers.append(worker)
            worker.start()
            return
        try:
            result = self.dashboard_service.load_dashboard(request)
            self._on_dashboard_loaded(result, request_id=request_id)
        except Exception as exc:  # noqa: BLE001
            self._on_dashboard_error(str(exc), request_id=request_id)

    def _request_from_controls(self) -> ForwardPerformanceDashboardRequest:
        return ForwardPerformanceDashboardRequest(
            start_date=_text_or_none(self.start_date_input),
            end_date=_text_or_none(self.end_date_input),
            event_type=_text_or_none(self.event_type_input),
            event_family=_text_or_none(self.event_family_input),
            source_type=_text_or_none(self.source_type_input),
            symbol=_text_or_none(self.symbol_input),
            regime=_text_or_none(self.regime_input),
            sector=_text_or_none(self.sector_input),
            profile_id=_text_or_none(self.profile_id_input),
            strategy_version_id=_text_or_none(self.strategy_version_id_input),
            window_days=self.window_days_input.value(),
            group_by=self.group_by_combo.currentText(),
            min_sample_size=self.min_sample_size_input.value(),
        )

    def _on_dashboard_loaded(self, result: ForwardPerformanceDashboardResult, request_id: int) -> None:
        if request_id != self._active_request_id:
            return
        self.refresh_button.setEnabled(True)
        self._render_result(result)

    def _on_dashboard_error(self, message: str, request_id: int) -> None:
        if request_id != self._active_request_id:
            return
        self.refresh_button.setEnabled(True)
        self.table_model.set_rows(())
        self._current_result = None
        self.empty_state_label.setText(f"Forward evidence 載入失敗：{message.splitlines()[0]}")
        self.detail_panel.setPlainText("")

    def _render_result(self, result: ForwardPerformanceDashboardResult) -> None:
        cards = result.cards
        self._current_result = result
        self._set_card(self.total_events_card, "Total Events", cards.total_events)
        self._set_card(self.ready_outcomes_card, "Ready Outcomes", cards.ready_outcomes)
        self._set_card(self.pending_outcomes_card, "Pending Outcomes", cards.pending_outcomes)
        self._set_card(self.missing_outcomes_card, "Missing Outcomes", cards.missing_outcomes)
        self._set_card(self.groups_ready_card, "Groups Ready", cards.groups_ready)
        self._set_card(self.groups_insufficient_card, "Insufficient Groups", cards.groups_insufficient_sample)
        self._set_card(self.groups_degraded_card, "Degraded Groups", cards.groups_degraded)
        self._set_card(self.missing_benchmark_card, "Missing Benchmark", cards.missing_benchmark_count)
        self._set_card(self.missing_industry_card, "Missing Industry", cards.missing_industry_count)
        self._set_card(self.warnings_card, "Warnings", cards.warnings_count)
        self.empty_state_label.setText(result.empty_state_message)
        self.table_model.set_rows(result.rows)
        self.summary_table.resizeColumnsToContents()
        if result.rows:
            self._render_details(result.rows[0], result)
        else:
            self.detail_panel.setPlainText("\n".join(result.limitations))

    def _on_table_row_clicked(self, index) -> None:
        row = self.table_model.row_at(index.row())
        if row is not None and self._current_result is not None:
            self._render_details(row, self._current_result)

    def _render_details(
        self,
        row: ForwardPerformanceDashboardRow,
        result: ForwardPerformanceDashboardResult,
    ) -> None:
        filters = result.request
        quality = _format_counts(row.quality_counts)
        warnings = _format_counts(row.warning_counts)
        benchmark_note = "可計算" if row.mean_benchmark_excess_bp is not None else "Benchmark 缺失，無法判斷相對大盤超額。"
        industry_note = "可計算" if row.mean_industry_excess_bp is not None else "Industry benchmark 缺失，無法判斷相對同產業超額。"
        sample_note = ""
        if row.summary_status == DASHBOARD_STATUS_INSUFFICIENT_SAMPLE:
            sample_note = "樣本不足，只能作資料品質檢查，不可作訊號有效性判斷。"
        elif row.summary_status == DASHBOARD_STATUS_MISSING_BENCHMARK:
            sample_note = "Benchmark 缺失，無法判斷相對大盤超額。"

        self.detail_panel.setPlainText(
            "\n".join(
                [
                    f"definition: {row.group_by} = {row.group_key}",
                    f"applied filters: start={filters.start_date or 'Any'}, end={filters.end_date or 'Any'}, "
                    f"event_type={filters.event_type or 'Any'}, source_type={filters.source_type or 'Any'}, "
                    f"symbol={filters.symbol or 'Any'}, window_days={filters.window_days}",
                    f"sample / pending / missing: {row.sample_size} / {row.pending_count} / {row.missing_count}",
                    f"quality breakdown: {quality}",
                    f"warning breakdown: {warnings}",
                    f"benchmark availability: {benchmark_note}",
                    f"industry benchmark availability: {industry_note}",
                    "return basis: Close-to-close forward research basis",
                    "limitations: 這是 research evidence，不是買賣建議；不能證明任一事件類型有效。",
                    sample_note,
                ]
            ).strip()
        )

    def _make_card(self, title: str) -> QLabel:
        card = QLabel(f"{title}\n0")
        card.setAlignment(Qt.AlignCenter)
        card.setMinimumHeight(58)
        card.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_primary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-radius: 6px; padding: 6px;"
        )
        return card

    def _set_card(self, card: QLabel, title: str, value: int) -> None:
        card.setText(f"{title}\n{value}")


def _text_or_none(widget: QLineEdit) -> str | None:
    text = widget.text().strip()
    return text or None


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}:{counts[key]}" for key in sorted(counts)) or "None"
