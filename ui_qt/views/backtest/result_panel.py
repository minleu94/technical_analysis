"""
回測結果面板
包含所有實驗摘要、圖表、最佳化結果、比較與批次/推薦結果呈現分頁
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QGroupBox, QTableView, QTextEdit, QComboBox, 
    QHeaderView, QListWidget, QTabWidget, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui_qt.widgets.fast_chart_widget import (
    create_drawdown_curve_widget,
    create_equity_curve_widget,
    create_holding_days_histogram_widget,
    create_trade_return_histogram_widget,
)
from ui_qt.views.research_lab.run_registry_compare_widget import RunRegistryCompareWidget


class BacktestResultPanel(QWidget):
    """回測結果面板"""
    
    def __init__(self, parent_view, parent=None):
        """初始化結果面板
        
        Args:
            parent_view: 父視圖 BacktestView 實例，用於獲取服務和回調方法
            parent: 父窗口
        """
        super().__init__(parent)
        self.parent_view = parent_view
        
        # 預留的 trades_model 內部變數
        self._trades_model = None
        
        self._setup_ui()
        
    @property
    def trades_model(self):
        return self._trades_model
        
    @trades_model.setter
    def trades_model(self, value):
        self._trades_model = value

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.result_tabs = QTabWidget()
        
        # Tab 1: 結果
        result_tab = QWidget()
        result_layout = QVBoxLayout(result_tab)
        result_layout.setSpacing(10)
        result_layout.setContentsMargins(5, 5, 5, 5)
        
        # 績效摘要
        summary_group = QGroupBox("實驗摘要")
        summary_layout = QVBoxLayout()
        
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(150)
        self.summary_text.setFont(QFont("Consolas", 9))
        summary_layout.addWidget(self.summary_text)
        
        # 單股回測 Excel 匯出按鈕
        btn_layout = QHBoxLayout()
        self.export_report_btn = QPushButton("📊 匯出 Excel 報告")
        self.export_report_btn.setEnabled(False)
        self.export_report_btn.setToolTip("匯出目前單股回測的詳細研究報告（報告僅輸出目前結果，不重新計算績效）")
        self.export_report_btn.clicked.connect(self.parent_view._export_single_backtest)
        btn_layout.addStretch()
        btn_layout.addWidget(self.export_report_btn)
        summary_layout.addLayout(btn_layout)
        
        summary_group.setLayout(summary_layout)
        result_layout.addWidget(summary_group, stretch=65)
        
        # 交易明細
        trades_group = QGroupBox("交易明細")
        trades_layout = QVBoxLayout()
        
        self.trades_table = QTableView()
        self.trades_table.setAlternatingRowColors(True)
        self.trades_table.setSelectionBehavior(QTableView.SelectRows)
        self.trades_table.setSortingEnabled(True)
        self.trades_table.horizontalHeader().setStretchLastSection(True)
        self.trades_table.setMinimumHeight(150)
        self.trades_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.trades_table.setFont(QFont("Consolas", 9))
        
        # 啟用右鍵選單
        self.trades_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.trades_table.customContextMenuRequested.connect(self.parent_view._show_trades_table_context_menu)
        
        trades_layout.addWidget(self.trades_table)
        trades_group.setLayout(trades_layout)
        result_layout.addWidget(trades_group, stretch=35)
        
        self.result_tabs.addTab(result_tab, "實驗摘要")
        
        # Tab 2: 圖表
        if self.parent_view.chart_data_service:
            chart_tab = QWidget()
            chart_layout = QVBoxLayout(chart_tab)
            
            run_select_row = QHBoxLayout()
            run_select_row.addWidget(QLabel("選擇回測結果:"))
            self.chart_run_combo = QComboBox()
            self.chart_run_combo.setEditable(False)
            self.chart_run_combo.currentTextChanged.connect(self.parent_view._on_chart_run_changed)
            run_select_row.addWidget(self.chart_run_combo)
            run_select_row.addStretch()
            chart_layout.addLayout(run_select_row)
            
            chart_tabs = QTabWidget()
            
            self.equity_chart = create_equity_curve_widget()
            chart_tabs.addTab(self.equity_chart, "權益曲線")
            
            self.drawdown_chart = create_drawdown_curve_widget()
            chart_tabs.addTab(self.drawdown_chart, "回撤曲線")
            
            self.return_hist = create_trade_return_histogram_widget()
            chart_tabs.addTab(self.return_hist, "報酬分佈")
            
            self.holding_hist = create_holding_days_histogram_widget()
            chart_tabs.addTab(self.holding_hist, "持有天數")
            
            chart_layout.addWidget(chart_tabs)
            self.result_tabs.addTab(chart_tab, "圖表")
        
        # Tab 3: 最佳化結果
        if self.parent_view.optimizer_service:
            optimization_result_tab = QWidget()
            optimization_result_layout = QVBoxLayout(optimization_result_tab)
            
            optimization_result_group = QGroupBox("最佳化結果")
            optimization_result_layout_inner = QVBoxLayout()
            
            self.optimization_table = QTableView()
            self.optimization_table.setAlternatingRowColors(True)
            self.optimization_table.setSelectionBehavior(QTableView.SelectRows)
            self.optimization_table.setSortingEnabled(True)
            self.optimization_table.horizontalHeader().setStretchLastSection(True)
            self.optimization_table.setMinimumHeight(200)
            self.optimization_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.optimization_table.setFont(QFont("Consolas", 9))
            self.optimization_table.doubleClicked.connect(self.parent_view._apply_optimization_params)
            optimization_result_layout_inner.addWidget(self.optimization_table)
            
            apply_btn = QPushButton("套用選中參數")
            apply_btn.clicked.connect(self.parent_view._apply_optimization_params)
            optimization_result_layout_inner.addWidget(apply_btn)
            
            optimization_result_group.setLayout(optimization_result_layout_inner)
            optimization_result_layout.addWidget(optimization_result_group)
            
            self.result_tabs.addTab(optimization_result_tab, "最佳化 / 驗證")
            
        # Tab 4: 比較
        if self.parent_view.run_repository:
            compare_tab = QWidget()
            compare_layout = QVBoxLayout(compare_tab)
            
            history_group = QGroupBox("回測歷史")
            history_layout = QVBoxLayout()
            
            history_btn_row = QHBoxLayout()
            self.refresh_history_btn = QPushButton("重新整理")
            self.refresh_history_btn.clicked.connect(self.parent_view._refresh_history)
            history_btn_row.addWidget(self.refresh_history_btn)
            
            self.delete_history_btn = QPushButton("刪除選中")
            self.delete_history_btn.setStyleSheet("background-color: #F44336; color: white;")
            self.delete_history_btn.clicked.connect(self.parent_view._delete_history_runs)
            history_btn_row.addWidget(self.delete_history_btn)
            
            history_btn_row.addStretch()
            history_layout.addLayout(history_btn_row)
            
            self.history_list = QListWidget()
            self.history_list.setSelectionMode(QListWidget.ExtendedSelection)
            self.history_list.itemDoubleClicked.connect(self.parent_view._load_history_run)
            history_layout.addWidget(self.history_list)
            
            compare_btn = QPushButton("比較選中")
            compare_btn.clicked.connect(self.parent_view._compare_runs)
            history_layout.addWidget(compare_btn)
            
            history_group.setLayout(history_layout)
            compare_layout.addWidget(history_group)
            
            compare_result_group = QGroupBox("比較結果")
            compare_result_layout = QVBoxLayout()
            
            self.compare_table = QTableView()
            self.compare_table.setAlternatingRowColors(True)
            self.compare_table.setSortingEnabled(True)
            self.compare_table.horizontalHeader().setStretchLastSection(True)
            self.compare_table.setSelectionBehavior(QTableView.SelectRows)
            self.compare_table.doubleClicked.connect(self.parent_view._on_compare_table_double_clicked)
            compare_result_layout.addWidget(self.compare_table)
            
            compare_result_group.setLayout(compare_result_layout)
            compare_layout.addWidget(compare_result_group)
            
            self.result_tabs.addTab(compare_tab, "歷史與比較")
            
        # Tab 5: 批次結果
        if self.parent_view.batch_backtest_service:
            batch_result_tab = QWidget()
            batch_result_layout = QVBoxLayout(batch_result_tab)
            batch_result_layout.setSpacing(10)
            batch_result_layout.setContentsMargins(5, 5, 5, 5)

            self.batch_interpretation_label = QLabel(
                "比較目的：排行榜用來快速找出同一批次內相對值得複核的股票；"
                "整體統計用來觀察樣本分布與成功率。此頁只整理已完成的批次回測結果，"
                "不代表正式策略判斷、交易建議或持倉調整。"
            )
            self.batch_interpretation_label.setWordWrap(True)
            self.batch_interpretation_label.setStyleSheet(
                "padding: 6px; background: #F6F8FA; border: 1px solid #D0D7DE;"
            )
            batch_result_layout.addWidget(self.batch_interpretation_label)
            
            sort_row = QHBoxLayout()
            sort_row.addWidget(QLabel("排序方式:"))
            self.batch_sort_combo = QComboBox()
            self.batch_sort_combo.addItems(["CAGR-MDD", "CAGR", "Sharpe", "MDD"])
            self.batch_sort_combo.currentTextChanged.connect(self.parent_view._on_batch_sort_changed)
            sort_row.addWidget(self.batch_sort_combo)
            sort_row.addStretch()
            
            self.export_batch_report_btn = QPushButton("📊 匯出批次 Excel")
            self.export_batch_report_btn.setEnabled(False)
            self.export_batch_report_btn.setToolTip("匯出目前批次操作的排行榜與統計報告")
            self.export_batch_report_btn.clicked.connect(self.parent_view._export_batch_backtest)
            sort_row.addWidget(self.export_batch_report_btn)
            
            batch_result_layout.addLayout(sort_row)
            
            batch_leaderboard_group = QGroupBox("排行榜")
            batch_leaderboard_layout = QVBoxLayout()
            
            self.batch_leaderboard_table = QTableView()
            self.batch_leaderboard_table.setAlternatingRowColors(True)
            self.batch_leaderboard_table.setSelectionBehavior(QTableView.SelectRows)
            self.batch_leaderboard_table.setSortingEnabled(False)
            self.batch_leaderboard_table.horizontalHeader().setStretchLastSection(True)
            self.batch_leaderboard_table.doubleClicked.connect(self.parent_view._on_batch_row_double_clicked)
            self.batch_leaderboard_table.setMinimumHeight(300)
            self.batch_leaderboard_table.setFont(QFont("Consolas", 9))
            batch_leaderboard_layout.addWidget(self.batch_leaderboard_table)
            
            batch_leaderboard_group.setLayout(batch_leaderboard_layout)
            batch_result_layout.addWidget(batch_leaderboard_group, stretch=2)
            
            batch_stats_group = QGroupBox("整體統計")
            batch_stats_layout = QVBoxLayout()
            
            self.batch_stats_text = QTextEdit()
            self.batch_stats_text.setReadOnly(True)
            self.batch_stats_text.setMaximumHeight(100)
            self.batch_stats_text.setFont(QFont("Consolas", 10))
            batch_stats_layout.addWidget(self.batch_stats_text)
            
            batch_stats_group.setLayout(batch_stats_layout)
            batch_result_layout.addWidget(batch_stats_group, stretch=1)
            
            self.result_tabs.addTab(batch_result_tab, "批次結果")
            
        # Tab 6: 推薦回放
        recommendation_portfolio_tab = QWidget()
        recommendation_portfolio_layout = QVBoxLayout(recommendation_portfolio_tab)
        recommendation_portfolio_layout.setSpacing(8)
        recommendation_portfolio_layout.setContentsMargins(5, 5, 5, 5)
        
        self.portfolio_summary_text = QTextEdit()
        self.portfolio_summary_text.setReadOnly(True)
        self.portfolio_summary_text.setMaximumHeight(200)
        self.portfolio_summary_text.setFont(QFont("Consolas", 9))
        recommendation_portfolio_layout.addWidget(self.portfolio_summary_text)
        
        # 推薦回放 Excel 匯出按鈕列
        portfolio_btn_row = QHBoxLayout()
        portfolio_btn_row.addStretch()
        self.export_portfolio_report_btn = QPushButton("📊 匯出回放 Excel")
        self.export_portfolio_report_btn.setEnabled(False)
        self.export_portfolio_report_btn.setToolTip("匯出推薦回放的組合持倉與個股貢獻報告")
        self.export_portfolio_report_btn.clicked.connect(self.parent_view._export_recommendation_replay)
        portfolio_btn_row.addWidget(self.export_portfolio_report_btn)
        recommendation_portfolio_layout.addLayout(portfolio_btn_row)
        
        self.portfolio_detail_tabs = QTabWidget()

        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self.portfolio_chart_tabs = QTabWidget()
        self.portfolio_equity_chart = create_equity_curve_widget()
        self.portfolio_drawdown_chart = create_drawdown_curve_widget()
        self.portfolio_chart_tabs.addTab(self.portfolio_equity_chart, "組合價值")
        self.portfolio_chart_tabs.addTab(self.portfolio_drawdown_chart, "回撤")
        chart_layout.addWidget(self.portfolio_chart_tabs)
        self.portfolio_detail_tabs.addTab(chart_container, "圖表")
        
        self.portfolio_period_table = QTableView()
        self.portfolio_stock_table = QTableView()
        self.portfolio_trades_table = QTableView()
        
        for table in [
            self.portfolio_period_table,
            self.portfolio_stock_table,
            self.portfolio_trades_table
        ]:
            table.setAlternatingRowColors(True)
            table.setSelectionBehavior(QTableView.SelectRows)
            table.setSortingEnabled(True)
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            table.setFont(QFont("Consolas", 9))
            
        period_tab = QWidget()
        period_layout = QVBoxLayout(period_tab)
        period_layout.setContentsMargins(0, 0, 0, 0)
        period_layout.addWidget(self.portfolio_period_table)
        self.portfolio_detail_tabs.addTab(period_tab, "期間明細")

        stock_tab = QWidget()
        stock_layout = QVBoxLayout(stock_tab)
        stock_layout.setContentsMargins(0, 0, 0, 0)
        stock_layout.addWidget(self.portfolio_stock_table)
        self.portfolio_detail_tabs.addTab(stock_tab, "個股貢獻")

        trades_tab = QWidget()
        trades_layout = QVBoxLayout(trades_tab)
        trades_layout.setContentsMargins(0, 0, 0, 0)
        trades_layout.addWidget(self.portfolio_trades_table)
        self.portfolio_detail_tabs.addTab(trades_tab, "交易紀錄")

        recommendation_portfolio_layout.addWidget(self.portfolio_detail_tabs, stretch=5)
        
        self.result_tabs.addTab(recommendation_portfolio_tab, "推薦回放")
        
        layout.addWidget(self.result_tabs)

        if getattr(self.parent_view, "research_run_service", None):
            self.add_registry_compare_tab()

    def add_registry_compare_tab(self):
        """將 Research Run Registry 比較頁掛入既有 Research Lab 結果分頁。"""
        existing = getattr(self, "run_registry_compare_widget", None)
        if existing is not None:
            return existing

        service = getattr(self.parent_view, "research_run_service", None)
        if service is None:
            return None

        self.run_registry_compare_widget = RunRegistryCompareWidget(service)
        self.result_tabs.addTab(self.run_registry_compare_widget, "Registry 比較")
        return self.run_registry_compare_widget
