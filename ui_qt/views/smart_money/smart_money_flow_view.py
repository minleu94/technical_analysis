"""
Smart Money Flow - Terminal Style Scanner 主視圖
整合 Summary Strip 與使用 Custom Delegate 的 Scanner Table。
已優化：採用左右分欄、增加股票資訊摘要面板、整合雙向资金長條圖分點明細表、美化控制列與表格樣式。
"""

import pandas as pd
import traceback
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableView, QMessageBox,
    QTabWidget, QSplitter, QComboBox, QHeaderView, QFrame
)
from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtGui import QColor

from ui_qt.widgets.info_button import InfoButton
from app_module.broker_flow_service import BrokerFlowService
from app_module.watchlist_service import WatchlistService
from ui_qt.views.smart_money.summary_strip import SummaryStrip
from ui_qt.views.smart_money.terminal_table_model import (
    ROLE_BADGES,
    TerminalTableModel,
    BranchTrackerTableModel,
)
from ui_qt.views.smart_money.terminal_delegate import TerminalScannerDelegate
from ui_qt.views.smart_money.detail_table_delegate import DetailTableDelegate
from ui_qt.models.pandas_table_model import PandasTableModel # 給 Detail Table 用

class SmartMoneyFlowView(QWidget):
    """Terminal Style Smart Money Scanner 主視圖"""

    def __init__(
        self,
        broker_flow_service: BrokerFlowService,
        watchlist_service: WatchlistService = None,
        smart_money_semantic_service=None,
        parent=None,
    ):
        super().__init__(parent)
        self.flow_service = broker_flow_service
        self.watchlist_service = watchlist_service
        self.smart_money_semantic_service = smart_money_semantic_service
        self._data_loaded = False
        self._all_scanner_signals = []

        # 色彩設定 (更為精緻的深藍黑背景)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("#0b0f19"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # 設置全域控制元件樣式
        self.setStyleSheet("""
            QComboBox {
                background-color: #1e293b;
                color: #f1f5f9;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 10px;
                min-width: 90px;
                font-family: 'Segoe UI', Arial;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e293b;
                color: #f1f5f9;
                selection-background-color: #3b82f6;
                border: 1px solid #334155;
            }
            QLabel {
                font-family: 'Segoe UI', Arial;
            }
        """)

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # --- Top: Summary Strip ---
        self.summary_strip = SummaryStrip(self)
        main_layout.addWidget(self.summary_strip)

        # --- Controls Bar ---
        control_widget = QWidget()
        control_widget.setStyleSheet("background-color: #0f172a; border-bottom: 1px solid #1e293b;")
        control_layout = QHBoxLayout(control_widget)
        control_layout.setContentsMargins(20, 12, 20, 12)

        title_lbl = QLabel("主力流向掃描器 (SMART MONEY FLOW)")
        title_lbl.setStyleSheet("color: #f1f5f9; font-weight: bold; font-size: 14px; letter-spacing: 0.5px;")
        control_layout.addWidget(title_lbl)

        info_btn = InfoButton("smart_money_flow", self)
        control_layout.addWidget(info_btn)

        control_layout.addStretch()

        # 週期選擇
        control_layout.addWidget(QLabel("掃描週期:", styleSheet="color: #94a3b8; font-weight: bold; margin-right: 4px;"))
        self.period_combo = QComboBox()
        self.period_combo.addItems(["日線 (DAY)", "週線 (WEEK)", "月線 (MONTH)"])
        self.period_combo.setCurrentIndex(1)
        self.period_combo.currentIndexChanged.connect(self._on_period_changed)
        control_layout.addWidget(self.period_combo)

        # 顯示範圍
        control_layout.addWidget(QLabel(" 顯示範圍:", styleSheet="color: #94a3b8; font-weight: bold; margin-right: 4px;"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Top / Bottom 50", "top_bottom_50")
        self.scope_combo.addItem("Top 50 買超", "top50")
        self.scope_combo.addItem("Bottom 50 賣超", "bottom50")
        self.scope_combo.addItem("全部", "all")
        self.scope_combo.setToolTip("主表預設顯示買超前 50 與賣超前 50；Summary Strip 仍以全市場訊號為統計母體。")
        self.scope_combo.currentIndexChanged.connect(lambda _idx=False: self._on_scope_changed())
        control_layout.addWidget(self.scope_combo)

        # Sparkline 圖表類型
        control_layout.addWidget(QLabel(" 趨勢圖樣:", styleSheet="color: #94a3b8; font-weight: bold; margin-right: 4px;"))
        self.chart_combo = QComboBox()
        self.chart_combo.addItems(["直方 (BAR)", "折線 (LINE)", "面積 (AREA)"])
        self.chart_combo.setCurrentIndex(0)
        self.chart_combo.currentIndexChanged.connect(self._on_chart_changed)
        control_layout.addWidget(self.chart_combo)

        # 按鈕美化
        self.refresh_btn = QPushButton("開始掃描")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
            }
            QPushButton:hover {
                background-color: #3b82f6;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
        """)
        self.refresh_btn.clicked.connect(self._refresh_data)
        control_layout.addWidget(self.refresh_btn)

        if self.watchlist_service:
            self.add_watchlist_btn = QPushButton("+ 觀察清單")
            self.add_watchlist_btn.setStyleSheet("""
                QPushButton {
                    background-color: #059669;
                    color: white;
                    font-weight: bold;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 18px;
                }
                QPushButton:hover {
                    background-color: #10b981;
                }
                QPushButton:pressed {
                    background-color: #047857;
                }
            """)
            self.add_watchlist_btn.clicked.connect(self._add_to_watchlist)
            control_layout.addWidget(self.add_watchlist_btn)

        main_layout.addWidget(control_widget)

        # --- Body: Tabs ---
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #1e293b; background-color: #0b0f19; }
            QTabBar::tab { background: #0f172a; color: #94a3b8; padding: 10px 24px; font-weight: bold; border-right: 1px solid #1e293b; }
            QTabBar::tab:selected { background: #0b0f19; color: #3b82f6; border-bottom: 2px solid #3b82f6; }
        """)
        main_layout.addWidget(self.tab_widget)

        # === Tab 1: Stock Overview ===
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setContentsMargins(10, 10, 10, 10)

        # 改為左右分欄 (Qt.Horizontal)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #1e293b; width: 4px; }")

        # Master: Terminal Scanner Table
        self.scanner_table = QTableView()
        self.scanner_table.setSelectionBehavior(QTableView.SelectRows)
        self.scanner_table.setSortingEnabled(True)
        self.scanner_table.setMinimumWidth(900)
        self.scanner_table.horizontalHeader().setStretchLastSection(False)
        self.scanner_table.verticalHeader().setVisible(False)
        self.scanner_table.setShowGrid(False)
        self.scanner_table.setStyleSheet("""
            QTableView {
                background-color: #0b0f19;
                color: #e2e8f0;
                gridline-color: #1e293b;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
            QHeaderView::section {
                background-color: #111827;
                color: #94a3b8;
                border: none;
                border-bottom: 2px solid #3b82f6;
                font-family: 'Segoe UI', Arial;
                font-weight: bold;
                padding: 8px;
            }
            QTableView::item:selected {
                background-color: transparent;
            }
        """)

        # 套用自定義委派
        self.delegate = TerminalScannerDelegate(self.scanner_table)
        self.scanner_table.setItemDelegate(self.delegate)
        # 增加 Row Height 以容納 Badges 與 Sparklines
        self.scanner_table.verticalHeader().setDefaultSectionSize(48)

        self.splitter.addWidget(self.scanner_table)

        # Detail: Drill-down Card Panel (高質感卡片化與左右排版)
        detail_widget = QFrame()
        detail_widget.setObjectName("DetailCardFrame")
        detail_widget.setMinimumWidth(240)
        detail_widget.setStyleSheet("""
            QFrame#DetailCardFrame {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
        """)
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(15, 15, 15, 15)
        detail_layout.setSpacing(12)

        # 1. 股票摘要與雷達訊號原因卡片
        self.detail_sub_card = QFrame()
        self.detail_sub_card.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        sub_card_layout = QVBoxLayout(self.detail_sub_card)
        sub_card_layout.setContentsMargins(14, 12, 14, 12)
        sub_card_layout.setSpacing(6)

        self.sub_card_title = QLabel("未選取股票")
        self.sub_card_title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")

        self.sub_card_stats = QLabel("請從左側表格點選股票以查看主力分點進出明細與原因")
        self.sub_card_stats.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.5;")
        self.sub_card_stats.setWordWrap(True)

        sub_card_layout.addWidget(self.sub_card_title)
        sub_card_layout.addWidget(self.sub_card_stats)
        detail_layout.addWidget(self.detail_sub_card)

        # 2. 分點明細表標題
        self.detail_label = QLabel("分點買賣明細 (BRANCH DRILL-DOWN)")
        self.detail_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        detail_layout.addWidget(self.detail_label)

        # 3. 分點明細表格 (套用雙向水平長條圖 Delegate)
        self.detail_table = QTableView()
        self.detail_table.setSelectionBehavior(QTableView.SelectRows)
        self.detail_table.setSortingEnabled(True)
        self.detail_table.setShowGrid(False)
        self.detail_table.horizontalHeader().setStretchLastSection(False)
        self.detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.verticalHeader().setDefaultSectionSize(38)
        self.detail_table.setStyleSheet("""
            QTableView {
                background-color: #0b0f19;
                color: #e2e8f0;
                border: 1px solid #1e293b;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #111827;
                color: #94a3b8;
                border: none;
                border-bottom: 2px solid #10b981;
                font-family: 'Segoe UI', Arial;
                font-weight: bold;
                padding: 6px;
            }
            QTableView::item:selected {
                background-color: transparent;
            }
        """)

        self.detail_delegate = DetailTableDelegate(self.detail_table)
        self.detail_table.setItemDelegate(self.detail_delegate)
        self.detail_table.doubleClicked.connect(self._drill_down_branch_from_detail)

        detail_layout.addWidget(self.detail_table)
        self.splitter.addWidget(detail_widget)

        # 設定比例：主表依內容貼合寬度，右側明細保留較大的預設閱讀空間。
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([980, 360])
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 1)
        tab1_layout.addWidget(self.splitter)
        self.tab_widget.addTab(tab1, "個股資金流向 (STOCK OVERVIEW)")

        # === Tab 2: Branch Tracker ===
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setContentsMargins(10, 10, 10, 10)

        b_control_widget = QWidget()
        b_control_widget.setStyleSheet("background-color: #0f172a; border-radius: 8px; margin-bottom: 8px;")
        b_control_layout = QHBoxLayout(b_control_widget)
        b_control_layout.setContentsMargins(15, 10, 15, 10)
        b_control_layout.addWidget(QLabel("追蹤券商分點:", styleSheet="color: #94a3b8; font-weight: bold;"))

        self.branch_combo = QComboBox()
        self.branch_combo.setMinimumWidth(280)
        self.branch_combo.currentIndexChanged.connect(self._on_branch_changed)
        b_control_layout.addWidget(self.branch_combo)
        b_control_layout.addStretch()
        tab2_layout.addWidget(b_control_widget)

        self.branch_table = QTableView()
        self.branch_table.setSelectionBehavior(QTableView.SelectRows)
        self.branch_table.setSortingEnabled(True)
        self.branch_table.horizontalHeader().setStretchLastSection(False)
        self.branch_table.verticalHeader().setVisible(False)
        self.branch_table.setShowGrid(False)
        self.branch_table.setStyleSheet(self.scanner_table.styleSheet())
        self.branch_table.verticalHeader().setDefaultSectionSize(48)

        self.branch_delegate = TerminalScannerDelegate(self.branch_table)
        self.branch_table.setItemDelegate(self.branch_delegate)
        tab2_layout.addWidget(self.branch_table)

        self.tab_widget.addTab(tab2, "分點進出追蹤 (BRANCH TRACKER)")

        self._on_chart_changed()

    def _get_current_period_val(self) -> str:
        idx = self.period_combo.currentIndex()
        if idx == 0: return 'day'
        if idx == 2: return 'month'
        return 'week'

    def _on_period_changed(self):
        self._refresh_data()

    def _on_chart_changed(self):
        chart_text = self.chart_combo.currentText()
        if "BAR" in chart_text:
            chart_type = 'bar'
        elif "LINE" in chart_text:
            chart_type = 'line'
        else:
            chart_type = 'area'

        self.delegate.chart_type = chart_type
        self.branch_delegate.chart_type = chart_type
        self.scanner_table.viewport().update()
        self.branch_table.viewport().update()

    def _on_scope_changed(self):
        if self._data_loaded or self._all_scanner_signals:
            self._apply_scanner_signals(self._all_scanner_signals)

    def _filter_scanner_signals(self, signals):
        mode = self.scope_combo.currentData() if hasattr(self, "scope_combo") else "top_bottom_50"
        signals = list(signals or [])
        if mode == "all":
            return signals

        positive = [s for s in signals if s.aggregation.total_net_qty > 0]
        negative = [s for s in signals if s.aggregation.total_net_qty < 0]

        top = sorted(positive, key=lambda s: s.smart_money_score, reverse=True)[:50]
        bottom = sorted(negative, key=lambda s: s.aggregation.total_net_qty)[:50]

        if mode == "top50":
            return top
        if mode == "bottom50":
            return bottom

        filtered = []
        seen_codes = set()
        for signal in [*top, *bottom]:
            if signal.stock_code in seen_codes:
                continue
            filtered.append(signal)
            seen_codes.add(signal.stock_code)
        return filtered

    def _apply_scanner_signals(self, signals):
        filtered_signals = self._filter_scanner_signals(signals)
        semantics_by_code = {}
        if self.smart_money_semantic_service is not None:
            decision_date = date.today()
            for signal in filtered_signals:
                try:
                    semantics_by_code[signal.stock_code] = self.smart_money_semantic_service.build_stock_semantics(
                        signal.stock_code,
                        decision_date,
                    )
                except Exception:
                    continue
        self.scanner_model = TerminalTableModel(filtered_signals, semantics_by_code=semantics_by_code)
        self.scanner_table.setModel(self.scanner_model)

        scanner_header = self.scanner_table.horizontalHeader()
        scanner_header.setStretchLastSection(False)
        scanner_header.setSectionResizeMode(QHeaderView.Interactive)
        scanner_widths = {
            0: 64,   # 分數
            1: 180,  # 股票
            2: 82,   # 淨量
            3: 68,   # 集中度
            4: 78,   # 語意狀態
            6: 150,  # Badges
            7: 190,  # Trend
        }
        for col, width in scanner_widths.items():
            scanner_header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.scanner_table.setColumnWidth(col, width)
        scanner_header.setSectionResizeMode(5, QHeaderView.Interactive)
        self._fit_scanner_diagnostic_column()

        sel_model = self.scanner_table.selectionModel()
        if sel_model:
            sel_model.selectionChanged.connect(self._on_scanner_selection_changed)

        self.sub_card_title.setText("未選取股票")
        self.sub_card_stats.setText("請從左側表格點選股票以查看主力分點進出明細與原因")
        self.detail_table.setModel(PandasTableModel(pd.DataFrame(columns=['分點名稱', '買進張數', '賣出張數', '淨買賣超'])))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "scanner_table") and self.scanner_table.model() is not None:
            self._fit_scanner_diagnostic_column()
        if hasattr(self, "detail_table") and self.detail_table.model() is not None:
            self._fit_detail_table_columns()

    def _fit_scanner_diagnostic_column(self):
        model = self.scanner_table.model()
        if model is None:
            return

        concentration_col = 3
        semantic_col = 4
        diagnostic_col = 5
        badges_col = 6
        trend_col = 7

        font_metrics = self.scanner_table.fontMetrics()

        concentration_width = self._fit_text_column_width(model, concentration_col, minimum=54, maximum=70, padding=18)
        semantic_width = self._fit_text_column_width(model, semantic_col, minimum=66, maximum=86, padding=18)
        badges_width = self._fit_badges_column_width(model, badges_col, font_metrics)
        trend_width = 190
        self.scanner_table.setColumnWidth(concentration_col, concentration_width)
        self.scanner_table.setColumnWidth(semantic_col, semantic_width)
        self.scanner_table.setColumnWidth(badges_col, badges_width)
        self.scanner_table.setColumnWidth(trend_col, trend_width)

        diagnostic_content_width = self._fit_text_column_width(
            model,
            diagnostic_col,
            minimum=250,
            maximum=420,
            padding=34,
        )

        left_and_middle_width = sum(
            self.scanner_table.columnWidth(col)
            for col in range(model.columnCount())
            if col != diagnostic_col
        )
        viewport_width = max(0, self.scanner_table.viewport().width() - 18)
        diagnostic_available_width = max(220, viewport_width - left_and_middle_width)
        diagnostic_width = min(diagnostic_content_width, diagnostic_available_width)
        self.scanner_table.setColumnWidth(diagnostic_col, diagnostic_width)

        total_column_width = sum(
            self.scanner_table.columnWidth(col)
            for col in range(model.columnCount())
        )
        preferred_table_width = total_column_width + 24
        self.scanner_table.setMaximumWidth(max(920, preferred_table_width))

    def _fit_text_column_width(self, model, column: int, minimum: int, maximum: int, padding: int) -> int:
        font_metrics = self.scanner_table.fontMetrics()
        header_text = str(model.headerData(column, Qt.Horizontal) or "")
        content_width = font_metrics.horizontalAdvance(header_text) + padding
        for row in range(model.rowCount()):
            text = str(model.data(model.index(row, column), Qt.DisplayRole) or "")
            content_width = max(content_width, font_metrics.horizontalAdvance(text) + padding)
        return min(max(content_width, minimum), maximum)

    def _fit_badges_column_width(self, model, column: int, font_metrics) -> int:
        header_text = str(model.headerData(column, Qt.Horizontal) or "")
        content_width = font_metrics.horizontalAdvance(header_text) + 24
        for row in range(model.rowCount()):
            badges = model.data(model.index(row, column), ROLE_BADGES) or []
            if not badges:
                continue
            badge_width = 20
            for badge in badges:
                badge_width += font_metrics.horizontalAdvance(str(badge)) + 22
            badge_width += max(0, len(badges) - 1) * 4
            content_width = max(content_width, badge_width)
        return min(max(content_width, 128), 280)

    def _drill_down_branch_from_detail(self, index):
        if not index.isValid() or self.detail_table.model() is None:
            return
        model = self.detail_table.model()
        if not hasattr(model, "getDataFrame"):
            return
        df = model.getDataFrame()
        if index.row() >= len(df) or "分點名稱" not in df.columns:
            return

        branch_name = str(df.iloc[index.row()].get("分點名稱", "")).strip()
        if not branch_name:
            return

        match_idx = self.branch_combo.findText(branch_name)
        if match_idx < 0:
            QMessageBox.warning(self, "找不到分點", f"分點追蹤清單中找不到「{branch_name}」。")
            return

        self.tab_widget.setCurrentIndex(1)
        self.branch_combo.setCurrentIndex(match_idx)
        self._on_branch_changed()

    def _refresh_data(self):
        try:
            period = self._get_current_period_val()

            # 1. 取得信號資料
            signals = self.flow_service.get_stock_flow_signals(period=period)
            self._all_scanner_signals = list(signals or [])

            # 2. 更新 Summary Strip
            summary = self.flow_service.get_market_flow_summary(signals=signals, period=period)
            self.summary_strip.update_summary(summary)

            # 3. 更新 Scanner Table (使用自定義 Model)
            self._apply_scanner_signals(self._all_scanner_signals)

            # 4. 更新 Branch Tracker 分點選單
            branches = self.flow_service.get_tracked_branches()
            current_branch = self.branch_combo.currentData()

            self.branch_combo.blockSignals(True)
            self.branch_combo.clear()
            idx_to_select = 0
            for i, b in enumerate(branches):
                self.branch_combo.addItem(b['display_name'], b['system_key'])
                if b['system_key'] == current_branch:
                    idx_to_select = i
            if branches:
                self.branch_combo.setCurrentIndex(idx_to_select)
            self.branch_combo.blockSignals(False)

            # 更新 Branch 表格
            self._on_branch_changed()

        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"載入主力流向資料失敗：\n{str(e)}\n{traceback.format_exc()}")

    def _on_scanner_selection_changed(self):
        selection = self.scanner_table.selectionModel().selectedRows()
        if not selection:
            return

        row = selection[0].row()
        signal = self.scanner_model.get_signal_at(row)
        if not signal:
            return

        # 1. 更新股票摘要卡片
        self.sub_card_title.setText(f"{signal.stock_name} ({signal.stock_code})")

        warning_html = ""
        if getattr(signal, 'has_estimated_lots', False):
            warning_html = "<div style='color:#f97316; font-weight:bold; margin-bottom:6px;'>注意：本訊號包含歷史金額與股價折算之估計張數資料</div>"

        stats_html = warning_html + (
            f"<span style='color:#94a3b8;'>主力分數：</span><b><font color='#ffffff'>{signal.smart_money_score:.1f}</font></b>"
            f" &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<span style='color:#94a3b8;'>籌碼集中度：</span><b><font color='#ffffff'>{signal.branch_concentration:.0%}</font></b><br/>"
        )
        if signal.explainable_reasons:
            stats_html += "<br/><b><span style='color:#3b82f6;'>訊號解析原因：</span></b><br/>"
            for reason in signal.explainable_reasons:
                stats_html += f"• {reason}<br/>"
        self.sub_card_stats.setText(stats_html)

        # 2. 載入 Detail
        period = self._get_current_period_val()
        details = self.flow_service.get_stock_detail_by_branches(signal.stock_code, period)

        # 先按淨買賣超數值進行數值排序 (None 視為極小)
        details_sorted = sorted(
            details,
            key=lambda x: x.total_net_qty if x.total_net_qty is not None else -99999999,
            reverse=True
        )

        data = []
        for d in details_sorted:
            if d.usable_event_count == 0:
                buy_val = "—"
                sell_val = "—"
                net_val = "不可用"
            else:
                if d.has_estimated_lots:
                    buy_val = f"{d.total_buy_qty:,}*(估)" if d.total_buy_qty is not None else "—"
                    sell_val = f"{d.total_sell_qty:,}*(估)" if d.total_sell_qty is not None else "—"
                    net_val = f"{d.total_net_qty:+,}*(估)" if d.total_net_qty is not None else "0*(估)"
                else:
                    buy_val = f"{d.total_buy_qty:,}" if d.total_buy_qty is not None else "—"
                    sell_val = f"{d.total_sell_qty:,}" if d.total_sell_qty is not None else "—"
                    net_val = f"{d.total_net_qty:+,}" if d.total_net_qty is not None else "0"

            data.append({
                '分點名稱': d.branch_display_name,
                '買進張數': buy_val,
                '賣出張數': sell_val,
                '淨買賣超': net_val
            })

        df_detail = pd.DataFrame(data) if data else pd.DataFrame(columns=['分點名稱', '買進張數', '賣出張數', '淨買賣超'])
        self.detail_table.setModel(PandasTableModel(df_detail))
        self._fit_detail_table_columns()

    def _fit_detail_table_columns(self):
        model = self.detail_table.model()
        if model is None or model.columnCount() == 0:
            return

        header = self.detail_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)

        viewport_width = max(0, self.detail_table.viewport().width() - 18)
        if viewport_width <= 0:
            return

        column_count = min(model.columnCount(), 4)
        font_metrics = self.detail_table.fontMetrics()
        minimums = [98, 68, 68, 128]
        paddings = [24, 20, 20, 86]
        desired_widths = []
        for col in range(column_count):
            header_text = str(model.headerData(col, Qt.Horizontal) or "")
            content_width = font_metrics.horizontalAdvance(header_text) + paddings[col]
            for row in range(model.rowCount()):
                text = str(model.data(model.index(row, col), Qt.DisplayRole) or "")
                content_width = max(content_width, font_metrics.horizontalAdvance(text) + paddings[col])
            desired_widths.append(max(minimums[col], content_width))

        total_desired = sum(desired_widths)
        if total_desired < viewport_width:
            extra = viewport_width - total_desired
            weights = [2, 1, 1, 3]
            total_weight = sum(weights[:column_count])
            widths = [
                desired_widths[col] + int(extra * weights[col] / total_weight)
                for col in range(column_count)
            ]
            widths[-1] += viewport_width - sum(widths)
        else:
            widths = desired_widths
            overflow = total_desired - viewport_width
            for col in (0, 1, 2, 3):
                if col >= column_count or overflow <= 0:
                    break
                reducible = max(0, widths[col] - minimums[col])
                reduction = min(reducible, overflow)
                widths[col] -= reduction
                overflow -= reduction

        for col, width in enumerate(widths):
            self.detail_table.setColumnWidth(col, max(48, width))

    def _on_branch_changed(self):
        branch_key = self.branch_combo.currentData()
        if not branch_key:
            return

        period = self._get_current_period_val()
        all_flows = self.flow_service.get_branch_flow_details(period=period)

        # 過濾特定分點
        branch_flows = [f for f in all_flows if f.branch_system_key == branch_key]

        self.branch_model = BranchTrackerTableModel(branch_flows)
        self.branch_table.setModel(self.branch_model)

        # 調整欄寬
        branch_header = self.branch_table.horizontalHeader()
        branch_header.setStretchLastSection(False)
        branch_header.setSectionResizeMode(QHeaderView.Interactive)
        self.branch_table.setColumnWidth(0, 110) # 淨量分數
        self.branch_table.setColumnWidth(1, 160) # 股票
        self.branch_table.setColumnWidth(2, 90)  # 買進
        self.branch_table.setColumnWidth(3, 90)  # 賣出
        self.branch_table.setColumnWidth(4, 200) # Badges
        self.branch_table.setColumnWidth(5, 150) # Sparkline

    def _add_to_watchlist(self):
        if not self.watchlist_service:
            return

        selection = self.scanner_table.selectionModel().selectedRows()
        if not selection:
            QMessageBox.warning(self, "提示", "請先選擇要加入觀察清單的股票")
            return

        stocks_to_add = []
        for index in selection:
            signal = self.scanner_model.get_signal_at(index.row())
            if signal:
                stocks_to_add.append({
                    'stock_code': signal.stock_code,
                    'stock_name': signal.stock_name
                })

        if stocks_to_add:
            try:
                added_count = self.watchlist_service.add_stocks(stocks_to_add, source='smart_money')
                if added_count > 0:
                    QMessageBox.information(self, "成功", f"已將 {added_count} 檔股票加入觀察清單")
                else:
                    QMessageBox.warning(self, "提示", "選中的股票已在觀察清單中")
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"加入觀察清單失敗：\n{str(e)}")

    def load_data_if_needed(self):
        if not self._data_loaded:
            self._refresh_data()
            self._data_loaded = True

    def select_stock(self, stock_code: str):
        """程式化選取並高亮掃描表格中的個股"""
        self.load_data_if_needed()
        if not hasattr(self, 'scanner_model') or self.scanner_model is None:
            return

        stock_code = str(stock_code).strip()
        row_idx = -1
        for r in range(self.scanner_model.rowCount()):
            sig = self.scanner_model.get_signal_at(r)
            if sig and sig.stock_code == stock_code:
                row_idx = r
                break

        if row_idx != -1:
            selection_model = self.scanner_table.selectionModel()
            if selection_model:
                index = self.scanner_model.index(row_idx, 0)
                selection_model.select(
                    index,
                    QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
                )
                self.scanner_table.scrollTo(index)
                self._on_scanner_selection_changed()
