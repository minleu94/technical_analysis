"""可互動的單股研究報告視圖。

畫面只呈現 ``StockResearchReportDTO``；所有真資料查詢都由
``TaskWorker`` 執行，且以 request id + stock code 丟棄過期回傳。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app_module.research_session import ResearchStockContextDTO
from app_module.stock_research_report_dtos import (
    ReportSectionStatus,
    StockAdviceSnapshotDTO,
    StockEvidenceEventDTO,
    StockFlowObservationDTO,
    StockFundamentalObservationDTO,
    StockMetricDTO,
    StockPositionSnapshotDTO,
    StockPricePointDTO,
    StockResearchReportDTO,
)
from app_module.stock_research_report_service import StockResearchReportReadService
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.theme_widgets import StatusBadge
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.workers.task_worker import TaskWorker


class StockReportTableModel(QAbstractTableModel):
    """針對有限 DTO rows 的小型 Qt model，保留完整 tooltip 文字。"""

    def __init__(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns = tuple(columns)
        self._rows = tuple(tuple(str(cell) for cell in row) for row in rows)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if index.column() >= len(row):
            return None
        value = row[index.column()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return value
        if role == Qt.TextAlignmentRole:
            return Qt.AlignLeft | Qt.AlignVCenter
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and section < len(self._columns):
            return self._columns[section]
        if orientation == Qt.Vertical:
            return str(section + 1)
        return None


class StockPriceChartWidget(QWidget):
    """無第三方互動依賴的 bounded price chart，提供文字替代。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: tuple[StockPricePointDTO, ...] = ()
        self.setMinimumHeight(188)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("個股收盤價走勢圖")
        self.setAccessibleDescription(
            "最近有限交易日的收盤價走勢；下方價格表提供可選取的日期與數值。"
        )

    def set_points(self, points: Sequence[StockPricePointDTO]) -> None:
        self._points = tuple(points)
        if self._points:
            last = self._points[-1]
            self.setToolTip(
                f"最新資料日：{last.data_date}；收盤價：{_decimal_text(last.close_price)}。"
                "圖表只作視覺化，不代表預測。"
            )
        else:
            self.setToolTip("目前沒有可繪製的價格資料。")
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QBrush(MIDNIGHT_ANALYST.surface_1))
        points = tuple(point for point in self._points if point.close_price is not None)
        if not points:
            painter.setPen(QPen(MIDNIGHT_ANALYST.text_muted))
            painter.drawText(self.rect(), Qt.AlignCenter, "無價格資料")
            return

        left = 58
        right = max(left + 40, self.width() - 18)
        top = 25
        bottom = max(top + 50, self.height() - 32)
        values = tuple(point.close_price for point in points if point.close_price is not None)
        low = min(values)
        high = max(values)
        span = high - low
        if span == 0:
            span = Decimal("1")

        painter.setPen(QPen(MIDNIGHT_ANALYST.border))
        painter.drawLine(left, bottom, right, bottom)
        painter.drawLine(left, top, left, bottom)
        painter.setPen(QPen(MIDNIGHT_ANALYST.text_secondary))
        painter.drawText(6, top + 4, "收盤價")
        painter.drawText(6, bottom, "TWD")
        painter.drawText(left, self.height() - 8, points[0].data_date)
        last_date = points[-1].data_date
        painter.drawText(max(left, right - 88), self.height() - 8, last_date)
        painter.drawText(6, top + 22, _decimal_text(high))
        painter.drawText(6, bottom - 5, _decimal_text(low))

        path_points: list[QPoint] = []
        denominator = max(1, len(points) - 1)
        for index, point in enumerate(points):
            assert point.close_price is not None
            x = left + int(Decimal(right - left) * Decimal(index) / Decimal(denominator))
            y = bottom - int(
                Decimal(bottom - top) * (point.close_price - low) / span
            )
            path_points.append(QPoint(x, y))
        painter.setPen(QPen(MIDNIGHT_ANALYST.accent, 2))
        for first, second in zip(path_points, path_points[1:]):
            painter.drawLine(first, second)
        painter.setBrush(QBrush(MIDNIGHT_ANALYST.accent))
        painter.setPen(QPen(MIDNIGHT_ANALYST.accent))
        painter.drawEllipse(path_points[-1], 3, 3)


