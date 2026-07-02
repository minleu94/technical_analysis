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
from ui_qt.widgets.date_filter_edit import OptionalDateFilterEdit, date_filter_value
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.workers.task_worker import TaskWorker


GROUP_BY_LABELS = {
    "event_type": "事件類型",
    "event_family": "事件家族",
    "source_type": "來源類型",
    "regime": "市場狀態",
    "sector": "產業",
    "profile_id": "Profile",
    "score_percentile_bucket": "分數分位桶",
    "liquidity_state": "流動性狀態",
    "data_quality": "資料品質",
}


CARD_TITLES = {
    "total_events": "事件總數",
    "ready_outcomes": "已完成結果",
    "pending_outcomes": "等待中結果",
    "missing_outcomes": "缺失結果",
    "groups_ready": "可用群組",
    "groups_insufficient": "樣本不足群組",
    "groups_degraded": "降級群組",
    "missing_benchmark": "缺大盤基準",
    "missing_industry": "缺產業基準",
    "warnings": "警告",
}


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

        title = QLabel("前瞻績效證據")
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

        filter_box = QGroupBox("篩選條件")
        filter_layout = QFormLayout(filter_box)
        filter_layout.setContentsMargins(10, 10, 10, 10)
        filter_layout.setSpacing(6)

        self.start_date_input = OptionalDateFilterEdit()
        self.end_date_input = OptionalDateFilterEdit()
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
        for value in SUPPORTED_DASHBOARD_GROUP_BY:
            self.group_by_combo.addItem(GROUP_BY_LABELS.get(value, value), value)
        self.group_by_combo.setCurrentIndex(self.group_by_combo.findData("event_type"))

        filter_layout.addRow("開始日期", self.start_date_input)
        filter_layout.addRow("結束日期", self.end_date_input)
        filter_layout.addRow("事件類型", self.event_type_input)
        filter_layout.addRow("事件家族", self.event_family_input)
        filter_layout.addRow("來源類型", self.source_type_input)
        filter_layout.addRow("股票代號", self.symbol_input)
        filter_layout.addRow("市場狀態", self.regime_input)
        filter_layout.addRow("產業", self.sector_input)
        filter_layout.addRow("Profile", self.profile_id_input)
        filter_layout.addRow("策略版本", self.strategy_version_id_input)
        filter_layout.addRow("觀察天數", self.window_days_input)
        filter_layout.addRow("分組方式", self.group_by_combo)
        filter_layout.addRow("最小樣本數", self.min_sample_size_input)

        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.setProperty("variant", "primary")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        filter_layout.addRow(self.refresh_button)
        body.addWidget(filter_box)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        card_grid = QGridLayout()
        self.total_events_card = self._make_card(CARD_TITLES["total_events"])
        self.ready_outcomes_card = self._make_card(CARD_TITLES["ready_outcomes"])
        self.pending_outcomes_card = self._make_card(CARD_TITLES["pending_outcomes"])
        self.missing_outcomes_card = self._make_card(CARD_TITLES["missing_outcomes"])
        self.groups_ready_card = self._make_card(CARD_TITLES["groups_ready"])
        self.groups_insufficient_card = self._make_card(CARD_TITLES["groups_insufficient"])
        self.groups_degraded_card = self._make_card(CARD_TITLES["groups_degraded"])
        self.missing_benchmark_card = self._make_card(CARD_TITLES["missing_benchmark"])
        self.missing_industry_card = self._make_card(CARD_TITLES["missing_industry"])
        self.warnings_card = self._make_card(CARD_TITLES["warnings"])
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
        apply_financial_table_style(self.summary_table)
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
            start_date=date_filter_value(self.start_date_input),
            end_date=date_filter_value(self.end_date_input),
            event_type=_text_or_none(self.event_type_input),
            event_family=_text_or_none(self.event_family_input),
            source_type=_text_or_none(self.source_type_input),
            symbol=_text_or_none(self.symbol_input),
            regime=_text_or_none(self.regime_input),
            sector=_text_or_none(self.sector_input),
            profile_id=_text_or_none(self.profile_id_input),
            strategy_version_id=_text_or_none(self.strategy_version_id_input),
            window_days=self.window_days_input.value(),
            group_by=str(self.group_by_combo.currentData() or self.group_by_combo.currentText()),
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
        self.empty_state_label.setText(f"前瞻證據載入失敗：{message.splitlines()[0]}")
        self.detail_panel.setPlainText("")

    def _render_result(self, result: ForwardPerformanceDashboardResult) -> None:
        cards = result.cards
        self._current_result = result
        self._set_card(self.total_events_card, CARD_TITLES["total_events"], cards.total_events)
        self._set_card(self.ready_outcomes_card, CARD_TITLES["ready_outcomes"], cards.ready_outcomes)
        self._set_card(self.pending_outcomes_card, CARD_TITLES["pending_outcomes"], cards.pending_outcomes)
        self._set_card(self.missing_outcomes_card, CARD_TITLES["missing_outcomes"], cards.missing_outcomes)
        self._set_card(self.groups_ready_card, CARD_TITLES["groups_ready"], cards.groups_ready)
        self._set_card(self.groups_insufficient_card, CARD_TITLES["groups_insufficient"], cards.groups_insufficient_sample)
        self._set_card(self.groups_degraded_card, CARD_TITLES["groups_degraded"], cards.groups_degraded)
        self._set_card(self.missing_benchmark_card, CARD_TITLES["missing_benchmark"], cards.missing_benchmark_count)
        self._set_card(self.missing_industry_card, CARD_TITLES["missing_industry"], cards.missing_industry_count)
        self._set_card(self.warnings_card, CARD_TITLES["warnings"], cards.warnings_count)
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
                    f"定義: {row.group_by} = {row.group_key}",
                    f"套用篩選: 開始={filters.start_date or '全部'}, 結束={filters.end_date or '全部'}, "
                    f"事件類型={filters.event_type or '全部'}, 來源類型={filters.source_type or '全部'}, "
                    f"股票={filters.symbol or '全部'}, 觀察天數={filters.window_days}",
                    f"樣本 / 等待 / 缺失: {row.sample_size} / {row.pending_count} / {row.missing_count}",
                    f"資料品質分布: {quality}",
                    f"警告分布: {warnings}",
                    f"大盤基準可用性: {benchmark_note}",
                    f"產業基準可用性: {industry_note}",
                    "報酬基礎: Close-to-close forward research basis",
                    "限制: 這是 research evidence，不是買賣建議；不能證明任一事件類型有效。",
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
    return ", ".join(f"{key}:{counts[key]}" for key in sorted(counts)) or "無"
