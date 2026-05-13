"""
Smart Money Flow - Terminal Style Scanner 主視圖
整合 Summary Strip 與使用 Custom Delegate 的 Scanner Table。
"""

import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableView, QMessageBox,
    QTabWidget, QSplitter, QComboBox, QHeaderView
)
from PySide6.QtCore import Qt

from ui_qt.widgets.info_button import InfoButton
from app_module.broker_flow_service import BrokerFlowService
from app_module.watchlist_service import WatchlistService
from ui_qt.views.smart_money.summary_strip import SummaryStrip
from ui_qt.views.smart_money.terminal_table_model import TerminalTableModel, BranchTrackerTableModel
from ui_qt.views.smart_money.terminal_delegate import TerminalScannerDelegate
from ui_qt.models.pandas_table_model import PandasTableModel # 給 Detail Table 用

class SmartMoneyFlowView(QWidget):
    """Terminal Style Smart Money Scanner 主視圖"""
    
    def __init__(self, broker_flow_service: BrokerFlowService, watchlist_service: WatchlistService = None, parent=None):
        super().__init__(parent)
        self.flow_service = broker_flow_service
        self.watchlist_service = watchlist_service
        self._data_loaded = False
        
        # 色彩設定 (Terminal 深色風格背景)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), Qt.black)
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        
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
        control_layout = QHBoxLayout(control_widget)
        control_layout.setContentsMargins(15, 10, 15, 10)
        
        title_lbl = QLabel("SMART MONEY SCANNER")
        title_lbl.setStyleSheet("color: #94a3b8; font-weight: bold; font-family: Courier;")
        control_layout.addWidget(title_lbl)
        
        info_btn = InfoButton("smart_money_flow", self)
        control_layout.addWidget(info_btn)
        
        control_layout.addStretch()
        
        control_layout.addWidget(QLabel("PERIOD:", styleSheet="color: #94a3b8; font-family: Courier;"))
        self.period_combo = QComboBox()
        self.period_combo.addItems(["DAY", "WEEK", "MONTH"])
        self.period_combo.setCurrentIndex(1)
        self.period_combo.currentIndexChanged.connect(self._on_period_changed)
        self.period_combo.setStyleSheet("background-color: #1e293b; color: white; border: 1px solid #334155;")
        control_layout.addWidget(self.period_combo)
        
        control_layout.addWidget(QLabel(" CHART:", styleSheet="color: #94a3b8; font-family: Courier;"))
        self.chart_combo = QComboBox()
        self.chart_combo.addItems(["BAR", "LINE", "AREA"])
        self.chart_combo.setCurrentIndex(0)
        self.chart_combo.currentIndexChanged.connect(self._on_chart_changed)
        self.chart_combo.setStyleSheet("background-color: #1e293b; color: white; border: 1px solid #334155;")
        control_layout.addWidget(self.chart_combo)
        
        self.refresh_btn = QPushButton("SCAN")
        self.refresh_btn.setStyleSheet("background-color: #3b82f6; color: white; font-weight: bold; padding: 4px 15px;")
        self.refresh_btn.clicked.connect(self._refresh_data)
        control_layout.addWidget(self.refresh_btn)
        
        if self.watchlist_service:
            self.add_watchlist_btn = QPushButton("+ WATCHLIST")
            self.add_watchlist_btn.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 4px 15px;")
            self.add_watchlist_btn.clicked.connect(self._add_to_watchlist)
            control_layout.addWidget(self.add_watchlist_btn)
            
        main_layout.addWidget(control_widget)
        
        # --- Body: Tabs ---
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #334155; background-color: black; }
            QTabBar::tab { background: #0f172a; color: #94a3b8; padding: 8px 20px; font-weight: bold; }
            QTabBar::tab:selected { background: #1e293b; color: white; border-bottom: 2px solid #3b82f6; }
        """)
        main_layout.addWidget(self.tab_widget)
        
        # === Tab 1: Stock Overview ===
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setContentsMargins(0, 0, 0, 0)
        
        self.splitter = QSplitter(Qt.Vertical)
        
        # Master: Terminal Scanner Table
        self.scanner_table = QTableView()
        self.scanner_table.setSelectionBehavior(QTableView.SelectRows)
        self.scanner_table.setSortingEnabled(True)
        self.scanner_table.horizontalHeader().setStretchLastSection(True)
        self.scanner_table.verticalHeader().setVisible(False)
        self.scanner_table.setShowGrid(False) # 移除傳統格線
        self.scanner_table.setStyleSheet("""
            QTableView {
                background-color: #000000;
                color: #e2e8f0;
                border: none;
            }
            QHeaderView::section {
                background-color: #0f172a;
                color: #94a3b8;
                border: none;
                border-bottom: 1px solid #334155;
                font-family: Courier;
                font-weight: bold;
                padding: 4px;
            }
            QTableView::item:selected {
                background-color: transparent;
            }
        """)
        
        # 套用自定義委派
        self.delegate = TerminalScannerDelegate(self.scanner_table)
        self.scanner_table.setItemDelegate(self.delegate)
        # 增加 Row Height 以容納 Badges 與 Sparklines
        self.scanner_table.verticalHeader().setDefaultSectionSize(46)
        
        self.splitter.addWidget(self.scanner_table)
        
        # Detail: Drill-down Table (沿用傳統 Pandas Table)
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(10, 10, 10, 10)
        
        self.detail_label = QLabel("BRANCH DRILL-DOWN: --")
        self.detail_label.setStyleSheet("color: #94a3b8; font-family: Courier; font-weight: bold;")
        detail_layout.addWidget(self.detail_label)
        
        self.detail_table = QTableView()
        self.detail_table.setSelectionBehavior(QTableView.SelectRows)
        self.detail_table.setSortingEnabled(True)
        self.detail_table.setStyleSheet("background-color: #0f172a; color: white;")
        detail_layout.addWidget(self.detail_table)
        
        self.splitter.addWidget(detail_widget)
        
        # 設定比例
        self.splitter.setSizes([700, 300])
        tab1_layout.addWidget(self.splitter)
        self.tab_widget.addTab(tab1, "STOCK OVERVIEW")
        
        # === Tab 2: Branch Tracker ===
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setContentsMargins(0, 0, 0, 0)
        
        b_control_widget = QWidget()
        b_control_layout = QHBoxLayout(b_control_widget)
        b_control_layout.setContentsMargins(15, 10, 15, 10)
        b_control_layout.addWidget(QLabel("TRACKED BRANCH:", styleSheet="color: #94a3b8; font-family: Courier;"))
        
        self.branch_combo = QComboBox()
        self.branch_combo.setStyleSheet("background-color: #1e293b; color: white; border: 1px solid #334155;")
        self.branch_combo.setMinimumWidth(250)
        self.branch_combo.currentIndexChanged.connect(self._on_branch_changed)
        b_control_layout.addWidget(self.branch_combo)
        b_control_layout.addStretch()
        tab2_layout.addWidget(b_control_widget)
        
        self.branch_table = QTableView()
        self.branch_table.setSelectionBehavior(QTableView.SelectRows)
        self.branch_table.setSortingEnabled(True)
        self.branch_table.horizontalHeader().setStretchLastSection(True)
        self.branch_table.verticalHeader().setVisible(False)
        self.branch_table.setShowGrid(False)
        self.branch_table.setStyleSheet(self.scanner_table.styleSheet())
        self.branch_table.verticalHeader().setDefaultSectionSize(46)
        
        self.branch_delegate = TerminalScannerDelegate(self.branch_table)
        self.branch_table.setItemDelegate(self.branch_delegate)
        tab2_layout.addWidget(self.branch_table)
        
        self.tab_widget.addTab(tab2, "BRANCH TRACKER")
        
        self._on_chart_changed()
        
    def _get_current_period_val(self) -> str:
        idx = self.period_combo.currentIndex()
        if idx == 0: return 'day'
        if idx == 2: return 'month'
        return 'week'
        
    def _on_period_changed(self):
        self._refresh_data()
        
    def _on_chart_changed(self):
        chart_type = self.chart_combo.currentText().lower()
        self.delegate.chart_type = chart_type
        self.branch_delegate.chart_type = chart_type
        self.scanner_table.viewport().update()
        self.branch_table.viewport().update()
        
    def _refresh_data(self):
        try:
            period = self._get_current_period_val()
            
            # 1. 取得信號資料
            signals = self.flow_service.get_stock_flow_signals(period=period)
            
            # 2. 更新 Summary Strip
            summary = self.flow_service.get_market_flow_summary(signals=signals, period=period)
            self.summary_strip.update_summary(summary)
            
            # 3. 更新 Scanner Table (使用自定義 Model)
            self.scanner_model = TerminalTableModel(signals)
            self.scanner_table.setModel(self.scanner_model)
            
            # 調整欄寬 (給 Sparkline 跟 Badges 更多空間)
            self.scanner_table.setColumnWidth(0, 60)  # 分數
            self.scanner_table.setColumnWidth(1, 150) # 股票
            self.scanner_table.setColumnWidth(2, 80)  # 淨量
            self.scanner_table.setColumnWidth(3, 70)  # 集中度
            self.scanner_table.setColumnWidth(4, 250) # Badges
            self.scanner_table.setColumnWidth(5, 120) # Sparkline
            
            # 重新綁定事件
            sel_model = self.scanner_table.selectionModel()
            if sel_model:
                sel_model.selectionChanged.connect(self._on_scanner_selection_changed)
                
            # 清空 Detail
            self.detail_label.setText("BRANCH DRILL-DOWN: --")
            self.detail_table.setModel(PandasTableModel(pd.DataFrame(columns=['分點名稱', '買進', '賣出', '淨量'])))
            
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
            import traceback
            QMessageBox.critical(self, "錯誤", f"載入主力流向資料失敗：\n{str(e)}\n{traceback.format_exc()}")
            
    def _on_scanner_selection_changed(self):
        selection = self.scanner_table.selectionModel().selectedRows()
        if not selection:
            return
            
        row = selection[0].row()
        signal = self.scanner_model.get_signal_at(row)
        if not signal:
            return
            
        self.detail_label.setText(f"BRANCH DRILL-DOWN: {signal.stock_name} ({signal.stock_code})")
        
        # 載入 Detail
        period = self._get_current_period_val()
        details = self.flow_service.get_stock_detail_by_branches(signal.stock_code, period)
        
        data = []
        for d in details:
            data.append({
                '分點名稱': d.branch_display_name,
                '買進張數': d.total_buy_qty,
                '賣出張數': d.total_sell_qty,
                '淨買賣超': d.total_net_qty
            })
            
        data.sort(key=lambda x: x['淨買賣超'], reverse=True)
        df_detail = pd.DataFrame(data) if data else pd.DataFrame(columns=['分點名稱', '買進張數', '賣出張數', '淨買賣超'])
        self.detail_table.setModel(PandasTableModel(df_detail))
        self.detail_table.resizeColumnsToContents()

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
        self.branch_table.setColumnWidth(0, 100) # 淨量分數
        self.branch_table.setColumnWidth(1, 150) # 股票
        self.branch_table.setColumnWidth(2, 80)  # 買進
        self.branch_table.setColumnWidth(3, 80)  # 賣出
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