class StockResearchReportView(QWidget):
    """報告內容本體，可被非模態 QDialog 或測試直接使用。"""

    reportLoaded = Signal(object)
    reportFailed = Signal(str)
    returnRequested = Signal()
    readyToClose = Signal()

    def __init__(
        self,
        service: StockResearchReportReadService,
        context: ResearchStockContextDTO | None = None,
        *,
        stock_codes: Sequence[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.context = context
        self.stock_codes = tuple(str(code).strip() for code in stock_codes if str(code).strip())
        self._request_id = 0
        self._active_code = ""
        self._active_worker: TaskWorker | None = None
        self._workers: set[TaskWorker] = set()
        self._closing = False
        self._setup_ui()
        if context is not None and context.stock_code:
            self.set_context(context)

    def minimumSizeHint(self) -> Any:  # noqa: N802 - Qt override
        return QSize(320, 0)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        search_row = QHBoxLayout()
        self.stock_search = QLineEdit()
        self.stock_search.setObjectName("stockResearchSearch")
        self.stock_search.setPlaceholderText("輸入股票代碼，例如 2330")
        self.stock_search.setMaxLength(12)
        self.stock_search.setAccessibleName("搜尋個股代碼")
        self.stock_search.setToolTip("輸入代碼後按 Enter 或按「載入個股報告」。")
        self.stock_search.returnPressed.connect(self._load_from_search)
        search_row.addWidget(self.stock_search, 1)

        self.load_button = QPushButton("載入個股報告")
        self.load_button.setProperty("variant", "primary")
        self.load_button.setAccessibleName("載入個股研究報告")
        self.load_button.clicked.connect(self._load_from_search)
        search_row.addWidget(self.load_button)
        self.reload_button = QPushButton("重新載入")
        self.reload_button.setAccessibleName("重新讀取目前個股報告")
        self.reload_button.clicked.connect(self._reload)
        search_row.addWidget(self.reload_button)
        root.addLayout(search_row)

        navigation_row = QHBoxLayout()
        self.previous_button = QPushButton("上一檔")
        self.previous_button.setAccessibleName("載入上一檔個股")
        self.previous_button.setToolTip("在來源清單代碼中載入上一檔；沒有清單時停用。")
        self.previous_button.clicked.connect(lambda: self._step_stock(-1))
        navigation_row.addWidget(self.previous_button)
        self.next_button = QPushButton("下一檔")
        self.next_button.setAccessibleName("載入下一檔個股")
        self.next_button.setToolTip("在來源清單代碼中載入下一檔；沒有清單時停用。")
        self.next_button.clicked.connect(lambda: self._step_stock(1))
        navigation_row.addWidget(self.next_button)
        self.return_button = QPushButton("返回來源清單")
        self.return_button.setAccessibleName("返回原持倉或觀察清單")
        self.return_button.setToolTip("關閉報告並回到原清單；原篩選與選取由來源頁保留。")
        self.return_button.clicked.connect(self._return_to_source)
        navigation_row.addWidget(self.return_button)
        navigation_row.addStretch()
        root.addLayout(navigation_row)

        self.identity_label = QLabel("尚未選取股票")
        identity_font = QFont()
        identity_font.setBold(True)
        identity_font.setPointSize(14)
        self.identity_label.setFont(identity_font)
        self.identity_label.setAccessibleName("個股識別")
        root.addWidget(self.identity_label)

        status_row = QHBoxLayout()
        self.status_badge = StatusBadge("尚未載入", "info")
        self.status_badge.setObjectName("stockResearchStatusBadge")
        self.status_badge.setAccessibleName("報告讀取狀態")
        status_row.addWidget(self.status_badge)
        self.status_label = QLabel("選取股票後載入既有研究來源。")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_row.addWidget(self.status_label, 1)
        root.addLayout(status_row)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("stockResearchTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)
        self._page_layouts: dict[str, QVBoxLayout] = {}
        self._create_page("summary", "摘要")
        self._create_page("price", "價格／技術")
        self._create_page("fundamental", "基本面／營收財報")
        self._create_page("flows", "籌碼／產業事件")
        self._create_page("position", "持倉／Health／Exit")
        self._create_page("decision", "Rule／ML／歷史")

        self._summary_values: dict[str, QLabel] = {}
        self._build_summary_shell()
        QWidget.setTabOrder(self.stock_search, self.load_button)
        QWidget.setTabOrder(self.load_button, self.reload_button)
        QWidget.setTabOrder(self.reload_button, self.previous_button)
        QWidget.setTabOrder(self.previous_button, self.next_button)
        QWidget.setTabOrder(self.next_button, self.return_button)
        QWidget.setTabOrder(self.return_button, self.tabs)
        self._set_navigation_state()

    def _create_page(self, page_id: str, title: str) -> None:
        inner = QWidget()
        inner.setObjectName(f"stockResearchPage_{page_id}")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        scroll.setAccessibleName(f"{title}內容")
        self.tabs.addTab(scroll, title)
        self._page_layouts[page_id] = layout

    def _build_summary_shell(self) -> None:
        layout = self._page_layouts["summary"]
        self._remove_all_content(layout)
        overview = QGroupBox("個股摘要")
        form = QVBoxLayout(overview)
        form.setSpacing(6)
        for key, label in (
            ("latest_price", "最新可用價格"),
            ("attention", "關注理由"),
            ("risk", "主要風險"),
            ("freshness", "資料更新狀態"),
            ("advice", "現有建議"),
        ):
            value = QLabel("—")
            value.setObjectName(f"stockResearch_{key}")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addWidget(QLabel(label))
            form.addWidget(value)
            self._summary_values[key] = value
        layout.addWidget(overview)
        layout.addWidget(self._label_panel("限制與資料缺口", "目前尚未載入。", "stockResearchLimitations"))
        self.summary_source_group = QGroupBox("來源與各區塊日期")
        source_layout = QVBoxLayout(self.summary_source_group)
        self.sources_table = QTableView()
        apply_financial_table_style(self.sources_table)
        self.sources_table.setAccessibleName("個股研究報告來源表")
        self.sources_table.setMaximumHeight(240)
        source_layout.addWidget(self.sources_table)
        layout.addWidget(self.summary_source_group)
        layout.addStretch()

    def set_stock_codes(self, stock_codes: Sequence[str]) -> None:
        self.stock_codes = tuple(str(code).strip() for code in stock_codes if str(code).strip())
        self._set_navigation_state()

    def set_context(self, context: ResearchStockContextDTO) -> None:
        self.context = context
        self.stock_search.setText(context.stock_code)
        self._load_stock(context.stock_code)

    def _load_from_search(self) -> None:
        self._load_stock(self.stock_search.text())

    def _reload(self) -> None:
        if self._active_code:
            self._load_stock(self._active_code)
        else:
            self._load_from_search()

    def _step_stock(self, step: int) -> None:
        if not self.stock_codes:
            return
        current = self._active_code or self.stock_search.text().strip()
        try:
            index = self.stock_codes.index(current)
        except ValueError:
            index = 0 if step > 0 else len(self.stock_codes) - 1
        next_index = (index + step) % len(self.stock_codes)
        self._load_stock(self.stock_codes[next_index])

    def _load_stock(self, value: object) -> None:
        code = str(value or "").strip()
        if not code:
            self._set_status("請輸入股票代碼。", "warning")
            return
        self._request_id += 1
        request_id = self._request_id
        self._active_code = code
        self.stock_search.setText(code)
        self._cancel_active_worker()
        self._set_loading_state(code)

        context = self.context
        if context is not None and context.stock_code.strip() != code:
            # 來源清單切到另一檔時保留 result/source lineage，但不能把原股票
            # 名稱／身份快取帶到新代碼；service 會再以新代碼的實際資料辨識名稱。
            context = replace(context, stock_code=code, stock_name="")

        def task(cancel_callback=None) -> StockResearchReportDTO:
            return self.service.read_report(
                code,
                context=context,
                cancel_callback=cancel_callback,
            )

        worker = TaskWorker(task)
        self._workers.add(worker)
        self._active_worker = worker
        worker.started.connect(
            lambda rid=request_id, requested_code=code: self._on_report_started(
                rid, requested_code
            )
        )
        worker.finished.connect(
            lambda report, rid=request_id, requested_code=code: self._on_report_loaded(
                rid, requested_code, report
            )
        )
        worker.error.connect(
            lambda error, rid=request_id, requested_code=code: self._on_report_error(
                rid, requested_code, error
            )
        )
        worker.cancelled.connect(
            lambda rid=request_id, requested_code=code: self._on_report_cancelled(
                rid, requested_code
            )
        )
        worker.native_thread_finished.connect(lambda current=worker: self._worker_finished(current))
        worker.start()

    def _cancel_active_worker(self) -> None:
        worker = self._active_worker
        if worker is not None and worker.isRunning():
            worker.cancel(cooperative=True, wait=False)

    def request_close(self) -> bool:
        """取消目前 worker；回傳 True 表示現在可安全關閉。"""

        self._closing = True
        self._request_id += 1
        worker = self._active_worker
        active_workers = [item for item in self._workers if item.isRunning()]
        if worker is not None and worker.isRunning() and worker not in active_workers:
            active_workers.append(worker)
        if active_workers:
            for current in active_workers:
                current.cancel(cooperative=True, wait=False)
            self._set_status("正在安全取消報告讀取…", "warning")
            return False
        return True

    def is_busy(self) -> bool:
        return any(worker.isRunning() for worker in self._workers)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if not self.request_close():
            event.ignore()
            return
        super().closeEvent(event)

    def _worker_finished(self, worker: TaskWorker) -> None:
        self._workers.discard(worker)
        if self._active_worker is worker:
            self._active_worker = None
        worker.deleteLater()
        if self._closing and not self.is_busy():
            self.readyToClose.emit()

    def _on_report_started(self, request_id: int, code: str) -> None:
        """忽略切股後才送達的舊 worker started 訊號。"""

        if request_id != self._request_id or code != self._active_code:
            return
        self._set_status("背景讀取中…", "info")

    def _on_report_loaded(
        self,
        request_id: int,
        code: str,
        report: object,
    ) -> None:
        if request_id != self._request_id or code != self._active_code:
            return
        if not isinstance(report, StockResearchReportDTO):
            self._on_report_error(request_id, code, "service returned an invalid report DTO")
            return
        self._render_report(report)
        self._set_status("報告已載入；內容只讀取既有來源。", "observed")
        self.reportLoaded.emit(report)

    def _on_report_error(self, request_id: int, code: str, error: object) -> None:
        if request_id != self._request_id or code != self._active_code:
            return
        message = str(error).splitlines()[0].strip() or "未知讀取錯誤"
        self._set_status(f"報告讀取失敗：{message}", "error")
        self.reportFailed.emit(message)

    def _on_report_cancelled(self, request_id: int, code: str) -> None:
        if request_id == self._request_id and code == self._active_code and not self._closing:
            self._set_status("報告讀取已取消。", "warning")

    def _set_loading_state(self, code: str) -> None:
        self.identity_label.setText(f"{code}｜報告載入中")
        self._set_status("正在背景讀取有限研究資料…", "info")
        self._summary_values["latest_price"].setText("讀取中…")
        self._summary_values["attention"].setText("讀取中…")
        self._summary_values["risk"].setText("讀取中…")
        self._summary_values["freshness"].setText("讀取中…")
        self._summary_values["advice"].setText("讀取中…")
        self._set_navigation_state()

    def _set_status(self, text: str, quality: str) -> None:
        self.status_label.setText(text)
        self.status_badge.setText(_quality_label(quality))
        self.status_badge.set_quality(_quality_tone(quality))
        self.status_badge.setAccessibleDescription(f"報告狀態：{text}")

    def _set_navigation_state(self) -> None:
        has_codes = bool(self.stock_codes)
        self.previous_button.setEnabled(has_codes)
        self.next_button.setEnabled(has_codes)
        busy = self.is_busy()
        self.load_button.setEnabled(not self._closing)
        self.reload_button.setEnabled(bool(self._active_code) and not self._closing)
        self.return_button.setEnabled(not busy)

    def _render_report(self, report: StockResearchReportDTO) -> None:
        self.identity_label.setText(
            f"{report.stock_code} {report.stock_name or '未提供名稱'}｜{report.market}"
            + (f"｜{report.industry}" if report.industry else "")
        )
        self._summary_values["latest_price"].setText(_latest_price_text(report.price_points))
        self._summary_values["attention"].setText(_join_or_missing(report.attention_reasons, "目前沒有額外關注理由。"))
        self._summary_values["risk"].setText(_join_or_missing(report.key_risks, "目前沒有可呈現的風險 row；不代表沒有風險。"))
        self._summary_values["freshness"].setText(_freshness_text(report))
        self._summary_values["advice"].setText(_advice_summary(report.advice))
        limitations = _join_or_missing(report.limitations, "目前沒有額外限制。")
        self._find_widget("stockResearchLimitations").setText(limitations)

        self._render_sources(report)
        self._render_price(report)
        self._render_fundamental(report)
        self._render_flows(report)
        self._render_position(report.position)
        self._render_decision(report)
        self._set_navigation_state()

    def _render_sources(self, report: StockResearchReportDTO) -> None:
        rows = []
        for source in report.sources:
            rows.append(
                (
                    source.source_label,
                    _quality_label(source.status),
                    _quality_label(source.quality),
                    source.data_as_of or "—",
                    source.available_at or "—",
                    _quality_label(source.freshness),
                    source.version or "—",
                    str(source.row_count),
                    source.frequency or "—",
                    source.expected_period or "—",
                    source.freshness_reason or "—",
                )
            )
        if not rows:
            rows = [("—", "缺資料", "—", "—", "—", "未知", "—", "0", "—", "—", "—")]
        self.sources_table.setModel(
            StockReportTableModel(
                (
                    "來源",
                    "來源狀態",
                    "品質",
                    "資料日",
                    "資料可得時間",
                    "更新狀態",
                    "版本",
                    "筆數",
                    "更新週期",
                    "預期資料期",
                    "更新說明",
                ),
                rows,
                self.sources_table,
            )
        )
        self.sources_table.resizeColumnsToContents()

    def _render_price(self, report: StockResearchReportDTO) -> None:
        layout = self._reset_page("price")
        layout.addWidget(self._section_heading("價格與成交量", report, "price"))
        chart = StockPriceChartWidget()
        chart.set_points(report.price_points)
        layout.addWidget(chart)
        if report.price_points:
            rows = tuple(
                (
                    point.data_date,
                    _decimal_text(point.close_price),
                    _decimal_text(point.change),
                    _integer_text(point.volume),
                    _decimal_text(point.turnover),
                )
                for point in reversed(report.price_points)
            )
            self._add_table(layout, ("日期", "收盤價", "漲跌價差", "成交股數", "成交金額"), rows, 310)
        else:
            layout.addWidget(self._missing_panel("價格資料不足；請從「數據更新」檢查 daily_prices。"))
        if report.technical is not None:
            group = QGroupBox(f"技術指標｜資料日 {report.technical.data_date or '—'}")
            group_layout = QVBoxLayout(group)
            rows = tuple(
                (metric.label, _metric_text(metric), metric.data_as_of or "—", metric.quality)
                for metric in report.technical.indicators
            )
            self._add_table(group_layout, ("指標", "值", "資料日", "品質"), rows, 240)
            if report.technical.limitations:
                group_layout.addWidget(self._wrapped_label(_join_or_missing(report.technical.limitations, "")))
            layout.addWidget(group)
        else:
            layout.addWidget(self._missing_panel("技術指標不足；不以缺欄位推論趨勢。"))
        layout.addStretch()

    def _render_fundamental(self, report: StockResearchReportDTO) -> None:
        layout = self._reset_page("fundamental")
        layout.addWidget(self._section_heading("基本面／營收財報", report, "fundamental"))
        if not report.fundamentals:
            layout.addWidget(self._missing_panel("沒有可用的公告／可得日基本面 row；不補零。"))
            layout.addStretch()
            return
        rows = tuple(
            (
                item.kind,
                item.label,
                item.period or "—",
                item.as_of_date or "—",
                item.announced_date or "—",
                item.available_at or "—",
                _metric_text(item),
                item.quality,
                item.source_version or "—",
            )
            for item in report.fundamentals
        )
        self._add_table(
            layout,
            ("類型", "項目", "期間", "資料日", "公告日", "資料可得時間", "值", "品質", "版本"),
            rows,
            420,
        )
        layout.addWidget(
            self._wrapped_label(
                "基本面只採用 available_date 不晚於報告 as_of 的 row；各項資料日期可能不同。"
            )
        )
        layout.addStretch()

    def _render_flows(self, report: StockResearchReportDTO) -> None:
        layout = self._reset_page("flows")
        layout.addWidget(self._section_heading("分點與法人／信用／集保", report, "flows"))
        if report.flows:
            rows = tuple(
                (
                    flow.data_date,
                    flow.branch_name,
                    _integer_text(flow.buy_shares),
                    _integer_text(flow.sell_shares),
                    _integer_text(flow.net_shares),
                    _decimal_text(flow.net_amount_thousand),
                    flow.trade_type or "—",
                    flow.quality,
                )
                for flow in report.flows
            )
            self._add_table(
                layout,
                ("日期", "分點", "買進股數", "賣出股數", "買賣超股數", "淨額千元", "類型", "品質"),
                rows,
                350,
            )
        else:
            layout.addWidget(self._missing_panel("沒有可用分點 row；請檢查 broker_flows 更新狀態。"))
        ownership = QGroupBox("法人／信用／集保（有資料才顯示）")
        ownership_layout = QVBoxLayout(ownership)
        ownership_rows = tuple(
            (metric.label, _metric_text(metric), metric.data_as_of or "—", metric.available_at or "—", metric.quality)
            for metric in (*report.institutional, *report.credit, *report.shareholding)
        )
        if ownership_rows:
            self._add_table(ownership_layout, ("項目", "值", "資料日", "資料可得時間", "品質"), ownership_rows, 240)
        else:
            ownership_layout.addWidget(self._missing_panel("目前沒有法人、信用或集保資料；不補零。"))
        layout.addWidget(ownership)
        events = QGroupBox("產業／事件／歷史 Evidence")
        event_layout = QVBoxLayout(events)
        self._add_event_table(event_layout, report.events)
        layout.addWidget(events)
        layout.addStretch()

    def _render_position(self, position: StockPositionSnapshotDTO | None) -> None:
        layout = self._reset_page("position")
        layout.addWidget(QLabel("此區只顯示既有 PortfolioService、Health／Exit read contract 的內容。"))
        if position is None:
            layout.addWidget(self._missing_panel("沒有此股票的持倉 row；Health／Exit 不對非持倉股票推導動作。"))
            layout.addStretch()
            return
        group = QGroupBox("持倉成本／損益／曝險")
        group_layout = QVBoxLayout(group)
        rows = (
            ("持倉狀態", "持有中" if position.is_holding else "非持倉"),
            ("持有股數", _decimal_text(position.quantity)),
            ("平均成本", _decimal_text(position.average_cost)),
            ("投入金額", _decimal_text(position.invested_amount)),
            ("最新持倉價格", _decimal_text(position.current_price)),
            ("未實現損益", _decimal_text(position.unrealized_pnl)),
            ("未實現損益%", _percent_text(position.unrealized_pnl_pct)),
            ("曝險", _bp_text(position.exposure_bp)),
            ("來源", position.source_type or position.source_id or "—"),
            ("最後交易日", position.last_trade_date or "—"),
        )
        self._add_table(group_layout, ("欄位", "值"), rows, 300)
        layout.addWidget(group)
        health = QGroupBox(f"Health｜{position.health_label or position.health_status or '資料不足'}")
        health_layout = QVBoxLayout(health)
        health_layout.addWidget(self._wrapped_label(_join_or_missing(position.health_reasons, "沒有 Health 理由。")))
        if position.health_source_trace:
            health_layout.addWidget(self._wrapped_label("Health source trace：" + "；".join(position.health_source_trace)))
        layout.addWidget(health)
        exit_group = QGroupBox(f"Exit｜{position.exit_status or 'unavailable'}")
        exit_layout = QVBoxLayout(exit_group)
        exit_layout.addWidget(self._wrapped_label(_join_or_missing(position.exit_reasons, "目前沒有可用的持倉 Exit 分析；不推導賣出動作。")))
        layout.addWidget(exit_group)
        if position.limitations:
            layout.addWidget(self._missing_panel(_join_or_missing(position.limitations, "")))
        layout.addStretch()

    def _render_decision(self, report: StockResearchReportDTO) -> None:
        layout = self._reset_page("decision")
        advice_group = QGroupBox("Advice（沿用既有 AdviceComposer）")
        advice_layout = QVBoxLayout(advice_group)
        self._render_advice_content(advice_layout, report.advice, report.position)
        layout.addWidget(advice_group)

        rule_group = QGroupBox("Rule 證據")
        rule_layout = QVBoxLayout(rule_group)
        rule_layout.addWidget(self._wrapped_label(_join_or_missing(report.rule_reasons, "目前沒有可追溯 Rule reason。")))
        layout.addWidget(rule_group)

        ml_group = QGroupBox("ML（有合格結果才顯示）")
        ml_layout = QVBoxLayout(ml_group)
        ml = report.ml
        if ml.status not in {"unavailable", "missing"} and ml.model_version and ml.dataset_version:
            ml_layout.addWidget(self._wrapped_label(
                f"狀態：{ml.status}\n模型版本：{ml.model_version}\nDataset：{ml.dataset_version}\n"
                f"推論時間：{ml.inference_at or '—'}\nLane：{ml.research_or_formal or '—'}"
            ))
            ml_layout.addWidget(self._wrapped_label("可解釋輸出：" + _join_or_missing(ml.explanations, "未提供")))
        else:
            ml_layout.addWidget(self._missing_panel(_join_or_missing(ml.limitations, "目前沒有可用的個股 ML 分析。")))
        if ml.limitations:
            ml_layout.addWidget(self._wrapped_label("ML 限制：" + "；".join(ml.limitations)))
        layout.addWidget(ml_group)

        history_group = QGroupBox("歷史建議與後續結果")
        history_layout = QVBoxLayout(history_group)
        self._add_event_table(history_layout, report.events)
        layout.addWidget(history_group)
        layout.addWidget(self._wrapped_label("研究報告不觸發自動下單；持倉修改仍沿既有確認與記錄流程。"))
        layout.addStretch()

    def _render_advice_content(
        self,
        layout: QVBoxLayout,
        advice: StockAdviceSnapshotDTO,
        position: StockPositionSnapshotDTO | None = None,
    ) -> None:
        if advice.recommendation is None:
            if advice.saved_analysis is not None:
                saved = advice.saved_analysis
                layout.addWidget(self._wrapped_label(
                    f"保存分析狀態：{saved.status}\n{saved.message or '沒有可顯示的保存分析。'}"
                ))
            layout.addWidget(self._missing_panel(_join_or_missing(advice.limitations, "目前沒有適用 Advice。")))
            return
        rec = advice.recommendation
        action = _advice_action_label(rec.advice_action.value)
        text = (
            f"適用狀態：{action}\n"
            f"分類：{rec.classification.value}\n"
            f"資料品質：{rec.data_quality or '—'}\n"
            f"決策日：{rec.decision_date or '—'}｜資料日：{rec.data_as_of_date or '—'}\n"
            f"適用期間：{rec.holding_horizon or '未提供'}"
        )
        layout.addWidget(self._wrapped_label(text))
        for title, values in (
            ("觸發條件／進場論點", (rec.entry_thesis,) if rec.entry_thesis else ()),
            ("支持理由", rec.why_reasons),
            ("反對證據／政策限制", rec.why_not_reasons),
            ("失效條件", rec.invalidation_conditions),
            ("主要風險", rec.risk_reasons),
            ("警告／拒絕理由", (*rec.warnings, *rec.refusal_reasons)),
        ):
            if values:
                layout.addWidget(self._wrapped_label(f"{title}：" + "；".join(values)))
        if rec.source_trace:
            layout.addWidget(self._wrapped_label("來源追溯：" + "；".join(rec.source_trace)))
        if advice.rule_reasons:
            layout.addWidget(self._wrapped_label("Rule reasons：" + "；".join(advice.rule_reasons)))
        if advice.ml_reasons:
            layout.addWidget(self._wrapped_label("ML reasons（分開呈現）：" + "；".join(advice.ml_reasons)))
        layout.addWidget(self._wrapped_label(
            f"Rule／ML 關係：{advice.agreement}\n"
            "此 Advice 不代表機率、目標價、勝率或自動交易指令。"
        ))
        if advice.portfolio is not None:
            portfolio = advice.portfolio
            layout.addWidget(self._wrapped_label(
                "持倉風控限制：已有既有 Portfolio Advice snapshot；"
                f"目前權重 {_bp_text(portfolio.current_weight_bp)}、"
                f"可執行權重 {_bp_text(portfolio.executable_weight_bp)}，詳見持倉分頁。"
            ))
        elif position is None or not position.is_holding:
            layout.addWidget(self._wrapped_label(
                "持倉風控限制：目前沒有持有中的持倉 row，未套用持倉限制。"
            ))
        else:
            layout.addWidget(self._wrapped_label(
                "持倉風控限制：已有持倉，但本次沒有既有 Portfolio Advice snapshot；"
                "請依持倉／Health／Exit 既有 read contract 判讀，不由報告 UI 推導。"
            ))

    def _section_heading(
        self,
        title: str,
        report: StockResearchReportDTO,
        section_id: str,
    ) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {MIDNIGHT_ANALYST.surface_2}; border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-left: 4px solid {MIDNIGHT_ANALYST.accent}; border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 7, 10, 7)
        label = QLabel(title)
        label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; font-weight: 700;")
        layout.addWidget(label)
        section = next((item for item in report.sections if item.section_id == section_id), None)
        status = section.status if section is not None else "missing"
        badge = StatusBadge(_quality_label(status), _quality_tone(status))
        badge.setAccessibleDescription(
            f"{title}狀態：{_quality_label(status)}；資料日：{section.data_as_of if section else '—'}；"
            f"資料可得時間：{section.available_at if section else '—'}"
        )
        layout.addStretch()
        layout.addWidget(badge)
        date_label = QLabel(
            f"資料日 {section.data_as_of if section and section.data_as_of else '—'}｜"
            f"資料可得時間 {section.available_at if section and section.available_at else '—'}"
        )
        date_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
        layout.addWidget(date_label)
        return frame

    def _reset_page(self, page_id: str) -> QVBoxLayout:
        layout = self._page_layouts[page_id]
        self._remove_all_content(layout)
        return layout

    @staticmethod
    def _remove_all_content(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                StockResearchReportView._remove_all_content(child)

    def _add_table(
        self,
        layout: QVBoxLayout,
        columns: Sequence[str],
        rows: Sequence[Sequence[str]],
        maximum_height: int,
    ) -> QTableView:
        table = QTableView()
        apply_financial_table_style(table)
        table.setModel(StockReportTableModel(columns, rows, table))
        table.setMaximumHeight(maximum_height)
        table.setSelectionBehavior(QTableView.SelectRows)
        table.setSelectionMode(QTableView.SingleSelection)
        table.setAccessibleDescription("可使用鍵盤方向鍵選取；完整欄位文字可由 tooltip 讀取。")
        table.resizeColumnsToContents()
        layout.addWidget(table)
        return table

    def _add_event_table(
        self,
        layout: QVBoxLayout,
        events: Sequence[StockEvidenceEventDTO],
    ) -> None:
        if not events:
            layout.addWidget(self._missing_panel("目前沒有可追溯的 Evidence event 或後續 outcome。"))
            return
        rows = []
        for event in events:
            outcomes = tuple(
                f"{outcome.window_days}日：{outcome.outcome_status or '—'}"
                + (f"，報酬bp {outcome.forward_return_bp}" if outcome.forward_return_bp is not None else "")
                for outcome in event.outcomes
            )
            rows.append(
                (
                    event.decision_date or event.event_date or "—",
                    event.event_type or "—",
                    event.source_type or "—",
                    event.data_quality or "—",
                    "；".join(event.reasons) or "—",
                    "；".join(event.why_not_reasons) or "—",
                    "；".join(outcomes) or "尚無後續結果",
                )
            )
        self._add_table(
            layout,
            ("日期", "事件", "來源", "品質", "Rule理由", "反對／風險", "後續結果"),
            rows,
            360,
        )

    def _label_panel(self, title: str, text: str, object_name: str) -> QWidget:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        label = self._wrapped_label(text)
        label.setObjectName(object_name)
        group_layout.addWidget(label)
        return group

    def _missing_panel(self, text: str) -> QWidget:
        label = self._wrapped_label(f"資料不足：{text}")
        label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.warning}; background: {MIDNIGHT_ANALYST.surface_2}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; padding: 8px;"
        )
        label.setAccessibleDescription("資料不足；此狀態不等於看多或看空。" + text)
        return label

    @staticmethod
    def _wrapped_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        return label

    def _find_widget(self, object_name: str) -> QLabel:
        widget = self.findChild(QLabel, object_name)
        if widget is None:
            raise RuntimeError(f"missing report widget: {object_name}")
        return widget

    def _return_to_source(self) -> None:
        self.returnRequested.emit()
        parent = self.parentWidget()
        if isinstance(parent, QDialog):
            parent.close()


class StockResearchReportDialog(QDialog):
    """非模態單股報告視窗；關閉前會合作式取消背景讀取。"""

    def __init__(
        self,
        service: StockResearchReportReadService,
        context: ResearchStockContextDTO,
        *,
        stock_codes: Sequence[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setWindowTitle(f"個股研究報告｜{context.stock_code}")
        self.setMinimumSize(360, 280)
        self.resize(1120, 760)
        layout = QVBoxLayout(self)
        self.report_view = StockResearchReportView(
            service,
            context,
            stock_codes=stock_codes,
            parent=self,
        )
        self.report_view.readyToClose.connect(self.accept)
        self.report_view.returnRequested.connect(self.accept)
        layout.addWidget(self.report_view)

    def set_context(
        self,
        context: ResearchStockContextDTO,
        *,
        stock_codes: Sequence[str] | None = None,
    ) -> None:
        self.setWindowTitle(f"個股研究報告｜{context.stock_code}")
        if stock_codes is not None:
            self.report_view.set_stock_codes(stock_codes)
        self.report_view.set_context(context)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if not self.report_view.request_close():
            event.ignore()
            return
        super().closeEvent(event)


def _quality_label(value: str) -> str:
    labels = {
        "available": "可用",
        "observed": "已觀測",
        "partial": "部分可用",
        "stale": "過期",
        "fresh": "新鮮",
        "missing": "缺資料",
        "error": "讀取失敗",
        "degraded": "降級",
        "estimated": "估計",
        "unavailable": "不可用",
        "unknown": "未知",
        "info": "讀取中",
        "warning": "注意",
    }
    return labels.get(str(value).lower(), str(value) or "未知")


def _quality_tone(value: str) -> str:
    token = str(value).lower()
    if token in {"available", "observed", "fresh"}:
        return "observed"
    if token in {"partial", "stale", "degraded", "estimated", "warning"}:
        return "warning"
    if token in {"missing", "error", "unavailable"}:
        return "missing"
    return "info"


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


def _integer_text(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def _percent_text(value: Decimal | None) -> str:
    return "—" if value is None else f"{value * Decimal('100'):+.2f}%"


def _bp_text(value: int | None) -> str:
    return "—" if value is None else f"{value:,} bp"


def _metric_text(metric: StockMetricDTO | StockFundamentalObservationDTO) -> str:
    if metric.value is not None:
        return _decimal_text(metric.value) + (f" {metric.unit}" if metric.unit else "")
    return metric.value_text or "—"


def _latest_price_text(points: Sequence[StockPricePointDTO]) -> str:
    if not points:
        return "資料不足：沒有不晚於查詢日的價格。"
    point = points[-1]
    return (
        f"{_decimal_text(point.close_price)} TWD｜資料日 {point.data_date}｜"
        f"成交股數 {_integer_text(point.volume)}｜成交金額 {_decimal_text(point.turnover)}"
    )


def _join_or_missing(values: Sequence[str], fallback: str) -> str:
    cleaned = tuple(str(value).strip() for value in values if str(value).strip())
    return "；".join(cleaned) if cleaned else fallback


def _freshness_text(report: StockResearchReportDTO) -> str:
    parts = [f"查詢日期：{report.as_of or '—'}"]
    for section in report.sections:
        parts.append(f"{section.label}：{_quality_label(section.freshness)}（{section.data_as_of or '—'}）")
    return "；".join(parts)


def _advice_summary(advice: StockAdviceSnapshotDTO) -> str:
    if advice.recommendation is None:
        return _join_or_missing(advice.limitations, "目前沒有適用 Advice；資料不足不等於看空。")
    rec = advice.recommendation
    return (
        f"{_advice_action_label(rec.advice_action.value)}｜"
        f"資料品質 {rec.data_quality or '—'}｜"
        f"依據 {_join_or_missing(rec.why_reasons, '未提供')}"
    )


def _advice_action_label(value: str) -> str:
    return {
        "RESEARCH": "觀察／資料不足",
        "ADD_CANDIDATE": "買進候選",
        "HOLD": "續抱",
        "REDUCE_CANDIDATE": "減碼候選",
        "EXIT_CANDIDATE": "賣出候選",
        "AVOID": "避免／觀察",
        "NO_NEW_POSITION": "暫不新增",
    }.get(value, value or "資料不足")
