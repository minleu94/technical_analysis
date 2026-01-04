"""
回測視圖
提供回測配置界面和結果顯示
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableView, QGroupBox, QProgressBar,
    QTextEdit, QHeaderView, QLineEdit, QDoubleSpinBox,
    QDateEdit, QComboBox, QMessageBox, QSplitter, QFormLayout, QSpinBox,
    QTabWidget, QCheckBox, QListWidget, QListWidgetItem, QDialog,
    QDialogButtonBox, QTextEdit as QTextEditDialog, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QDate, QTimer
from PySide6.QtGui import QFont
import pandas as pd
from typing import Dict, Any, Optional, List
from datetime import datetime
from datetime import datetime, timedelta

from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.widgets.info_button import InfoButton
from ui_qt.workers.task_worker import TaskWorker
from app_module.backtest_service import BacktestService
from app_module.strategy_spec import StrategySpec
from app_module.strategy_registry import StrategyRegistry
from app_module.dtos import BacktestReportDTO
from app_module.preset_service import PresetService
from app_module.universe_service import UniverseService
from app_module.backtest_repository import BacktestRunRepository
from app_module.chart_data_service import ChartDataService
from app_module.promotion_service import PromotionService
from app_module.strategy_version_service import StrategyVersionService
from app_module.walkforward_service import WalkForwardService
from ui_qt.widgets.chart_widget import (
    EquityCurveWidget, DrawdownCurveWidget,
    TradeReturnHistogramWidget, HoldingDaysHistogramWidget
)


class BacktestView(QWidget):
    """回測視圖"""
    
    def __init__(
        self,
        backtest_service: BacktestService,
        config=None,
        batch_backtest_service=None,
        watchlist_service=None,
        parent=None
    ):
        """初始化回測視圖
        
        Args:
            backtest_service: 回測服務實例
            config: TWStockConfig 實例（用於新服務）
            batch_backtest_service: 批次回測服務實例（可選）
            watchlist_service: 觀察清單服務實例（可選，用於跨 Tab 共用）
            parent: 父窗口
        """
        super().__init__(parent)
        self.backtest_service = backtest_service
        self.config = config
        self.batch_backtest_service = batch_backtest_service
        self.watchlist_service = watchlist_service
        
        # 初始化新服務
        if config:
            self.preset_service = PresetService(config)
            self.universe_service = UniverseService(config)
            self.run_repository = BacktestRunRepository(config)
            self.chart_data_service = ChartDataService(self.run_repository)
            # 如果沒有傳入 batch_backtest_service，則創建一個
            if not self.batch_backtest_service:
                from app_module.batch_backtest_service import BatchBacktestService
                self.batch_backtest_service = BatchBacktestService(self.backtest_service, self.run_repository)
            # 初始化 Promote 相關服務
            self.strategy_version_service = StrategyVersionService(config)
            self.walkforward_service = WalkForwardService(self.backtest_service)
            self.promotion_service = PromotionService(
                config=config,
                backtest_repository=self.run_repository,
                backtest_service=self.backtest_service,
                walkforward_service=self.walkforward_service,
                strategy_version_service=self.strategy_version_service,
                preset_service=self.preset_service
            )
        else:
            self.preset_service = None
            self.universe_service = None
            self.run_repository = None
            self.chart_data_service = None
            self.strategy_version_service = None
            self.walkforward_service = None
            self.promotion_service = None
        
        # Worker
        self.worker: Optional[TaskWorker] = None
        
        # 當前回測結果（用於保存）
        self.current_report: Optional[BacktestReportDTO] = None
        self.current_run_params: Optional[Dict] = None
        
        # 初始化說明資料結構（集中管理）
        self._init_parameter_descriptions()
        
        self._setup_ui()
    
    def _setup_ui(self):
        """設置 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("策略回測")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("backtest", self)
        title_layout.addWidget(info_btn)
        main_layout.addLayout(title_layout)
        
        # 使用 Splitter 分割配置和結果
        splitter = QSplitter(Qt.Horizontal)
        
        # 左側：配置面板（使用 ScrollArea 支援滾動）
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setMinimumWidth(400)  # 設置最小寬度
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        config_layout.setSpacing(10)
        config_layout.setContentsMargins(10, 10, 10, 10)
        
        # ========== 策略預設區塊 ==========
        if self.preset_service:
            preset_group = QGroupBox("策略預設")
            preset_layout = QVBoxLayout()
            
            preset_row = QHBoxLayout()
            self.preset_combo = QComboBox()
            self.preset_combo.setEditable(False)
            self._populate_preset_combo()
            preset_row.addWidget(self.preset_combo)
            
            preset_btn_row = QHBoxLayout()
            self.save_preset_btn = QPushButton("儲存")
            self.save_preset_btn.setMaximumWidth(60)
            self.save_preset_btn.clicked.connect(self._save_preset)
            preset_btn_row.addWidget(self.save_preset_btn)
            
            self.load_preset_btn = QPushButton("載入")
            self.load_preset_btn.setMaximumWidth(60)
            self.load_preset_btn.clicked.connect(self._load_preset)
            preset_btn_row.addWidget(self.load_preset_btn)
            
            self.delete_preset_btn = QPushButton("刪除")
            self.delete_preset_btn.setMaximumWidth(60)
            self.delete_preset_btn.clicked.connect(self._delete_preset)
            preset_btn_row.addWidget(self.delete_preset_btn)
            
            preset_layout.addLayout(preset_row)
            preset_layout.addLayout(preset_btn_row)
            preset_group.setLayout(preset_layout)
            config_layout.addWidget(preset_group)
        
        # ========== 回測配置 ==========
        config_group = QGroupBox("回測配置")
        config_form = QFormLayout()
        
        # 股票代號（升級為支援單一/清單模式）
        stock_mode_row = QHBoxLayout()
        self.stock_mode_combo = QComboBox()
        self.stock_mode_combo.addItems(["單一股票", "選股清單"])
        self.stock_mode_combo.currentTextChanged.connect(self._on_stock_mode_changed)
        stock_mode_row.addWidget(QLabel("模式:"))
        stock_mode_row.addWidget(self.stock_mode_combo)
        config_form.addRow(stock_mode_row)
        
        # 單一股票輸入
        self.stock_code_input = QLineEdit()
        self.stock_code_input.setPlaceholderText("例如：2330")
        config_form.addRow("股票代號:", self.stock_code_input)
        
        # 選股清單（初始隱藏）
        self.watchlist_widget = QWidget()
        watchlist_layout = QVBoxLayout(self.watchlist_widget)
        watchlist_row = QHBoxLayout()
        self.watchlist_combo = QComboBox()
        self.watchlist_combo.setEditable(False)
        self._populate_watchlist_combo()
        watchlist_row.addWidget(QLabel("清單:"))
        watchlist_row.addWidget(self.watchlist_combo)
        watchlist_btn = QPushButton("管理")
        watchlist_btn.setMaximumWidth(60)
        watchlist_btn.clicked.connect(self._manage_watchlists)
        watchlist_row.addWidget(watchlist_btn)
        watchlist_layout.addLayout(watchlist_row)
        self.watchlist_widget.setVisible(False)
        config_form.addRow(self.watchlist_widget)
        
        # 日期範圍
        self.start_date = QDateEdit()
        self.start_date.setDate(QDate.currentDate().addYears(-1))
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        config_form.addRow("開始日期:", self.start_date)
        
        self.end_date = QDateEdit()
        self.end_date.setDate(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        config_form.addRow("結束日期:", self.end_date)
        
        # 初始資金
        self.capital_input = QDoubleSpinBox()
        self.capital_input.setRange(10000, 100000000)
        self.capital_input.setValue(1000000)
        self.capital_input.setPrefix("$ ")
        self.capital_input.setDecimals(0)
        # 添加 tooltip
        if 'capital' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['capital']['tooltip_lines'])
            self.capital_input.setToolTip(tooltip_text)
        config_form.addRow("初始資金:", self.capital_input)
        
        # 手續費（基點）
        self.fee_bps_input = QDoubleSpinBox()
        self.fee_bps_input.setRange(0, 1000)
        self.fee_bps_input.setValue(14.25)
        self.fee_bps_input.setSuffix(" bps")
        self.fee_bps_input.setDecimals(2)
        # 添加 tooltip
        if 'fee_bps' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['fee_bps']['tooltip_lines'])
            self.fee_bps_input.setToolTip(tooltip_text)
        config_form.addRow("手續費:", self.fee_bps_input)
        
        # 滑價（基點）
        self.slippage_bps_input = QDoubleSpinBox()
        self.slippage_bps_input.setRange(0, 1000)
        self.slippage_bps_input.setValue(5.0)
        self.slippage_bps_input.setSuffix(" bps")
        self.slippage_bps_input.setDecimals(2)
        # 添加 tooltip
        if 'slippage_bps' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['slippage_bps']['tooltip_lines'])
            self.slippage_bps_input.setToolTip(tooltip_text)
        config_form.addRow("滑價:", self.slippage_bps_input)
        
        # 執行價格選擇
        self.execution_price_combo = QComboBox()
        self.execution_price_combo.addItems(["下一根K開盤價 (next_open)", "當根K收盤價 (close)"])
        self.execution_price_combo.setCurrentIndex(0)  # 預設 next_open
        # 添加 tooltip
        if 'execution_price' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['execution_price']['tooltip_lines'])
            self.execution_price_combo.setToolTip(tooltip_text)
        config_form.addRow("執行價格:", self.execution_price_combo)
        
        # 停損停利模式選擇
        self.stop_profit_mode_combo = QComboBox()
        self.stop_profit_mode_combo.addItems(["百分比模式", "ATR 倍數模式"])
        self.stop_profit_mode_combo.setCurrentIndex(0)  # 預設百分比模式
        self.stop_profit_mode_combo.currentTextChanged.connect(self._on_stop_profit_mode_changed)
        # 添加 tooltip
        if 'stop_profit_mode' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['stop_profit_mode']['tooltip_lines'])
            self.stop_profit_mode_combo.setToolTip(tooltip_text)
        config_form.addRow("停損停利模式:", self.stop_profit_mode_combo)
        
        # 停損（%）
        self.stop_loss_input = QDoubleSpinBox()
        self.stop_loss_input.setRange(0, 50)
        self.stop_loss_input.setValue(0)
        self.stop_loss_input.setSuffix("%")
        self.stop_loss_input.setDecimals(2)
        self.stop_loss_input.setSpecialValueText("關閉")
        # 添加 tooltip
        if 'stop_loss_pct' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['stop_loss_pct']['tooltip_lines'])
            self.stop_loss_input.setToolTip(tooltip_text)
        config_form.addRow("停損 (%):", self.stop_loss_input)
        
        # 停利（%）
        self.take_profit_input = QDoubleSpinBox()
        self.take_profit_input.setRange(0, 100)
        self.take_profit_input.setValue(0)
        self.take_profit_input.setSuffix("%")
        self.take_profit_input.setDecimals(2)
        self.take_profit_input.setSpecialValueText("關閉")
        # 添加 tooltip
        if 'take_profit_pct' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['take_profit_pct']['tooltip_lines'])
            self.take_profit_input.setToolTip(tooltip_text)
        config_form.addRow("停利 (%):", self.take_profit_input)
        
        # 停損（ATR 倍數）
        self.stop_loss_atr_input = QDoubleSpinBox()
        self.stop_loss_atr_input.setRange(0, 10)
        self.stop_loss_atr_input.setValue(0)
        self.stop_loss_atr_input.setSuffix(" × ATR")
        self.stop_loss_atr_input.setDecimals(2)
        self.stop_loss_atr_input.setSpecialValueText("關閉")
        self.stop_loss_atr_input.setVisible(False)  # 初始隱藏
        # 添加 tooltip
        if 'stop_loss_atr' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['stop_loss_atr']['tooltip_lines'])
            self.stop_loss_atr_input.setToolTip(tooltip_text)
        config_form.addRow("停損 (ATR):", self.stop_loss_atr_input)
        
        # 停利（ATR 倍數）
        self.take_profit_atr_input = QDoubleSpinBox()
        self.take_profit_atr_input.setRange(0, 20)
        self.take_profit_atr_input.setValue(0)
        self.take_profit_atr_input.setSuffix(" × ATR")
        self.take_profit_atr_input.setDecimals(2)
        self.take_profit_atr_input.setSpecialValueText("關閉")
        self.take_profit_atr_input.setVisible(False)  # 初始隱藏
        # 添加 tooltip
        if 'take_profit_atr' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['take_profit_atr']['tooltip_lines'])
            self.take_profit_atr_input.setToolTip(tooltip_text)
        config_form.addRow("停利 (ATR):", self.take_profit_atr_input)
        
        config_group.setLayout(config_form)
        config_layout.addWidget(config_group)
        
        # ========== 部位 Sizing 配置 ==========
        sizing_group = QGroupBox("部位 Sizing")
        sizing_form = QFormLayout()
        
        # Sizing 模式
        self.sizing_mode_combo = QComboBox()
        self.sizing_mode_combo.addItems(["全倉", "固定金額", "風險百分比"])
        self.sizing_mode_combo.currentTextChanged.connect(self._on_sizing_mode_changed)
        # 添加 tooltip
        if 'sizing_mode' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['sizing_mode']['tooltip_lines'])
            self.sizing_mode_combo.setToolTip(tooltip_text)
        sizing_form.addRow("Sizing 模式:", self.sizing_mode_combo)
        
        # 固定金額（初始隱藏）
        self.fixed_amount_input = QDoubleSpinBox()
        self.fixed_amount_input.setRange(10000, 10000000)
        self.fixed_amount_input.setValue(100000)
        self.fixed_amount_input.setPrefix("$ ")
        self.fixed_amount_input.setDecimals(0)
        self.fixed_amount_input.setVisible(False)
        # 添加 tooltip
        if 'fixed_amount' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['fixed_amount']['tooltip_lines'])
            self.fixed_amount_input.setToolTip(tooltip_text)
        sizing_form.addRow("固定金額:", self.fixed_amount_input)
        
        # 風險百分比（初始隱藏）
        self.risk_pct_input = QDoubleSpinBox()
        self.risk_pct_input.setRange(0.1, 10)
        self.risk_pct_input.setValue(2.0)
        self.risk_pct_input.setSuffix("%")
        self.risk_pct_input.setDecimals(1)
        self.risk_pct_input.setVisible(False)
        # 添加 tooltip
        if 'risk_pct' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['risk_pct']['tooltip_lines'])
            self.risk_pct_input.setToolTip(tooltip_text)
        sizing_form.addRow("風險百分比:", self.risk_pct_input)
        
        sizing_group.setLayout(sizing_form)
        config_layout.addWidget(sizing_group)
        
        # ========== 部位管理配置 ==========
        position_mgmt_group = QGroupBox("部位管理")
        position_mgmt_form = QFormLayout()
        
        # 最大持有部位數
        self.max_positions_input = QSpinBox()
        self.max_positions_input.setRange(1, 50)
        self.max_positions_input.setValue(1)
        self.max_positions_input.setSpecialValueText("無限制")
        # 添加 tooltip
        if 'max_positions' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['max_positions']['tooltip_lines'])
            self.max_positions_input.setToolTip(tooltip_text)
        position_mgmt_form.addRow("最大持有部位數:", self.max_positions_input)
        
        # 部位加權方式
        self.position_sizing_combo = QComboBox()
        self.position_sizing_combo.addItems(["等權重", "分數加權", "波動調整"])
        self.position_sizing_combo.setCurrentIndex(0)  # 預設等權重
        # 添加 tooltip
        if 'position_sizing' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['position_sizing']['tooltip_lines'])
            self.position_sizing_combo.setToolTip(tooltip_text)
        position_mgmt_form.addRow("部位加權方式:", self.position_sizing_combo)
        
        # 允許加碼
        self.allow_pyramid_checkbox = QCheckBox("允許加碼（金字塔式建倉）")
        self.allow_pyramid_checkbox.setChecked(False)
        # 添加 tooltip
        if 'allow_pyramid' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['allow_pyramid']['tooltip_lines'])
            self.allow_pyramid_checkbox.setToolTip(tooltip_text)
        position_mgmt_form.addRow(self.allow_pyramid_checkbox)
        
        # 允許重新進場
        self.allow_reentry_checkbox = QCheckBox("允許重新進場")
        self.allow_reentry_checkbox.setChecked(True)
        self.allow_reentry_checkbox.toggled.connect(self._on_allow_reentry_changed)
        # 添加 tooltip
        if 'allow_reentry' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['allow_reentry']['tooltip_lines'])
            self.allow_reentry_checkbox.setToolTip(tooltip_text)
        position_mgmt_form.addRow(self.allow_reentry_checkbox)
        
        # 重新進場冷卻天數
        self.reentry_cooldown_input = QSpinBox()
        self.reentry_cooldown_input.setRange(0, 30)
        self.reentry_cooldown_input.setValue(5)
        self.reentry_cooldown_input.setSuffix(" 天")
        # 添加 tooltip
        if 'reentry_cooldown_days' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['reentry_cooldown_days']['tooltip_lines'])
            self.reentry_cooldown_input.setToolTip(tooltip_text)
        position_mgmt_form.addRow("重新進場冷卻天數:", self.reentry_cooldown_input)
        
        position_mgmt_group.setLayout(position_mgmt_form)
        config_layout.addWidget(position_mgmt_group)
        
        # ========== 市場限制配置 ==========
        market_constraints_group = QGroupBox("市場限制")
        market_constraints_form = QFormLayout()
        
        # 漲跌停限制
        self.enable_limit_checkbox = QCheckBox("啟用漲跌停限制")
        self.enable_limit_checkbox.setChecked(True)
        # 添加 tooltip
        if 'enable_limit' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['enable_limit']['tooltip_lines'])
            self.enable_limit_checkbox.setToolTip(tooltip_text)
        market_constraints_form.addRow(self.enable_limit_checkbox)
        
        # 成交量約束
        self.enable_volume_checkbox = QCheckBox("啟用成交量約束")
        self.enable_volume_checkbox.setChecked(True)
        # 添加 tooltip
        if 'enable_volume' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['enable_volume']['tooltip_lines'])
            self.enable_volume_checkbox.setToolTip(tooltip_text)
        market_constraints_form.addRow(self.enable_volume_checkbox)
        
        # 最大參與率
        self.max_participation_input = QDoubleSpinBox()
        self.max_participation_input.setRange(0.1, 50)
        self.max_participation_input.setValue(5.0)
        self.max_participation_input.setSuffix("%")
        self.max_participation_input.setDecimals(1)
        # 添加 tooltip
        if 'max_participation' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['max_participation']['tooltip_lines'])
            self.max_participation_input.setToolTip(tooltip_text)
        market_constraints_form.addRow("最大參與率:", self.max_participation_input)
        
        market_constraints_group.setLayout(market_constraints_form)
        config_layout.addWidget(market_constraints_group)
        
        # 策略配置
        strategy_group = QGroupBox("策略配置")
        strategy_layout = QVBoxLayout()
        
        # 策略選擇下拉選單
        strategy_layout.addWidget(QLabel("策略:"))
        self.strategy_combo = QComboBox()
        self._populate_strategy_combo()
        strategy_layout.addWidget(self.strategy_combo)
        
        # 策略參數（動態顯示）
        self.params_widget = QWidget()
        self.params_layout = QFormLayout(self.params_widget)
        strategy_layout.addWidget(self.params_widget)
        
        # 策略描述
        self.strategy_desc = QLabel()
        self.strategy_desc.setStyleSheet("color: #888; font-size: 10px;")
        self.strategy_desc.setWordWrap(True)
        strategy_layout.addWidget(self.strategy_desc)
        
        # 連接策略選擇事件
        self.strategy_combo.currentTextChanged.connect(self._on_strategy_changed)
        self._on_strategy_changed()  # 初始化
        
        strategy_group.setLayout(strategy_layout)
        config_layout.addWidget(strategy_group)
        
        # ========== 參數最佳化區塊 ==========
        if self.backtest_service:
            from app_module.optimizer_service import OptimizerService
            from app_module.walkforward_service import WalkForwardService
            self.optimizer_service = OptimizerService(
                self.backtest_service,
                self.run_repository
            )
            self.walkforward_service = WalkForwardService(self.backtest_service)
        else:
            self.optimizer_service = None
            self.walkforward_service = None
        
        if self.optimizer_service:
            self.optimization_group = QGroupBox("參數最佳化")
            self.optimization_group.setCheckable(True)
            self.optimization_group.setChecked(False)
            # 連接勾選狀態變更事件，控制參數顯示位置
            self.optimization_group.toggled.connect(self._on_optimization_toggled)
            optimization_layout = QVBoxLayout()
            
            # 目標指標選擇
            objective_row = QHBoxLayout()
            objective_row.addWidget(QLabel("目標指標:"))
            self.objective_combo = QComboBox()
            self.objective_combo.addItems(["夏普比率", "年化報酬率", "CAGR-MDD權衡"])
            # 添加 tooltip
            if 'optimization_objective' in self.parameter_descriptions:
                tooltip_text = '\n'.join(self.parameter_descriptions['optimization_objective']['tooltip_lines'])
                self.objective_combo.setToolTip(tooltip_text)
            objective_row.addWidget(self.objective_combo)
            optimization_layout.addLayout(objective_row)
            
            # 參數範圍設定（動態生成）
            self.optimization_params_widget = QWidget()
            self.optimization_params_layout = QFormLayout(self.optimization_params_widget)
            optimization_layout.addWidget(self.optimization_params_widget)
            
            # 連接策略變更事件，更新參數範圍表單
            self.strategy_combo.currentTextChanged.connect(self._update_optimization_params_form)
            
            # 初始化參數表單（如果已經有策略選擇）
            # 使用 QTimer 延遲執行，確保 UI 完全初始化後再更新
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._update_optimization_params_form)
            
            # 同時在策略變更時也更新（確保同步）
            self.strategy_combo.currentTextChanged.connect(lambda: QTimer.singleShot(50, self._update_optimization_params_form))
            
            # 執行最佳化按鈕
            self.optimize_btn = QPushButton("執行參數掃描")
            self.optimize_btn.setStyleSheet("background-color: #2196F3; color: white;")
            self.optimize_btn.clicked.connect(self._execute_optimization)
            optimization_layout.addWidget(self.optimize_btn)
            
            self.optimization_group.setLayout(optimization_layout)
            config_layout.addWidget(self.optimization_group)
        
        # ========== Walk-forward 驗證區塊 ==========
        if self.walkforward_service:
            wf_group = QGroupBox("Walk-forward 驗證")
            wf_group.setCheckable(True)
            wf_group.setChecked(False)
            wf_layout = QVBoxLayout()
            
            # 驗證模式選擇
            wf_mode_row = QHBoxLayout()
            wf_mode_row.addWidget(QLabel("模式:"))
            self.wf_mode_combo = QComboBox()
            self.wf_mode_combo.addItems(["Train-Test Split", "Walk-forward"])
            # 添加 tooltip
            if 'walkforward_mode' in self.parameter_descriptions:
                tooltip_text = '\n'.join(self.parameter_descriptions['walkforward_mode']['tooltip_lines'])
                self.wf_mode_combo.setToolTip(tooltip_text)
            wf_mode_row.addWidget(self.wf_mode_combo)
            wf_layout.addLayout(wf_mode_row)
            
            # Train-Test Split 設定
            self.wf_split_widget = QWidget()
            wf_split_layout = QFormLayout(self.wf_split_widget)
            self.wf_train_ratio = QDoubleSpinBox()
            self.wf_train_ratio.setRange(0.1, 0.9)
            self.wf_train_ratio.setValue(0.7)
            self.wf_train_ratio.setSingleStep(0.1)
            self.wf_train_ratio.setDecimals(1)
            self.wf_train_ratio.setSuffix(" (訓練比例)")
            wf_split_layout.addRow("訓練/測試比例:", self.wf_train_ratio)
            wf_layout.addWidget(self.wf_split_widget)
            
            # Walk-forward 設定（初始隱藏）
            self.wf_wf_widget = QWidget()
            wf_wf_layout = QFormLayout(self.wf_wf_widget)
            self.wf_train_months = QSpinBox()
            self.wf_train_months.setRange(1, 24)
            self.wf_train_months.setValue(6)
            wf_wf_layout.addRow("訓練期（月）:", self.wf_train_months)
            
            self.wf_test_months = QSpinBox()
            self.wf_test_months.setRange(1, 12)
            self.wf_test_months.setValue(3)
            wf_wf_layout.addRow("測試期（月）:", self.wf_test_months)
            
            self.wf_step_months = QSpinBox()
            self.wf_step_months.setRange(1, 12)
            self.wf_step_months.setValue(3)
            wf_wf_layout.addRow("步進（月）:", self.wf_step_months)
            
            self.wf_wf_widget.setVisible(False)
            wf_layout.addWidget(self.wf_wf_widget)
            
            # 連接模式切換
            def on_wf_mode_changed(mode):
                if mode == "Train-Test Split":
                    self.wf_split_widget.setVisible(True)
                    self.wf_wf_widget.setVisible(False)
                else:
                    self.wf_split_widget.setVisible(False)
                    self.wf_wf_widget.setVisible(True)
            
            self.wf_mode_combo.currentTextChanged.connect(on_wf_mode_changed)
            
            # 執行 Walk-forward 按鈕
            self.wf_execute_btn = QPushButton("執行驗證")
            self.wf_execute_btn.setStyleSheet("background-color: #FF9800; color: white;")
            self.wf_execute_btn.clicked.connect(self._execute_walkforward)
            wf_layout.addWidget(self.wf_execute_btn)
            
            wf_group.setLayout(wf_layout)
            config_layout.addWidget(wf_group)
        
        # 執行按鈕
        execute_row = QHBoxLayout()
        self.execute_btn = QPushButton("執行回測")
        self.execute_btn.setMinimumHeight(40)
        self.execute_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.execute_btn.clicked.connect(self._execute_backtest)
        execute_row.addWidget(self.execute_btn)
        
        # 保存結果按鈕
        if self.run_repository:
            self.save_result_btn = QPushButton("保存結果")
            self.save_result_btn.setMaximumWidth(100)
            self.save_result_btn.setEnabled(False)  # 初始禁用
            self.save_result_btn.clicked.connect(self._save_backtest_result)
            execute_row.addWidget(self.save_result_btn)
        
        # Promote 按鈕
        if self.promotion_service:
            self.promote_btn = QPushButton("升級為策略版本")
            self.promote_btn.setMaximumWidth(120)
            self.promote_btn.setEnabled(False)  # 初始禁用
            self.promote_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
            self.promote_btn.clicked.connect(self._promote_backtest_result)
            execute_row.addWidget(self.promote_btn)
        
        config_layout.addLayout(execute_row)
        
        # 進度條和進度文字
        progress_widget = QWidget()
        progress_layout = QVBoxLayout(progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(2)
        
        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        self.progress_label.setStyleSheet("color: #666; font-size: 10pt;")
        progress_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        
        config_layout.addWidget(progress_widget)
        
        config_layout.addStretch()
        
        # 將 config_widget 放入 ScrollArea
        config_scroll.setWidget(config_widget)
        splitter.addWidget(config_scroll)
        
        # 右側：結果面板（使用 Tab）
        result_widget = QWidget()
        result_tabs = QTabWidget()
        
        # Tab 1: 結果
        result_tab = QWidget()
        result_layout = QVBoxLayout(result_tab)
        result_layout.setSpacing(10)
        result_layout.setContentsMargins(5, 5, 5, 5)
        
        # 績效摘要
        summary_group = QGroupBox("績效摘要")
        summary_layout = QVBoxLayout()
        
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(150)  # 降低最小高度，讓它更靈活
        self.summary_text.setFont(QFont("Consolas", 9))
        summary_layout.addWidget(self.summary_text)
        
        summary_group.setLayout(summary_layout)
        result_layout.addWidget(summary_group, stretch=65)  # 績效摘要佔 65% 空間（6.5:3.5）
        
        # 交易明細
        trades_group = QGroupBox("交易明細")
        trades_layout = QVBoxLayout()
        
        self.trades_table = QTableView()
        self.trades_table.setAlternatingRowColors(True)
        self.trades_table.setSelectionBehavior(QTableView.SelectRows)
        self.trades_table.setSortingEnabled(True)
        self.trades_table.horizontalHeader().setStretchLastSection(True)
        self.trades_table.setMinimumHeight(150)  # 降低最小高度，讓它更靈活
        # 設置表格可以隨窗口大小調整
        self.trades_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        font = QFont("Consolas", 9)
        self.trades_table.setFont(font)
        trades_layout.addWidget(self.trades_table)
        
        trades_group.setLayout(trades_layout)
        result_layout.addWidget(trades_group, stretch=35)  # 交易明細佔 35% 空間（6.5:3.5）
        
        result_tabs.addTab(result_tab, "結果")
        
        # Tab 2: 圖表（如果有 chart service）
        if self.chart_data_service:
            chart_tab = QWidget()
            chart_layout = QVBoxLayout(chart_tab)
            
            # Run 選擇（用於切換不同的回測結果）
            run_select_row = QHBoxLayout()
            run_select_row.addWidget(QLabel("選擇回測結果:"))
            self.chart_run_combo = QComboBox()
            self.chart_run_combo.setEditable(False)
            self.chart_run_combo.currentTextChanged.connect(self._on_chart_run_changed)
            run_select_row.addWidget(self.chart_run_combo)
            run_select_row.addStretch()
            chart_layout.addLayout(run_select_row)
            
            # 使用 Tab 組織 4 張圖表
            chart_tabs = QTabWidget()
            
            # 圖表 1: 權益曲線
            equity_chart = EquityCurveWidget()
            chart_tabs.addTab(equity_chart, "權益曲線")
            self.equity_chart = equity_chart
            
            # 圖表 2: 回撤曲線
            drawdown_chart = DrawdownCurveWidget()
            chart_tabs.addTab(drawdown_chart, "回撤曲線")
            self.drawdown_chart = drawdown_chart
            
            # 圖表 3: 交易報酬分佈
            return_hist = TradeReturnHistogramWidget()
            chart_tabs.addTab(return_hist, "報酬分佈")
            self.return_hist = return_hist
            
            # 圖表 4: 持有天數分佈
            holding_hist = HoldingDaysHistogramWidget()
            chart_tabs.addTab(holding_hist, "持有天數")
            self.holding_hist = holding_hist
            
            chart_layout.addWidget(chart_tabs)
            
            result_tabs.addTab(chart_tab, "圖表")
            
            # 初始化圖表 run 列表（會在回測完成或載入歷史時更新）
            self._update_chart_run_combo()
        
        # Tab 3: 最佳化結果（如果有 optimizer）
        if self.optimizer_service:
            optimization_result_tab = QWidget()
            optimization_result_layout = QVBoxLayout(optimization_result_tab)
            
            optimization_result_group = QGroupBox("最佳化結果")
            optimization_result_layout_inner = QVBoxLayout()
            
            self.optimization_table = QTableView()
            self.optimization_table.setAlternatingRowColors(True)
            self.optimization_table.setSelectionBehavior(QTableView.SelectRows)
            self.optimization_table.setSortingEnabled(True)
            self.optimization_table.horizontalHeader().setStretchLastSection(True)
            self.optimization_table.setMinimumHeight(200)  # 降低最小高度，讓它更靈活
            self.optimization_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.optimization_table.setFont(QFont("Consolas", 9))
            self.optimization_table.doubleClicked.connect(self._apply_optimization_params)
            optimization_result_layout_inner.addWidget(self.optimization_table)
            
            # 應用參數按鈕
            apply_btn = QPushButton("套用選中參數")
            apply_btn.clicked.connect(self._apply_optimization_params)
            optimization_result_layout_inner.addWidget(apply_btn)
            
            optimization_result_group.setLayout(optimization_result_layout_inner)
            optimization_result_layout.addWidget(optimization_result_group)
            
            result_tabs.addTab(optimization_result_tab, "最佳化")
        
        # Tab 4: 比較（如果有 repository）
        if self.run_repository:
            compare_tab = QWidget()
            compare_layout = QVBoxLayout(compare_tab)
            
            # 歷史列表
            history_group = QGroupBox("回測歷史")
            history_layout = QVBoxLayout()
            
            history_btn_row = QHBoxLayout()
            self.refresh_history_btn = QPushButton("重新整理")
            self.refresh_history_btn.clicked.connect(self._refresh_history)
            history_btn_row.addWidget(self.refresh_history_btn)
            
            self.delete_history_btn = QPushButton("刪除選中")
            self.delete_history_btn.setStyleSheet("background-color: #F44336; color: white;")
            self.delete_history_btn.clicked.connect(self._delete_history_runs)
            history_btn_row.addWidget(self.delete_history_btn)
            
            history_btn_row.addStretch()
            history_layout.addLayout(history_btn_row)
            
            self.history_list = QListWidget()
            self.history_list.setSelectionMode(QListWidget.ExtendedSelection)  # 多選
            self.history_list.itemDoubleClicked.connect(self._load_history_run)
            history_layout.addWidget(self.history_list)
            
            compare_btn = QPushButton("比較選中")
            compare_btn.clicked.connect(self._compare_runs)
            history_layout.addWidget(compare_btn)
            
            history_group.setLayout(history_layout)
            compare_layout.addWidget(history_group)
            
            # 比較結果表格
            compare_result_group = QGroupBox("比較結果")
            compare_result_layout = QVBoxLayout()
            
            self.compare_table = QTableView()
            self.compare_table.setAlternatingRowColors(True)
            self.compare_table.setSortingEnabled(True)
            self.compare_table.horizontalHeader().setStretchLastSection(True)
            self.compare_table.setSelectionBehavior(QTableView.SelectRows)
            self.compare_table.doubleClicked.connect(self._on_compare_table_double_clicked)
            compare_result_layout.addWidget(self.compare_table)
            
            compare_result_group.setLayout(compare_result_layout)
            compare_layout.addWidget(compare_result_group)
            
            result_tabs.addTab(compare_tab, "比較")
            
            # 初始化歷史列表
            self._refresh_history()
        
        # Tab 5: 批次結果（如果有 batch service）
        if self.batch_backtest_service:
            batch_result_tab = QWidget()
            batch_result_layout = QVBoxLayout(batch_result_tab)
            batch_result_layout.setSpacing(10)
            batch_result_layout.setContentsMargins(5, 5, 5, 5)
            
            # 排序選擇
            sort_row = QHBoxLayout()
            sort_row.addWidget(QLabel("排序方式:"))
            self.batch_sort_combo = QComboBox()
            self.batch_sort_combo.addItems(["CAGR-MDD", "CAGR", "Sharpe", "MDD"])
            self.batch_sort_combo.currentTextChanged.connect(self._on_batch_sort_changed)
            sort_row.addWidget(self.batch_sort_combo)
            sort_row.addStretch()
            batch_result_layout.addLayout(sort_row)
            
            # 排行榜表格
            batch_leaderboard_group = QGroupBox("排行榜")
            batch_leaderboard_layout = QVBoxLayout()
            
            self.batch_leaderboard_table = QTableView()
            self.batch_leaderboard_table.setAlternatingRowColors(True)
            self.batch_leaderboard_table.setSelectionBehavior(QTableView.SelectRows)
            self.batch_leaderboard_table.setSortingEnabled(False)  # 使用服務排序
            self.batch_leaderboard_table.horizontalHeader().setStretchLastSection(True)
            self.batch_leaderboard_table.doubleClicked.connect(self._on_batch_row_double_clicked)
            self.batch_leaderboard_table.setMinimumHeight(300)
            self.batch_leaderboard_table.setFont(QFont("Consolas", 9))
            batch_leaderboard_layout.addWidget(self.batch_leaderboard_table)
            
            batch_leaderboard_group.setLayout(batch_leaderboard_layout)
            batch_result_layout.addWidget(batch_leaderboard_group, stretch=2)
            
            # 整體統計
            batch_stats_group = QGroupBox("整體統計")
            batch_stats_layout = QVBoxLayout()
            
            self.batch_stats_text = QTextEdit()
            self.batch_stats_text.setReadOnly(True)
            self.batch_stats_text.setMaximumHeight(100)
            self.batch_stats_text.setFont(QFont("Consolas", 10))
            batch_stats_layout.addWidget(self.batch_stats_text)
            
            batch_stats_group.setLayout(batch_stats_layout)
            batch_result_layout.addWidget(batch_stats_group, stretch=1)
            
            result_tabs.addTab(batch_result_tab, "批次結果")
        
        # 調整 Tab 順序（如果有最佳化Tab）
        if self.optimizer_service:
            # 確保順序：結果、最佳化、比較
            pass
        
        result_widget_layout = QVBoxLayout(result_widget)
        result_widget_layout.addWidget(result_tabs)
        
        result_widget.setLayout(result_widget_layout)
        splitter.addWidget(result_widget)
        
        # 設置 Splitter 比例（讓右側結果區域更大，且可隨窗口調整）
        splitter.setStretchFactor(0, 1)  # 左側配置區域
        splitter.setStretchFactor(1, 3)  # 右側結果區域（更大的權重，會佔更多空間）
        # 設置初始大小比例（約 30% : 70%），但允許隨窗口調整
        # 不設置固定大小，讓它隨窗口大小自動調整
        
        main_layout.addWidget(splitter)
    
    def _execute_backtest(self):
        """執行回測（支援單檔和批次模式）"""
        # 獲取股票代號列表
        stock_codes = self._get_stock_codes()
        if not stock_codes:
            QMessageBox.warning(self, "錯誤", "請輸入股票代號或選擇選股清單")
            return
        
        # 判斷是單檔還是批次模式
        is_batch_mode = len(stock_codes) > 1
        
        if is_batch_mode and not self.batch_backtest_service:
            QMessageBox.warning(self, "錯誤", "批次回測服務未初始化")
            return
        
        start_date = self.start_date.date().toString("yyyy-MM-dd")
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        
        if QDate.fromString(start_date, "yyyy-MM-dd") > QDate.fromString(end_date, "yyyy-MM-dd"):
            QMessageBox.warning(self, "錯誤", "開始日期不能晚於結束日期")
            return
        
        capital = self.capital_input.value()
        fee_bps = self.fee_bps_input.value()
        slippage_bps = self.slippage_bps_input.value()
        
        # 執行價格
        execution_price_text = self.execution_price_combo.currentText()
        execution_price = "next_open" if "next_open" in execution_price_text else "close"
        
        # 停損停利模式
        stop_profit_mode = self.stop_profit_mode_combo.currentText()
        if stop_profit_mode == "百分比模式":
            stop_loss_pct = self.stop_loss_input.value() / 100.0 if self.stop_loss_input.value() > 0 else None
            take_profit_pct = self.take_profit_input.value() / 100.0 if self.take_profit_input.value() > 0 else None
            stop_loss_atr_mult = None
            take_profit_atr_mult = None
        else:  # ATR 倍數模式
            stop_loss_pct = None
            take_profit_pct = None
            stop_loss_atr_mult = self.stop_loss_atr_input.value() if self.stop_loss_atr_input.value() > 0 else None
            take_profit_atr_mult = self.take_profit_atr_input.value() if self.take_profit_atr_input.value() > 0 else None
        
        # 獲取選中的策略 ID
        selected_strategy_id = self.strategy_combo.currentData()
        if not selected_strategy_id:
            QMessageBox.warning(self, "錯誤", "請選擇策略")
            return
        
        # 獲取策略參數
        params = self._get_strategy_params()
        
        # 創建策略規格
        strategy_spec = StrategySpec(
            strategy_id=selected_strategy_id,
            strategy_version="1.0",
            name=self.strategy_combo.currentText(),
            description=self.strategy_desc.text(),
            regime=[],
            risk_level="medium",
            target_type="stock",
            config={
                **self._get_default_strategy_config(),
                'params': params
            }
        )
        
        # 獲取 sizing 和市場限制設定
        sizing_mode_map = {
            "全倉": "all_in",
            "固定金額": "fixed_amount",
            "風險百分比": "risk_based"
        }
        sizing_mode = sizing_mode_map.get(self.sizing_mode_combo.currentText(), "all_in")
        fixed_amount = self.fixed_amount_input.value() if sizing_mode == "fixed_amount" else None
        risk_pct = self.risk_pct_input.value() / 100.0 if sizing_mode == "risk_based" else None
        
        enable_limit = self.enable_limit_checkbox.isChecked()
        enable_volume = self.enable_volume_checkbox.isChecked()
        max_participation = self.max_participation_input.value() / 100.0
        
        # 部位管理參數
        max_positions = self.max_positions_input.value() if self.max_positions_input.value() > 0 else None
        position_sizing_map = {
            "等權重": "equal_weight",
            "分數加權": "score_weight",
            "波動調整": "volatility_adjusted"
        }
        position_sizing = position_sizing_map.get(self.position_sizing_combo.currentText(), "equal_weight")
        allow_pyramid = self.allow_pyramid_checkbox.isChecked()
        allow_reentry = self.allow_reentry_checkbox.isChecked()
        reentry_cooldown_days = self.reentry_cooldown_input.value() if allow_reentry else 0
        
        # 禁用按鈕
        self.execute_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        if is_batch_mode:
            self.progress_bar.setRange(0, len(stock_codes))
            self.progress_bar.setValue(0)
            self.progress_label.setVisible(True)
            self.progress_label.setText(f"準備開始批次回測 ({len(stock_codes)} 檔)...")
        else:
            self.progress_bar.setRange(0, 0)  # 不確定進度
            self.progress_label.setVisible(True)
            self.progress_label.setText("正在執行回測...")
        
        # 清空結果
        self.summary_text.clear()
        self.trades_table.setModel(None)
        
        if is_batch_mode:
            # 批次模式
            self._execute_batch_backtest(
                stock_codes=stock_codes,
                start_date=start_date,
                end_date=end_date,
                strategy_spec=strategy_spec,
                capital=capital,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                execution_price=execution_price,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                stop_loss_atr_mult=stop_loss_atr_mult,
                take_profit_atr_mult=take_profit_atr_mult,
                sizing_mode=sizing_mode,
                fixed_amount=fixed_amount,
                risk_pct=risk_pct,
                max_positions=max_positions,
                position_sizing=position_sizing,
                allow_pyramid=allow_pyramid,
                allow_reentry=allow_reentry,
                reentry_cooldown_days=reentry_cooldown_days,
                enable_limit=enable_limit,
                enable_volume=enable_volume,
                max_participation=max_participation
            )
        else:
            # 單檔模式
            stock_code = stock_codes[0]
            
            # 保存當前參數（用於後續保存結果）
            self.current_run_params = {
                'stock_code': stock_code,
                'start_date': start_date,
                'end_date': end_date,
                'strategy_id': selected_strategy_id,
                'strategy_params': params,
                'capital': capital,
                'fee_bps': fee_bps,
                'slippage_bps': slippage_bps,
                'execution_price': execution_price,
                'stop_loss_pct': stop_loss_pct,
                'take_profit_pct': take_profit_pct,
                'stop_loss_atr_mult': stop_loss_atr_mult,
                'take_profit_atr_mult': take_profit_atr_mult,
                'sizing_mode': sizing_mode,
                'fixed_amount': fixed_amount,
                'risk_pct': risk_pct,
                'max_positions': max_positions,
                'position_sizing': position_sizing,
                'allow_pyramid': allow_pyramid,
                'allow_reentry': allow_reentry,
                'reentry_cooldown_days': reentry_cooldown_days,
                'enable_limit': enable_limit,
                'enable_volume': enable_volume,
                'max_participation': max_participation
            }
            
            # 創建 Worker
            def backtest_task():
                return self.backtest_service.run_backtest(
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    strategy_spec=strategy_spec,
                    strategy_executor=None,
                    capital=capital,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    execution_price=execution_price,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    stop_loss_atr_mult=stop_loss_atr_mult,
                    take_profit_atr_mult=take_profit_atr_mult,
                    sizing_mode=sizing_mode,
                    fixed_amount=fixed_amount,
                    risk_pct=risk_pct,
                    max_positions=max_positions,
                    position_sizing=position_sizing,
                    allow_pyramid=allow_pyramid,
                    allow_reentry=allow_reentry,
                    reentry_cooldown_days=reentry_cooldown_days,
                    enable_limit_up_down=enable_limit,
                    enable_volume_constraint=enable_volume,
                    max_participation_rate=max_participation
                )
            
            self.worker = TaskWorker(backtest_task)
            self.worker.finished.connect(self._on_backtest_finished)
            self.worker.error.connect(self._on_backtest_error)
            self.worker.start()
    
    def _on_backtest_finished(self, report: BacktestReportDTO):
        """回測完成"""
        # ✅ 檢查日期是否被調整
        details = report.details
        if details.get('date_adjusted'):
            date_msg = details.get('date_adjusted', '')
            QMessageBox.information(
                self,
                "日期範圍調整",
                f"{date_msg}\n\n回測將使用調整後的日期範圍進行。"
            )
        
        self.execute_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 保存當前結果（用於後續保存）
        self.current_report = report
        
        # 更新圖表 run 列表（如果有）
        if hasattr(self, 'chart_run_combo'):
            self._update_chart_run_combo()
            # 自動選中當前結果（如果已保存）
            if hasattr(self, 'current_run_id') and self.current_run_id:
                index = self.chart_run_combo.findData(self.current_run_id)
                if index >= 0:
                    self.chart_run_combo.setCurrentIndex(index)
        
        # 顯示績效摘要
        summary = self._format_summary(report)
        self.summary_text.setPlainText(summary)
        
        # 顯示交易明細
        if 'trade_list' in report.details and isinstance(report.details['trade_list'], pd.DataFrame):
            trade_list = report.details['trade_list']
            if len(trade_list) > 0:
                self.trades_model = PandasTableModel(trade_list)
                self.trades_table.setModel(self.trades_model)
                self.trades_table.resizeColumnsToContents()
            else:
                self.trades_table.setModel(None)
        else:
            self.trades_table.setModel(None)
        
        # 直接從當前結果繪製圖表（不需要保存）
        self._plot_charts_from_report(report)
        
        # 啟用保存按鈕（確保有 run_repository 和 current_report）
        if hasattr(self, 'save_result_btn'):
            if self.run_repository and self.current_report and self.current_run_params:
                self.save_result_btn.setEnabled(True)
                print(f"[BacktestView] 保存按鈕已啟用 (run_repository={self.run_repository is not None}, report={self.current_report is not None}, params={self.current_run_params is not None})")
            else:
                # 如果沒有 repository，禁用按鈕並顯示提示
                self.save_result_btn.setEnabled(False)
                if not self.run_repository:
                    print("[BacktestView] 警告: run_repository 未初始化，無法保存結果")
                if not self.current_report:
                    print("[BacktestView] 警告: current_report 為空，無法保存結果")
                if not self.current_run_params:
                    print("[BacktestView] 警告: current_run_params 為空，無法保存結果")
        
        # 啟用 Promote 按鈕（需要已保存的回測結果）
        if hasattr(self, 'promote_btn'):
            if self.promotion_service and hasattr(self, 'current_run_id') and self.current_run_id:
                self.promote_btn.setEnabled(True)
            else:
                self.promote_btn.setEnabled(False)
    
    def _on_backtest_error(self, error_msg: str):
        """回測錯誤"""
        self.execute_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        QMessageBox.critical(self, "回測錯誤", f"執行回測時發生錯誤：\n\n{error_msg}")
    
    def _format_summary(self, report: BacktestReportDTO) -> str:
        """格式化績效摘要"""
        details = report.details
        
        # ✅ 顯示實際使用的日期範圍
        actual_start = details.get('start_date', '未知')
        actual_end = details.get('end_date', '未知')
        requested_start = details.get('requested_start_date', actual_start)
        requested_end = details.get('requested_end_date', actual_end)
        
        summary_lines = [
            "=== 績效摘要 ===",
            f"回測日期範圍: {actual_start} 至 {actual_end}",
        ]
        
        # 如果日期被調整，顯示提示
        if details.get('date_adjusted'):
            summary_lines.append(f"⚠️ 注意: 請求範圍 {requested_start}~{requested_end} 已調整為實際數據範圍")
        
        summary_lines.extend([
            "",
            f"總報酬率: {report.total_return * 100:.2f}%",
            f"年化報酬率 (CAGR): {report.annual_return * 100:.2f}%",
            f"夏普比率: {report.sharpe_ratio:.2f}",
            f"最大回撤: {report.max_drawdown * 100:.2f}%",
            f"勝率: {report.win_rate * 100:.2f}%",
            f"總交易次數: {report.total_trades}",
            f"期望值: {report.expectancy * 100:.2f}%",
            "",
            "=== 詳細統計 ===",
        ])
        
        if 'profit_factor' in details:
            summary_lines.append(f"獲利因子: {details['profit_factor']:.2f}")
        if 'avg_win' in details:
            summary_lines.append(f"平均獲利: ${details['avg_win']:.2f}")
        if 'avg_loss' in details:
            summary_lines.append(f"平均虧損: ${details['avg_loss']:.2f}")
        if 'largest_win' in details:
            summary_lines.append(f"最大獲利: ${details['largest_win']:.2f}")
        if 'largest_loss' in details:
            summary_lines.append(f"最大虧損: ${details['largest_loss']:.2f}")
        if 'final_equity' in details:
            summary_lines.append(f"最終權益: ${details['final_equity']:,.2f}")
        
        if 'error' in details:
            summary_lines.append(f"\n錯誤: {details['error']}")
        
        return "\n".join(summary_lines)
    
    def _init_parameter_descriptions(self):
        """初始化參數說明資料結構（集中管理）"""
        self.parameter_descriptions = {
            # 策略參數
            'buy_score': {
                'tooltip_lines': [
                    '最低進場分數門檻。',
                    '當策略分數連續達到此值以上時，才允許產生買入訊號。',
                    '系統角色：進場濾波機制，避免在分數不足時進場。'
                ]
            },
            'sell_score': {
                'tooltip_lines': [
                    '最高出場分數門檻。',
                    '當策略分數連續低於此值時，才允許產生賣出訊號。',
                    '系統角色：出場濾波機制，避免在分數仍高時過早出場。'
                ]
            },
            'buy_confirm_days': {
                'tooltip_lines': [
                    '買入確認天數。',
                    '策略分數必須連續 N 天達到 buy_score 以上，才真正產生買入訊號。',
                    '系統角色：確認機制，減少假訊號和頻繁進出場。'
                ]
            },
            'sell_confirm_days': {
                'tooltip_lines': [
                    '賣出確認天數。',
                    '策略分數必須連續 N 天低於 sell_score，才真正產生賣出訊號。',
                    '系統角色：確認機制，減少假訊號和頻繁進出場。'
                ]
            },
            'cooldown_days': {
                'tooltip_lines': [
                    '每次交易後的冷卻期。',
                    '在冷卻期間內，即使訊號再次出現，也不允許反向或重新進場。',
                    '系統角色：保護機制，避免過度交易和情緒化決策。'
                ]
            },
            # 回測執行設定
            'execution_price': {
                'tooltip_lines': [
                    '定義回測中實際成交使用的價格。',
                    'next_open：使用下一根 K 棒的開盤價（較保守，避免偷看未來）。',
                    'close：使用當根 K 棒的收盤價（較接近理想化即時成交）。',
                    '系統角色：影響回測的樂觀/保守程度，next_open 較保守。'
                ]
            },
            # 停損停利
            'stop_profit_mode': {
                'tooltip_lines': [
                    '停損停利模式選擇。',
                    '百分比模式：使用固定百分比作為停損停利門檻。',
                    'ATR 倍數模式：使用 ATR（平均真實波幅）的倍數，相對波動而非固定百分比。',
                    '系統角色：事後風控機制，不是交易訊號來源。'
                ]
            },
            'stop_loss_pct': {
                'tooltip_lines': [
                    '停損百分比。',
                    '當持倉虧損達到此百分比時，強制平倉。',
                    '系統角色：事後風控，保護資金，不產生交易訊號。',
                    '設定為 0 表示關閉停損功能。'
                ]
            },
            'take_profit_pct': {
                'tooltip_lines': [
                    '停利百分比。',
                    '當持倉獲利達到此百分比時，強制平倉。',
                    '系統角色：事後風控，鎖定獲利，不產生交易訊號。',
                    '設定為 0 表示關閉停利功能。'
                ]
            },
            'stop_loss_atr': {
                'tooltip_lines': [
                    '停損 ATR 倍數。',
                    '當持倉虧損達到 ATR × 此倍數時，強制平倉。',
                    'ATR 模式：根據股票波動性動態調整，而非固定百分比。',
                    '系統角色：事後風控，相對波動的風險控制。',
                    '設定為 0 表示關閉停損功能。'
                ]
            },
            'take_profit_atr': {
                'tooltip_lines': [
                    '停利 ATR 倍數。',
                    '當持倉獲利達到 ATR × 此倍數時，強制平倉。',
                    'ATR 模式：根據股票波動性動態調整，而非固定百分比。',
                    '系統角色：事後風控，相對波動的獲利鎖定。',
                    '設定為 0 表示關閉停利功能。'
                ]
            },
            # 部位與資金管理
            'sizing_mode': {
                'tooltip_lines': [
                    '部位大小計算模式。',
                    '全倉：使用所有可用資金。',
                    '固定金額：每次使用固定金額。',
                    '風險百分比：根據風險百分比計算部位大小。',
                    '系統角色：決定「有訊號時，下多少單」，不產生交易訊號。'
                ]
            },
            'fixed_amount': {
                'tooltip_lines': [
                    '固定金額模式下的每次交易金額。',
                    '每次進場時使用此固定金額，不受可用資金影響。',
                    '系統角色：部位大小控制，不產生交易訊號。'
                ]
            },
            'risk_pct': {
                'tooltip_lines': [
                    '風險百分比模式下的風險比例。',
                    '根據此百分比和停損距離計算每次交易的部位大小。',
                    '系統角色：部位大小控制，確保每次交易風險一致。'
                ]
            },
            'max_positions': {
                'tooltip_lines': [
                    '最多同時持有的部位數量。',
                    '當達到此數量時，即使有新訊號也不會進場。',
                    '系統角色：部位管理限制，不產生交易訊號。',
                    '設定為 1 表示無限制。'
                ]
            },
            'position_sizing': {
                'tooltip_lines': [
                    '多部位時的加權分配方式。',
                    '等權重：所有部位平均分配資金。',
                    '分數加權：根據策略分數分配資金。',
                    '波動調整：根據波動性調整分配。',
                    '系統角色：多部位資金分配，不產生交易訊號。'
                ]
            },
            'allow_pyramid': {
                'tooltip_lines': [
                    '允許金字塔式建倉（加碼）。',
                    '啟用後，在已有持倉的情況下，如果訊號再次出現，可以加碼。',
                    '系統角色：部位管理選項，不產生交易訊號。'
                ]
            },
            'allow_reentry': {
                'tooltip_lines': [
                    '允許重新進場。',
                    '啟用後，在出場後可以重新進場。',
                    '系統角色：部位管理選項，不產生交易訊號。'
                ]
            },
            'reentry_cooldown_days': {
                'tooltip_lines': [
                    '重新進場的冷卻天數。',
                    '出場後必須等待此天數，才能重新進場。',
                    '系統角色：保護機制，避免頻繁進出場。'
                ]
            },
            # 市場限制
            'enable_limit': {
                'tooltip_lines': [
                    '啟用漲跌停限制。',
                    '當股票漲停或跌停時，不允許進場或出場。',
                    '系統角色：可行性約束，可能導致「訊號存在但交易被跳過」。'
                ]
            },
            'enable_volume': {
                'tooltip_lines': [
                    '啟用成交量約束。',
                    '當成交量不足時，不允許進場或出場。',
                    '系統角色：可行性約束，模擬實際交易中的流動性限制。'
                ]
            },
            'max_participation': {
                'tooltip_lines': [
                    '最大參與率。',
                    '單次交易不得超過該股票當日成交量的此百分比。',
                    '系統角色：可行性約束，模擬大額交易對市場的影響。',
                    '可能導致「訊號存在但交易被跳過」。'
                ]
            },
            # Optimization / Walk-forward
            'optimization_objective': {
                'tooltip_lines': [
                    '參數最佳化的目標指標。',
                    '夏普比率：風險調整後報酬率。',
                    '年化報酬率：年度化總報酬率。',
                    'CAGR-MDD權衡：綜合考慮成長率和最大回撤。',
                    '系統角色：Grid Search 的優化目標，不是回測本身。'
                ]
            },
            'walkforward_mode': {
                'tooltip_lines': [
                    'Walk-forward 驗證模式。',
                    'Train-Test Split：將資料分成訓練集和測試集。',
                    'Walk-forward：滾動窗口驗證，防止過擬合。',
                    '系統角色：防止 overfitting 的驗證方式，不是回測本身。'
                ]
            },
            # 資金與成本設定
            'capital': {
                'tooltip_lines': [
                    '回測初始資金。',
                    '用於計算報酬率、最大回撤等績效指標。',
                    '系統角色：回測計算的基準資金。'
                ]
            },
            'fee_bps': {
                'tooltip_lines': [
                    '手續費（基點，1 bps = 0.01%）。',
                    '每次買賣交易時扣除的手續費。',
                    '系統角色：模擬實際交易成本，影響淨報酬率。',
                    '可設為 0 進行敏感度分析。'
                ]
            },
            'slippage_bps': {
                'tooltip_lines': [
                    '滑價（基點，1 bps = 0.01%）。',
                    '模擬實際成交價格與預期價格的偏差。',
                    '系統角色：模擬實際交易中的價格滑動，影響淨報酬率。',
                    '可設為 0 進行敏感度分析。'
                ]
            }
        }
    
    def _get_default_strategy_config(self) -> Dict[str, Any]:
        """獲取預設策略配置"""
        return {
            'technical': {
                'momentum': {
                    'enabled': True,
                    'rsi': {'enabled': True, 'period': 14},
                    'macd': {'enabled': True, 'fast': 12, 'slow': 26, 'signal': 9},
                    'kd': {'enabled': False}
                },
                'volatility': {
                    'enabled': False,
                    'bollinger': {'enabled': False, 'window': 20, 'std': 2},
                    'atr': {'enabled': True, 'period': 14}
                },
                'trend': {
                    'enabled': True,
                    'adx': {'enabled': True, 'period': 14},
                    'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                }
            },
            'patterns': {
                'selected': []
            },
            'signals': {
                'technical_indicators': ['momentum', 'trend'],
                'volume_conditions': ['increasing'],
                'weights': {'pattern': 0.30, 'technical': 0.50, 'volume': 0.20}
            },
            'filters': {},
            'regime': None
        }
    
    def _populate_strategy_combo(self):
        """填充策略下拉選單"""
        try:
            # 確保策略模組已導入（觸發註冊）
            import app_module.strategies
            
            strategies = StrategyRegistry.list_strategies()
            print(f"[BacktestView] 已註冊的策略: {list(strategies.keys())}")
            
            if not strategies:
                # 如果沒有策略，顯示提示
                self.strategy_combo.addItem("無可用策略", None)
                return
            
            for strategy_id, info in strategies.items():
                # 處理 StrategyMeta 對象或字典
                if isinstance(info, dict):
                    name = info.get('name', strategy_id)
                else:
                    # 如果是 StrategyMeta 對象，使用屬性訪問
                    name = getattr(info, 'name', strategy_id)
                self.strategy_combo.addItem(name, strategy_id)
                print(f"[BacktestView] 添加策略: {name} ({strategy_id})")
        except Exception as e:
            import traceback
            print(f"[BacktestView] 載入策略列表失敗: {e}")
            print(traceback.format_exc())
            self.strategy_combo.addItem("載入策略失敗", None)
    
    def _on_strategy_changed(self):
        """策略選擇改變"""
        strategy_id = self.strategy_combo.currentData()
        if not strategy_id:
            self.strategy_desc.setText("請選擇策略")
            self._update_params_form({})
            return
        
        try:
            # 獲取策略資訊
            strategies = StrategyRegistry.list_strategies()
            if not strategies:
                self.strategy_desc.setText("無可用策略")
                self._update_params_form({})
                return
            
            info = strategies.get(strategy_id, {})
            if not info:
                self.strategy_desc.setText(f"找不到策略 {strategy_id} 的資訊")
                self._update_params_form({})
                return
            
            # 處理 StrategyMeta 對象或字典
            if isinstance(info, dict):
                desc = info.get('description', '')
                # 統一參數讀取邏輯：優先讀取 params（baseline 格式），再讀取 default_params（StrategyMeta 格式）
                params = info.get('params', {})
                if not params:
                    params = info.get('default_params', {})
            else:
                # 如果是 StrategyMeta 對象，使用屬性訪問
                desc = getattr(info, 'description', '')
                params = getattr(info, 'default_params', {})
            
            # 如果 params 為空，嘗試從策略的 get_meta 獲取
            if not params:
                executor_cls = StrategyRegistry._registry.get(strategy_id)
                if executor_cls and hasattr(executor_cls, 'get_meta'):
                    meta = executor_cls.get_meta()
                    if isinstance(meta, dict):
                        params = meta.get('params', meta.get('default_params', {}))
                    else:
                        params = getattr(meta, 'default_params', {})
            
            # 更新描述
            self.strategy_desc.setText(desc)
            
            # 檢查參數最佳化區塊是否勾選
            # 如果勾選，參數顯示在參數最佳化區塊；如果沒有勾選，參數顯示在策略配置區塊
            if hasattr(self, 'optimization_group') and self.optimization_group.isChecked():
                # 勾選時：更新參數最佳化表單，隱藏策略配置區塊的參數
                self.params_widget.setVisible(False)
                self._update_optimization_params_form()
            else:
                # 沒有勾選時：更新策略配置表單，顯示策略配置區塊的參數
                self.params_widget.setVisible(True)
            self._update_params_form(params)
        except Exception as e:
            import traceback
            print(f"[BacktestView] 更新策略資訊失敗: {e}")
            print(traceback.format_exc())
            self.strategy_desc.setText(f"載入策略資訊失敗: {str(e)}")
            self._update_params_form({})
    
    def _update_params_form(self, params: Dict):
        """更新參數表單"""
        # 清除舊的參數控件
        while self.params_layout.count():
            child = self.params_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        self.param_widgets = {}
        
        # 添加參數控件
        for param_name, param_info in params.items():
            # 處理兩種格式：
            # 1. 字典格式：{'type': 'float', 'default': 60, 'description': '買入閾值'}（baseline 策略）
            # 2. 簡單值格式：70（暴衝/穩健策略）
            if isinstance(param_info, dict):
                param_type = param_info.get('type', 'float')
                default_value = param_info.get('default', 0)
                description = param_info.get('description', param_name)
            else:
                # 簡單值格式，推斷類型
                default_value = param_info
                if isinstance(default_value, int):
                    param_type = 'int'
                elif isinstance(default_value, float):
                    param_type = 'float'
                else:
                    param_type = 'float'  # 預設為 float
                    try:
                        default_value = float(default_value)
                    except (ValueError, TypeError):
                        default_value = 0
                # 生成描述（使用參數名稱）
                description = param_name.replace('_', ' ').title()
            
            # 創建輸入控件
            if param_type == 'int':
                widget = QSpinBox()
                widget.setRange(0, 1000)
                widget.setValue(int(default_value))
            else:  # float
                widget = QDoubleSpinBox()
                widget.setRange(0, 1000)
                widget.setValue(float(default_value))
                widget.setDecimals(2)
            
            label = QLabel(description + ":")
            self.params_layout.addRow(label, widget)
            self.param_widgets[param_name] = widget
            
            # 為策略參數添加 tooltip
            if param_name in self.parameter_descriptions:
                desc = self.parameter_descriptions[param_name]
                tooltip_lines = desc.get('tooltip_lines', [])
                if tooltip_lines:
                    tooltip_text = '\n'.join(tooltip_lines)
                    widget.setToolTip(tooltip_text)
                    label.setToolTip(tooltip_text)
    
    def _get_strategy_params(self) -> Dict:
        """獲取策略參數"""
        params = {}
        for param_name, widget in getattr(self, 'param_widgets', {}).items():
            if isinstance(widget, QSpinBox):
                params[param_name] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                params[param_name] = widget.value()
        return params
    
    # ========== 策略預設相關方法 ==========
    
    def _populate_preset_combo(self):
        """填充預設下拉選單"""
        if not self.preset_service:
            print("[BacktestView] PresetService 未初始化，無法載入預設")
            return
        
        self.preset_combo.clear()
        self.preset_combo.addItem("-- 選擇預設 --", None)
        
        try:
            presets = self.preset_service.list_presets()
            print(f"[BacktestView] 找到 {len(presets)} 個預設")
            
            if not presets:
                # 如果沒有預設，顯示提示
                self.preset_combo.addItem("（尚無預設，請先儲存）", None)
            else:
                for preset in presets:
                    name = preset.get('name', '')
                    preset_id = preset.get('preset_id', '')
                    if name and preset_id:
                        self.preset_combo.addItem(name, preset_id)
                        print(f"[BacktestView] 添加預設: {name} ({preset_id})")
        except Exception as e:
            import traceback
            print(f"[BacktestView] 載入預設列表失敗: {e}")
            print(traceback.format_exc())
            self.preset_combo.addItem("（載入失敗）", None)
    
    def _save_preset(self):
        """儲存策略預設"""
        if not self.preset_service:
            QMessageBox.warning(self, "錯誤", "預設服務未初始化")
            return
        
        # 獲取當前策略設定
        strategy_id = self.strategy_combo.currentData()
        if not strategy_id:
            QMessageBox.warning(self, "錯誤", "請先選擇策略")
            return
        
        params = self._get_strategy_params()
        
        # 彈出對話框輸入名稱
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "儲存預設", "請輸入預設名稱:")
        if not ok or not name.strip():
            return
        
        try:
            preset_id = self.preset_service.save_preset(
                name=name.strip(),
                strategy_id=strategy_id,
                params=params
            )
            QMessageBox.information(self, "成功", f"預設已儲存: {name}")
            self._populate_preset_combo()
            # 選中剛儲存的預設
            index = self.preset_combo.findData(preset_id)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"儲存失敗: {str(e)}")
    
    def _load_preset(self):
        """載入策略預設"""
        if not self.preset_service:
            return
        
        preset_id = self.preset_combo.currentData()
        if not preset_id:
            return
        
        preset = self.preset_service.load_preset(preset_id)
        if preset is None:
            QMessageBox.warning(self, "錯誤", "載入預設失敗")
            return
        
        # 載入策略
        index = self.strategy_combo.findData(preset.strategy_id)
        if index >= 0:
            self.strategy_combo.setCurrentIndex(index)
        
        # 載入參數
        for param_name, value in preset.params.items():
            if param_name in getattr(self, 'param_widgets', {}):
                widget = self.param_widgets[param_name]
                if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    widget.setValue(value)
    
    def _delete_preset(self):
        """刪除策略預設"""
        if not self.preset_service:
            return
        
        preset_id = self.preset_combo.currentData()
        if not preset_id:
            QMessageBox.warning(self, "錯誤", "請選擇要刪除的預設")
            return
        
        reply = QMessageBox.question(
            self, "確認刪除", "確定要刪除此預設嗎？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.preset_service.delete_preset(preset_id):
                QMessageBox.information(self, "成功", "預設已刪除")
                self._populate_preset_combo()
            else:
                QMessageBox.warning(self, "錯誤", "刪除失敗")
    
    # ========== 選股清單相關方法 ==========
    
    def _populate_watchlist_combo(self):
        """填充選股清單下拉選單"""
        self.watchlist_combo.clear()
        self.watchlist_combo.addItem("-- 選擇清單 --", None)
        
        # 先加入跨 Tab 共用的觀察清單（如果可用）
        if self.watchlist_service:
            try:
                default_watchlist = self.watchlist_service.get_default_watchlist()
                if default_watchlist and len(default_watchlist.items) > 0:
                    display_name = f"📋 {default_watchlist.name} ({len(default_watchlist.items)}檔)"
                    self.watchlist_combo.addItem(display_name, "watchlist_default")
            except:
                pass
        
        # 再加入 Backtest 專用的選股清單（UniverseService）
        if self.universe_service:
            watchlists = self.universe_service.list_watchlists()
            for watchlist in watchlists:
                name = watchlist.get('name', '')
                count = watchlist.get('count', 0)
                watchlist_id = watchlist.get('watchlist_id', '')
                display_name = f"{name} ({count}檔)"
                self.watchlist_combo.addItem(display_name, watchlist_id)
    
    def _on_stock_mode_changed(self, mode: str):
        """股票模式切換"""
        if mode == "單一股票":
            self.stock_code_input.setVisible(True)
            self.watchlist_widget.setVisible(False)
        else:  # 選股清單
            self.stock_code_input.setVisible(False)
            self.watchlist_widget.setVisible(True)
    
    def _manage_watchlists(self):
        """管理選股清單"""
        if not self.universe_service:
            QMessageBox.warning(self, "錯誤", "選股清單服務未初始化")
            return
        
        # 創建管理對話框
        dialog = QDialog(self)
        dialog.setWindowTitle("管理選股清單")
        dialog.setMinimumSize(500, 400)
        dialog_layout = QVBoxLayout(dialog)
        
        # 清單列表
        list_group = QGroupBox("選股清單")
        list_layout = QVBoxLayout()
        
        self.watchlist_manage_list = QListWidget()
        self._refresh_watchlist_manage_list()
        list_layout.addWidget(self.watchlist_manage_list)
        
        # 按鈕行
        btn_row = QHBoxLayout()
        
        create_btn = QPushButton("新增")
        create_btn.clicked.connect(lambda: self._create_watchlist(dialog))
        btn_row.addWidget(create_btn)
        
        edit_btn = QPushButton("編輯")
        edit_btn.clicked.connect(lambda: self._edit_watchlist(dialog))
        btn_row.addWidget(edit_btn)
        
        delete_btn = QPushButton("刪除")
        delete_btn.clicked.connect(lambda: self._delete_watchlist(dialog))
        btn_row.addWidget(delete_btn)
        
        btn_row.addStretch()
        list_layout.addLayout(btn_row)
        
        list_group.setLayout(list_layout)
        dialog_layout.addWidget(list_group)
        
        # 關閉按鈕
        close_btn = QPushButton("關閉")
        close_btn.clicked.connect(dialog.accept)
        dialog_layout.addWidget(close_btn)
        
        dialog.exec()
        
        # 刷新下拉選單
        self._populate_watchlist_combo()
    
    def _refresh_watchlist_manage_list(self):
        """刷新清單管理列表"""
        if not hasattr(self, 'watchlist_manage_list'):
            return
        
        self.watchlist_manage_list.clear()
        watchlists = self.universe_service.list_watchlists()
        for watchlist in watchlists:
            name = watchlist.get('name', '')
            count = watchlist.get('count', 0)
            watchlist_id = watchlist.get('watchlist_id', '')
            display_text = f"{name} ({count}檔)"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, watchlist_id)
            self.watchlist_manage_list.addItem(item)
    
    def _create_watchlist(self, parent_dialog):
        """創建新清單"""
        dialog = QDialog(parent_dialog)
        dialog.setWindowTitle("新增選股清單")
        dialog_layout = QVBoxLayout(dialog)
        
        dialog_layout.addWidget(QLabel("清單名稱:"))
        name_input = QLineEdit()
        dialog_layout.addWidget(name_input)
        
        dialog_layout.addWidget(QLabel("股票代號（每行一個或逗號分隔）:"))
        codes_input = QTextEdit()
        codes_input.setMinimumHeight(200)
        dialog_layout.addWidget(codes_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            name = name_input.text().strip()
            if not name:
                QMessageBox.warning(parent_dialog, "錯誤", "請輸入清單名稱")
                return
            
            # 解析股票代號
            codes_text = codes_input.toPlainText().strip()
            codes = []
            for line in codes_text.split('\n'):
                line = line.strip()
                if ',' in line:
                    codes.extend([c.strip() for c in line.split(',') if c.strip()])
                elif line:
                    codes.append(line)
            
            if not codes:
                QMessageBox.warning(parent_dialog, "錯誤", "請輸入至少一個股票代號")
                return
            
            try:
                self.universe_service.save_watchlist(
                    name=name,
                    codes=codes
                )
                QMessageBox.information(parent_dialog, "成功", f"清單已創建: {name}")
                self._refresh_watchlist_manage_list()
            except Exception as e:
                QMessageBox.critical(parent_dialog, "錯誤", f"創建失敗: {str(e)}")
    
    def _edit_watchlist(self, parent_dialog):
        """編輯清單"""
        selected_items = self.watchlist_manage_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(parent_dialog, "錯誤", "請選擇要編輯的清單")
            return
        
        watchlist_id = selected_items[0].data(Qt.UserRole)
        watchlist = self.universe_service.load_watchlist(watchlist_id)
        if not watchlist:
            QMessageBox.warning(parent_dialog, "錯誤", "載入清單失敗")
            return
        
        dialog = QDialog(parent_dialog)
        dialog.setWindowTitle("編輯選股清單")
        dialog_layout = QVBoxLayout(dialog)
        
        dialog_layout.addWidget(QLabel("清單名稱:"))
        name_input = QLineEdit(watchlist.name)
        dialog_layout.addWidget(name_input)
        
        dialog_layout.addWidget(QLabel("股票代號（每行一個或逗號分隔）:"))
        codes_input = QTextEdit('\n'.join(watchlist.codes))
        codes_input.setMinimumHeight(200)
        dialog_layout.addWidget(codes_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            name = name_input.text().strip()
            if not name:
                QMessageBox.warning(parent_dialog, "錯誤", "請輸入清單名稱")
                return
            
            # 解析股票代號
            codes_text = codes_input.toPlainText().strip()
            codes = []
            for line in codes_text.split('\n'):
                line = line.strip()
                if ',' in line:
                    codes.extend([c.strip() for c in line.split(',') if c.strip()])
                elif line:
                    codes.append(line)
            
            if not codes:
                QMessageBox.warning(parent_dialog, "錯誤", "請輸入至少一個股票代號")
                return
            
            try:
                self.universe_service.save_watchlist(
                    name=name,
                    codes=codes,
                    watchlist_id=watchlist_id  # 更新現有清單
                )
                QMessageBox.information(parent_dialog, "成功", f"清單已更新: {name}")
                self._refresh_watchlist_manage_list()
            except Exception as e:
                QMessageBox.critical(parent_dialog, "錯誤", f"更新失敗: {str(e)}")
    
    def _delete_watchlist(self, parent_dialog):
        """刪除清單"""
        selected_items = self.watchlist_manage_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(parent_dialog, "錯誤", "請選擇要刪除的清單")
            return
        
        watchlist_id = selected_items[0].data(Qt.UserRole)
        item_text = selected_items[0].text()
        
        reply = QMessageBox.question(
            parent_dialog, "確認刪除", f"確定要刪除清單「{item_text}」嗎？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                if self.universe_service.delete_watchlist(watchlist_id):
                    QMessageBox.information(parent_dialog, "成功", "清單已刪除")
                    self._refresh_watchlist_manage_list()
                else:
                    QMessageBox.warning(parent_dialog, "錯誤", "刪除失敗")
            except Exception as e:
                QMessageBox.critical(parent_dialog, "錯誤", f"刪除失敗: {str(e)}")
    
    def load_from_recommendation(self, config: Dict[str, Any]):
        """從推薦結果載入回測配置（Phase 3.3：一鍵送回測）
        
        Args:
            config: 回測配置（包含 stock_list, profile_id, strategy_config, regime 等）
        """
        try:
            stock_list = config.get('stock_list', [])
            if not stock_list:
                QMessageBox.warning(self, "錯誤", "股票清單為空")
                return
            
            # 切換到選股清單模式
            self.stock_mode_combo.setCurrentText("選股清單")
            
            # 創建臨時選股清單（如果 universe_service 可用）
            if self.universe_service:
                profile_name = config.get('profile_name', '推薦結果')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                watchlist_name = f"{profile_name}_{timestamp}"
                watchlist_id = self.universe_service.save_watchlist(
                    name=watchlist_name,
                    codes=stock_list,
                    source="recommendation",
                    description=f"來自推薦分析：Profile={config.get('profile_id', 'N/A')}, Regime={config.get('regime', 'N/A')}"
                )
                
                # 選擇剛創建的清單
                self._populate_watchlist_combo()
                index = self.watchlist_combo.findData(watchlist_id)
                if index >= 0:
                    self.watchlist_combo.setCurrentIndex(index)
            
            # 設置執行價格（根據 Profile 風險等級）
            profile_id = config.get('profile_id', '')
            if profile_id == 'momentum':
                # 暴衝策略：使用 next_open（更激進）
                self.execution_price_combo.setCurrentIndex(0)
            else:
                # 穩健/長期策略：使用 close（更保守）
                self.execution_price_combo.setCurrentIndex(1)
            
            # 設置日期範圍（預設最近 6 個月）
            end_date = QDate.currentDate()
            start_date = end_date.addMonths(-6)
            self.start_date.setDate(start_date)
            self.end_date.setDate(end_date)
            
            QMessageBox.information(
                self,
                "載入成功",
                f"已載入 {len(stock_list)} 檔股票到回測配置\n\n"
                f"請檢查並調整回測參數後執行回測。"
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self,
                "錯誤",
                f"載入推薦結果失敗：\n{str(e)}\n\n{traceback.format_exc()}"
            )
    
    def _get_stock_codes(self) -> List[str]:
        """獲取要回測的股票代號列表"""
        mode = self.stock_mode_combo.currentText()
        
        if mode == "單一股票":
            code = self.stock_code_input.text().strip()
            return [code] if code else []
        else:  # 選股清單
            watchlist_id = self.watchlist_combo.currentData()
            if not watchlist_id:
                return []
            
            # 檢查是否為跨 Tab 共用的觀察清單
            if watchlist_id == "watchlist_default" and self.watchlist_service:
                return self.watchlist_service.get_stock_codes()
            
            # 否則使用 Backtest 專用的選股清單
            if not self.universe_service:
                return []
            
            watchlist = self.universe_service.load_watchlist(watchlist_id)
            if watchlist:
                return watchlist.codes
            return []
    
    # ========== 回測結果保存相關方法 ==========
    
    def _save_backtest_result(self):
        """保存回測結果"""
        if not self.run_repository or not self.current_report:
            QMessageBox.warning(self, "錯誤", "沒有可保存的結果")
            return
        
        # 生成預設名稱
        stock_code = self.current_run_params.get('stock_code', 'UNKNOWN')
        strategy_id = self.current_run_params.get('strategy_id', 'UNKNOWN')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{stock_code}_{strategy_id}_{timestamp}"
        
        # 彈出對話框輸入名稱和備註
        dialog = QDialog(self)
        dialog.setWindowTitle("保存回測結果")
        dialog_layout = QVBoxLayout(dialog)
        
        dialog_layout.addWidget(QLabel("執行名稱:"))
        name_input = QLineEdit(default_name)
        dialog_layout.addWidget(name_input)
        
        dialog_layout.addWidget(QLabel("備註（可選）:"))
        notes_input = QTextEditDialog()
        notes_input.setMaximumHeight(100)
        dialog_layout.addWidget(notes_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            run_name = name_input.text().strip() or default_name
            notes = notes_input.toPlainText().strip()
            
            try:
                run_id = self.run_repository.save_run(
                    run_name=run_name,
                    stock_code=self.current_run_params.get('stock_code', ''),
                    start_date=self.current_run_params.get('start_date', ''),
                    end_date=self.current_run_params.get('end_date', ''),
                    strategy_id=self.current_run_params.get('strategy_id', ''),
                    strategy_params=self.current_run_params.get('strategy_params', {}),
                    capital=self.current_run_params.get('capital', 1000000),
                    fee_bps=self.current_run_params.get('fee_bps', 14.25),
                    slippage_bps=self.current_run_params.get('slippage_bps', 5.0),
                    stop_loss_pct=self.current_run_params.get('stop_loss_pct'),
                    take_profit_pct=self.current_run_params.get('take_profit_pct'),
                    report=self.current_report,
                    notes=notes
                )
                QMessageBox.information(self, "成功", f"結果已保存: {run_name}")
                self.current_run_id = run_id  # 保存當前 run_id
                self._refresh_history()
                self._update_chart_run_combo()
                # 自動選中剛保存的結果
                index = self.chart_run_combo.findData(run_id)
                if index >= 0:
                    self.chart_run_combo.setCurrentIndex(index)
                # 啟用 Promote 按鈕
                if hasattr(self, 'promote_btn'):
                    self.promote_btn.setEnabled(True)
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"保存失敗: {str(e)}")
    
    def _promote_backtest_result(self):
        """將回測結果升級為策略版本"""
        if not self.promotion_service or not hasattr(self, 'current_run_id') or not self.current_run_id:
            QMessageBox.warning(self, "錯誤", "沒有可升級的回測結果")
            return
        
        run_id = self.current_run_id
        
        # 1. 檢查升級條件
        criteria = self.promotion_service.check_promotion_criteria(run_id)
        
        # 顯示檢查結果對話框
        dialog = QDialog(self)
        dialog.setWindowTitle("升級條件檢查")
        dialog_layout = QVBoxLayout(dialog)
        
        dialog_layout.addWidget(QLabel("升級條件檢查結果:"))
        result_text = QTextEditDialog()
        result_text.setReadOnly(True)
        result_text.setMaximumHeight(200)
        
        if criteria.passed:
            result_text.setPlainText("✓ 通過升級條件\n\n" + "\n".join(criteria.reasons))
        else:
            result_text.setPlainText("✗ 未通過升級條件\n\n" + "\n".join(criteria.reasons))
        
        dialog_layout.addWidget(result_text)
        
        if not criteria.passed:
            # 如果未通過，只顯示確定按鈕
            buttons = QDialogButtonBox(QDialogButtonBox.Ok)
            buttons.accepted.connect(dialog.accept)
            dialog_layout.addWidget(buttons)
            dialog.exec()
            return
        
        # 2. 如果通過，顯示升級對話框
        dialog_layout.addWidget(QLabel("\n版本名稱（可選）:"))
        name_input = QLineEdit()
        name_input.setPlaceholderText("留空則自動生成")
        dialog_layout.addWidget(name_input)
        
        dialog_layout.addWidget(QLabel("備註（可選）:"))
        notes_input = QTextEditDialog()
        notes_input.setMaximumHeight(100)
        dialog_layout.addWidget(notes_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            version_name = name_input.text().strip() or None
            notes = notes_input.toPlainText().strip() or None
            
            try:
                version_id = self.promotion_service.promote_to_strategy_version(
                    run_id=run_id,
                    version_name=version_name,
                    notes=notes
                )
                
                if version_id:
                    QMessageBox.information(
                        self,
                        "成功",
                        f"回測結果已升級為策略版本\n\n版本 ID: {version_id}\n回測 ID: {run_id}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "失敗",
                        "升級失敗，請檢查升級條件"
                    )
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"升級失敗: {str(e)}")
    
    def _refresh_history(self):
        """重新整理歷史列表"""
        if not self.run_repository:
            return
        
        self.history_list.clear()
        runs = self.run_repository.list_runs(limit=100)
        
        for run in runs:
            run_name = run.get('run_name', '')
            stock_code = run.get('stock_code', '')
            strategy_id = run.get('strategy_id', '')
            created_at = run.get('created_at', '')
            
            # 格式化日期
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d %H:%M')
            except:
                date_str = created_at[:16] if len(created_at) > 16 else created_at
            
            display_text = f"{run_name} | {stock_code} | {strategy_id} | {date_str}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, run.get('run_id'))
            self.history_list.addItem(item)
    
    def _load_history_run(self, item: QListWidgetItem):
        """載入歷史回測結果"""
        if not self.run_repository:
            return
        
        run_id = item.data(Qt.UserRole)
        if not run_id:
            return
        
        run_data = self.run_repository.load_run_data(run_id)
        if not run_data:
            QMessageBox.warning(self, "錯誤", "載入失敗")
            return
        
        # 顯示摘要
        summary_lines = [
            f"執行名稱: {run_data.get('run_name', '')}",
            f"股票代號: {run_data.get('stock_code', '')}",
            f"日期範圍: {run_data.get('start_date', '')} ~ {run_data.get('end_date', '')}",
            f"策略: {run_data.get('strategy_id', '')}",
            "",
            "=== 績效摘要 ===",
            f"總報酬率: {run_data.get('total_return', 0) * 100:.2f}%",
            f"年化報酬率: {run_data.get('annual_return', 0) * 100:.2f}%",
            f"夏普比率: {run_data.get('sharpe_ratio', 0):.2f}",
            f"最大回撤: {run_data.get('max_drawdown', 0) * 100:.2f}%",
            f"勝率: {run_data.get('win_rate', 0) * 100:.2f}%",
            f"總交易次數: {run_data.get('total_trades', 0)}",
        ]
        
        self.summary_text.setPlainText("\n".join(summary_lines))
        
        # 顯示交易明細
        if 'trade_list' in run_data and isinstance(run_data['trade_list'], pd.DataFrame):
            trade_list = run_data['trade_list']
            if len(trade_list) > 0:
                self.trades_model = PandasTableModel(trade_list)
                self.trades_table.setModel(self.trades_model)
                self.trades_table.resizeColumnsToContents()
            else:
                self.trades_table.setModel(None)
        else:
            self.trades_table.setModel(None)
    
    def _delete_history_runs(self):
        """刪除選中的回測結果"""
        if not self.run_repository:
            QMessageBox.warning(self, "錯誤", "回測結果儲存庫未初始化")
            return
        
        selected_items = self.history_list.selectedItems()
        if len(selected_items) == 0:
            QMessageBox.warning(self, "提示", "請選擇要刪除的回測結果")
            return
        
        # 確認刪除
        if len(selected_items) == 1:
            item_text = selected_items[0].text()
            reply = QMessageBox.question(
                self, "確認刪除", 
                f"確定要刪除此回測結果嗎？\n\n{item_text}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                self, "確認刪除", 
                f"確定要刪除選中的 {len(selected_items)} 個回測結果嗎？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        
        if reply != QMessageBox.Yes:
            return
        
        # 執行刪除
        deleted_count = 0
        failed_count = 0
        failed_names = []
        
        for item in selected_items:
            run_id = item.data(Qt.UserRole)
            if not run_id:
                continue
            
            # 獲取名稱用於錯誤提示
            run = self.run_repository.load_run(run_id)
            run_name = run.run_name if run else run_id
            
            try:
                if self.run_repository.delete_run(run_id):
                    deleted_count += 1
                else:
                    failed_count += 1
                    failed_names.append(run_name)
            except Exception as e:
                failed_count += 1
                failed_names.append(run_name)
                print(f"[BacktestView] 刪除回測結果失敗 {run_id}: {e}")
        
        # 顯示結果
        if failed_count == 0:
            if deleted_count == 1:
                QMessageBox.information(self, "成功", "回測結果已刪除")
            else:
                QMessageBox.information(self, "成功", f"已刪除 {deleted_count} 個回測結果")
        else:
            msg = f"成功刪除 {deleted_count} 個結果"
            if failed_count > 0:
                msg += f"\n失敗 {failed_count} 個結果"
                if len(failed_names) <= 5:
                    msg += f":\n" + "\n".join(failed_names)
                else:
                    msg += f":\n" + "\n".join(failed_names[:5]) + f"\n... 還有 {len(failed_names) - 5} 個"
            QMessageBox.warning(self, "部分成功", msg)
        
        # 刷新列表和圖表下拉選單
        self._refresh_history()
        if hasattr(self, 'chart_run_combo'):
            self._update_chart_run_combo()
    
    def _compare_runs(self):
        """比較選中的回測結果"""
        if not self.run_repository:
            return
        
        selected_items = self.history_list.selectedItems()
        if len(selected_items) < 2:
            QMessageBox.warning(self, "錯誤", "請至少選擇2個結果進行比較")
            return
        
        runs_data = []
        for item in selected_items:
            run_id = item.data(Qt.UserRole)
            run = self.run_repository.load_run(run_id)
            if run:
                runs_data.append(run)
        
        if len(runs_data) < 2:
            QMessageBox.warning(self, "錯誤", "無法載入足夠的結果")
            return
        
        # 建立比較表格（保存 run_id 用於雙擊載入）
        compare_data = []
        self.compare_runs_data = []  # 保存原始 run 數據，用於雙擊時獲取 run_id
        
        for item in selected_items:
            run_id = item.data(Qt.UserRole)
            run = self.run_repository.load_run(run_id)
            if run:
                self.compare_runs_data.append({
                    'run_id': run_id,
                    'run': run
                })
            compare_data.append({
                '執行名稱': run.run_name,
                '股票代號': run.stock_code,
                '策略': run.strategy_id,
                '總報酬率%': run.total_return * 100,
                '年化報酬率%': run.annual_return * 100,
                '夏普比率': run.sharpe_ratio,
                '最大回撤%': run.max_drawdown * 100,
                '勝率%': run.win_rate * 100,
                '交易次數': run.total_trades,
                '期望值%': run.expectancy * 100,
                '獲利因子': run.profit_factor,
            })
        
        compare_df = pd.DataFrame(compare_data)
        self.compare_model = PandasTableModel(compare_df)
        self.compare_table.setModel(self.compare_model)
        self.compare_table.resizeColumnsToContents()
    
    def _on_compare_table_double_clicked(self, index):
        """比較表格雙擊事件：載入該回測結果的詳細信息"""
        if not hasattr(self, 'compare_model') or not self.compare_model:
            return
        
        if not hasattr(self, 'compare_runs_data') or not self.compare_runs_data:
            return
        
        # 獲取選中的行
        row = index.row()
        if row >= len(self.compare_runs_data):
            return
        
        # 獲取對應的 run_id
        run_id = self.compare_runs_data[row]['run_id']
        
        # 載入並切換到結果 Tab
        self._load_run_and_switch_tab(run_id)
    
    # ========== Sizing 模式相關方法 ==========
    
    def _on_stop_profit_mode_changed(self, mode: str):
        """停損停利模式切換"""
        if mode == "百分比模式":
            # 顯示百分比輸入框，隱藏 ATR 輸入框
            self.stop_loss_input.setVisible(True)
            self.take_profit_input.setVisible(True)
            self.stop_loss_atr_input.setVisible(False)
            self.take_profit_atr_input.setVisible(False)
        else:  # ATR 倍數模式
            # 隱藏百分比輸入框，顯示 ATR 輸入框
            self.stop_loss_input.setVisible(False)
            self.take_profit_input.setVisible(False)
            self.stop_loss_atr_input.setVisible(True)
            self.take_profit_atr_input.setVisible(True)
    
    def _on_allow_reentry_changed(self, checked: bool):
        """允許重新進場切換"""
        # 如果允許重新進場，啟用冷卻天數輸入框
        self.reentry_cooldown_input.setEnabled(checked)
    
    def _on_sizing_mode_changed(self, mode: str):
        """Sizing 模式切換"""
        if mode == "固定金額":
            self.fixed_amount_input.setVisible(True)
            self.risk_pct_input.setVisible(False)
        elif mode == "風險百分比":
            self.fixed_amount_input.setVisible(False)
            self.risk_pct_input.setVisible(True)
        else:  # 全倉
            self.fixed_amount_input.setVisible(False)
            self.risk_pct_input.setVisible(False)
    
    # ========== 參數最佳化相關方法 ==========
    
    def _on_optimization_toggled(self, checked: bool):
        """參數最佳化區塊勾選狀態變更"""
        # 根據勾選狀態切換參數顯示位置
        if checked:
            # 勾選時：隱藏策略配置區塊的參數，顯示參數最佳化區塊的參數
            self.params_widget.setVisible(False)
            # 更新參數最佳化表單
            self._update_optimization_params_form()
        else:
            # 取消勾選時：顯示策略配置區塊的參數，隱藏參數最佳化區塊的參數
            self.params_widget.setVisible(True)
            # 清空參數最佳化表單
            if hasattr(self, 'optimization_params_layout'):
                while self.optimization_params_layout.count():
                    child = self.optimization_params_layout.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
                self.optimization_param_widgets = {}
            # 重新更新策略配置區塊的參數（確保顯示最新參數）
            self._on_strategy_changed()
    
    def _update_optimization_params_form(self):
        """更新參數最佳化表單（當策略改變時）"""
        if not hasattr(self, 'optimization_params_layout'):
            return
        
        # 檢查參數最佳化區塊是否勾選
        # 如果沒有勾選，不更新參數最佳化表單
        if hasattr(self, 'optimization_group') and not self.optimization_group.isChecked():
            # 如果沒有勾選，清空表單但不顯示提示
            while self.optimization_params_layout.count():
                child = self.optimization_params_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.optimization_param_widgets = {}
            return
        
        # 清除舊的參數控件
        while self.optimization_params_layout.count():
            child = self.optimization_params_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        self.optimization_param_widgets = {}
        
        # 獲取當前策略的參數
        strategy_id = self.strategy_combo.currentData()
        if not strategy_id:
            # 如果沒有選擇策略，顯示提示標籤
            hint_label = QLabel("請先選擇策略，參數範圍設定將自動顯示")
            hint_label.setStyleSheet("color: #888; font-style: italic;")
            self.optimization_params_layout.addRow(hint_label)
            return
        
        try:
            strategies = StrategyRegistry.list_strategies()
            info = strategies.get(strategy_id, {})
            
            # 處理 StrategyMeta 對象或字典（與 _on_strategy_changed 使用相同的邏輯）
            params = {}
            if isinstance(info, dict):
                # 統一參數讀取邏輯：優先讀取 params（baseline 格式），再讀取 default_params（StrategyMeta 格式）
                params = info.get('params', {})
                if not params:
                    params = info.get('default_params', {})
            else:
                # StrategyMeta 對象
                params = getattr(info, 'default_params', {})
            
            # 如果 params 為空，嘗試從策略的 get_meta 獲取（直接從執行器類別獲取）
            if not params:
                executor_cls = StrategyRegistry._registry.get(strategy_id)
                if executor_cls and hasattr(executor_cls, 'get_meta'):
                    meta = executor_cls.get_meta()
                    if isinstance(meta, dict):
                        # baseline 策略格式：params 在 'params' 鍵下
                        params = meta.get('params', {})
                        # 如果還是沒有，嘗試 default_params
                        if not params:
                            params = meta.get('default_params', {})
                    else:
                        # StrategyMeta 對象格式
                        params = getattr(meta, 'default_params', {})
            
            # 調試：確保參數被正確讀取
            if params:
                print(f"[BacktestView] 參數最佳化：成功讀取到 {len(params)} 個參數: {list(params.keys())}")
            
            # 調試：打印參數信息（僅在開發時使用）
            if not params:
                print(f"[BacktestView] 警告：策略 {strategy_id} 沒有找到參數定義")
                print(f"[BacktestView] info 類型: {type(info)}")
                if isinstance(info, dict):
                    print(f"[BacktestView] info keys: {list(info.keys())}")
                    print(f"[BacktestView] info['params']: {info.get('params', 'NOT FOUND')}")
                    print(f"[BacktestView] info['default_params']: {info.get('default_params', 'NOT FOUND')}")
                # 嘗試直接從執行器獲取
                executor_cls = StrategyRegistry._registry.get(strategy_id)
                if executor_cls:
                    print(f"[BacktestView] 嘗試直接從執行器獲取...")
                    if hasattr(executor_cls, 'get_meta'):
                        meta = executor_cls.get_meta()
                        print(f"[BacktestView] get_meta() 返回類型: {type(meta)}")
                        if isinstance(meta, dict):
                            print(f"[BacktestView] meta keys: {list(meta.keys())}")
                            print(f"[BacktestView] meta['params']: {meta.get('params', 'NOT FOUND')}")
                        elif hasattr(meta, 'default_params'):
                            print(f"[BacktestView] meta.default_params: {meta.default_params}")
            
            # 調試：確保參數被正確讀取
            if params:
                print(f"[BacktestView] 成功讀取到 {len(params)} 個參數: {list(params.keys())}")
            
            # 為每個參數創建範圍設定控件
            print(f"[BacktestView] 開始創建參數控件，共 {len(params)} 個參數")
            for param_name, param_info in params.items():
                print(f"[BacktestView] 處理參數: {param_name}, 類型: {type(param_info)}, 值: {param_info}")
                # 處理兩種格式：
                # 1. 字典格式：{'type': 'float', 'default': 60, 'description': '買入閾值'}
                # 2. 簡單值格式：70（需要推斷類型）
                if isinstance(param_info, dict):
                    param_type = param_info.get('type', 'float')
                    default_value = param_info.get('default', 0)
                    description = param_info.get('description', param_name)
                else:
                    # 簡單值格式，推斷類型
                    default_value = param_info
                    if isinstance(default_value, int):
                        param_type = 'int'
                    elif isinstance(default_value, float):
                        param_type = 'float'
                    else:
                        param_type = 'float'  # 預設為 float
                        try:
                            default_value = float(default_value)
                        except (ValueError, TypeError):
                            default_value = 0
                    # 生成描述（使用參數名稱）
                    description = param_name.replace('_', ' ').title()
                
                # 創建範圍設定行（無論是字典格式還是簡單值格式都需要）
                range_row = QHBoxLayout()
                
                # 參數名稱標籤
                label = QLabel(description + ":")
                label.setMinimumWidth(120)
                range_row.addWidget(label)
                
                # 模式選擇（固定值/範圍）
                mode_combo = QComboBox()
                mode_combo.addItems(["固定值", "範圍"])
                mode_combo.setCurrentText("固定值")
                mode_combo.setMaximumWidth(80)
                range_row.addWidget(mode_combo)
                
                # 固定值輸入
                if param_type == 'int':
                    fixed_widget = QSpinBox()
                    fixed_widget.setRange(0, 1000)
                    fixed_widget.setValue(int(default_value))
                else:
                    fixed_widget = QDoubleSpinBox()
                    fixed_widget.setRange(0, 1000)
                    fixed_widget.setValue(float(default_value))
                    fixed_widget.setDecimals(2)
                
                # 範圍輸入（初始隱藏）
                range_widget = QWidget()
                range_layout = QHBoxLayout(range_widget)
                range_layout.setContentsMargins(0, 0, 0, 0)
                
                if param_type == 'int':
                    min_widget = QSpinBox()
                    max_widget = QSpinBox()
                    step_widget = QSpinBox()
                    min_widget.setRange(0, 1000)
                    max_widget.setRange(0, 1000)
                    step_widget.setRange(1, 100)
                    min_widget.setValue(int(default_value) - 10)
                    max_widget.setValue(int(default_value) + 10)
                    step_widget.setValue(1)
                else:
                    min_widget = QDoubleSpinBox()
                    max_widget = QDoubleSpinBox()
                    step_widget = QDoubleSpinBox()
                    min_widget.setRange(0, 1000)
                    max_widget.setRange(0, 1000)
                    step_widget.setRange(0.1, 100)
                    min_widget.setDecimals(2)
                    max_widget.setDecimals(2)
                    step_widget.setDecimals(2)
                    min_widget.setValue(float(default_value) - 10)
                    max_widget.setValue(float(default_value) + 10)
                    step_widget.setValue(1.0)
                
                range_layout.addWidget(QLabel("最小:"))
                range_layout.addWidget(min_widget)
                range_layout.addWidget(QLabel("最大:"))
                range_layout.addWidget(max_widget)
                range_layout.addWidget(QLabel("步長:"))
                range_layout.addWidget(step_widget)
                
                # 使用容器 widget 來切換顯示（避免布局問題）
                container_widget = QWidget()
                container_layout = QHBoxLayout(container_widget)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.setSpacing(5)
                
                # 將兩個 widget 都添加到容器中
                container_layout.addWidget(fixed_widget)
                container_layout.addWidget(range_widget)
                
                # 切換顯示（使用 lambda 確保閉包正確綁定）
                def make_mode_changed_handler(fixed, range_w, container):
                    def handler(mode):
                        if mode == "固定值":
                            fixed.show()
                            range_w.hide()
                        else:  # 範圍
                            fixed.hide()
                            range_w.show()
                        # 強制更新布局
                        container.update()
                        container.updateGeometry()
                        # 強制父布局更新
                        if container.parent():
                            container.parent().update()
                    return handler
                
                on_mode_changed = make_mode_changed_handler(fixed_widget, range_widget, container_widget)
                mode_combo.currentTextChanged.connect(on_mode_changed)
                # 初始化：顯示固定值，隱藏範圍
                on_mode_changed("固定值")
                
                range_row.addWidget(container_widget)
                range_row.addStretch()
                
                self.optimization_params_layout.addRow(range_row)
                
                # 保存控件引用
                self.optimization_param_widgets[param_name] = {
                    'mode': mode_combo,
                    'fixed': fixed_widget,
                    'min': min_widget,
                    'max': max_widget,
                    'step': step_widget,
                    'type': param_type
                }
            
            # 如果沒有參數，顯示提示
            if not self.optimization_param_widgets:
                print(f"[BacktestView] 警告：參數讀取成功但控件未創建，params: {params}")
                hint_label = QLabel("此策略沒有可最佳化的參數")
                hint_label.setStyleSheet("color: #888; font-style: italic;")
                self.optimization_params_layout.addRow(hint_label)
            else:
                print(f"[BacktestView] 成功創建 {len(self.optimization_param_widgets)} 個參數控件")
        except Exception as e:
            import traceback
            print(f"[BacktestView] 更新最佳化參數表單失敗: {e}")
            print(traceback.format_exc())
    
    def _execute_optimization(self):
        """執行參數掃描"""
        if not self.optimizer_service:
            QMessageBox.warning(self, "錯誤", "最佳化服務未初始化")
            return
        
        # 獲取基本參數
        stock_code = self.stock_code_input.text().strip()
        if not stock_code:
            QMessageBox.warning(self, "錯誤", "請輸入股票代號")
            return
        
        start_date = self.start_date.date().toString("yyyy-MM-dd")
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        
        selected_strategy_id = self.strategy_combo.currentData()
        if not selected_strategy_id:
            QMessageBox.warning(self, "錯誤", "請選擇策略")
            return
        
        # 獲取參數範圍設定
        from app_module.optimizer_service import ParamRange
        
        param_ranges = {}
        base_params = {}
        
        for param_name, widgets in getattr(self, 'optimization_param_widgets', {}).items():
            mode = widgets['mode'].currentText()
            
            if mode == "固定值":
                # 固定值，加入基礎參數
                if isinstance(widgets['fixed'], QSpinBox):
                    base_params[param_name] = widgets['fixed'].value()
                else:
                    base_params[param_name] = widgets['fixed'].value()
            else:
                # 範圍，加入掃描參數
                param_type = widgets['type']
                if param_type == 'int':
                    min_val = widgets['min'].value()
                    max_val = widgets['max'].value()
                    step_val = widgets['step'].value()
                    param_ranges[param_name] = ParamRange(
                        name=param_name,
                        type='int',
                        values=[],
                        min=min_val,
                        max=max_val,
                        step=step_val
                    )
                else:
                    min_val = widgets['min'].value()
                    max_val = widgets['max'].value()
                    step_val = widgets['step'].value()
                    param_ranges[param_name] = ParamRange(
                        name=param_name,
                        type='float',
                        values=[],
                        min=min_val,
                        max=max_val,
                        step=step_val
                    )
        
        if not param_ranges:
            QMessageBox.warning(
                self, 
                "錯誤", 
                "請至少設定一個參數的掃描範圍。\n\n"
                "操作步驟：\n"
                "1. 確認已選擇策略\n"
                "2. 展開「參數最佳化」區塊（點擊標題旁的勾選框）\n"
                "3. 為要最佳化的參數選擇「範圍」模式\n"
                "4. 設定最小、最大、步長值\n"
                "5. 再次點擊「執行參數掃描」"
            )
            return
        
        # 獲取目標指標
        objective_map = {
            "夏普比率": "sharpe_ratio",
            "年化報酬率": "cagr",
            "CAGR-MDD權衡": "cagr_mdd"
        }
        objective = objective_map.get(self.objective_combo.currentText(), "sharpe_ratio")
        
        # 獲取其他設定
        capital = self.capital_input.value()
        fee_bps = self.fee_bps_input.value()
        slippage_bps = self.slippage_bps_input.value()
        stop_loss_pct = self.stop_loss_input.value() / 100.0 if self.stop_loss_input.value() > 0 else None
        take_profit_pct = self.take_profit_input.value() / 100.0 if self.take_profit_input.value() > 0 else None
        
        # 禁用按鈕
        self.optimize_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在執行參數掃描...")
        
        # 清空結果
        if hasattr(self, 'optimization_table'):
            self.optimization_table.setModel(None)
        
        # 創建 Worker（使用自定義進度回調）
        def optimization_task(progress_callback=None):
            # 包裝進度回調以符合 OptimizerService 的簽名 (current, total, message)
            def wrapped_callback(current, total, message):
                if progress_callback:
                    # 計算百分比
                    percentage = int((current / total * 100)) if total > 0 else 0
                    # 格式化消息：已完成 x/y 組參數
                    progress_msg = f"{message}\n已完成 {current}/{total} 組參數 ({percentage}%)"
                    progress_callback(progress_msg, percentage)
            
            return self.optimizer_service.grid_search(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                strategy_id=selected_strategy_id,
                base_params=base_params,
                param_ranges=param_ranges,
                capital=capital,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                objective=objective,
                top_n=20,
                progress_callback=wrapped_callback
            )
        
        # 使用 ProgressTaskWorker 以支持進度回調
        from ui_qt.workers.task_worker import ProgressTaskWorker
        self.worker = ProgressTaskWorker(optimization_task)
        self.worker.progress.connect(self._on_optimization_progress)
        self.worker.finished.connect(self._on_optimization_finished)
        self.worker.error.connect(self._on_optimization_error)
        self.worker.start()
    
    def _on_optimization_progress(self, message: str, percentage: int):
        """參數掃描進度更新"""
        self.progress_label.setText(message)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(percentage)
    
    def _on_optimization_finished(self, results):
        """參數掃描完成"""
        self.optimize_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        if not results:
            QMessageBox.warning(self, "提示", "沒有找到有效結果")
            return
        
        # 保存結果供後續使用
        self.current_optimization_results = results
        
        # 創建摘要表格
        summary_df = self.optimizer_service.create_optimization_summary(results)
        
        # 顯示表格
        self.optimization_model = PandasTableModel(summary_df)
        self.optimization_table.setModel(self.optimization_model)
        self.optimization_table.resizeColumnsToContents()
        
        QMessageBox.information(
            self,
            "完成",
            f"參數掃描完成！\n共找到 {len(results)} 組最佳參數組合。\n雙擊表格行可套用參數。"
        )
    
    def _on_optimization_error(self, error_msg: str):
        """參數掃描錯誤"""
        self.optimize_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        QMessageBox.critical(self, "錯誤", f"參數掃描失敗：\n\n{error_msg}")
    
    def _apply_optimization_params(self):
        """套用選中的最佳化參數"""
        if not hasattr(self, 'current_optimization_results'):
            QMessageBox.warning(self, "錯誤", "沒有可套用的結果")
            return
        
        # 獲取選中的行
        selected_indexes = self.optimization_table.selectionModel().selectedRows()
        if not selected_indexes:
            # 如果沒有選中，嘗試獲取雙擊的行
            current_index = self.optimization_table.currentIndex()
            if current_index.isValid():
                selected_indexes = [current_index]
            else:
                QMessageBox.warning(self, "錯誤", "請選擇要套用的參數組合")
                return
        
        # 獲取第一個選中的結果
        row = selected_indexes[0].row()
        if row >= len(self.current_optimization_results):
            return
        
        result = self.current_optimization_results[row]
        
        applied_count = 0
        
        # 套用參數到策略配置欄（用於單檔/批次回測）
        for param_name, value in result.params.items():
            if param_name in getattr(self, 'param_widgets', {}):
                widget = self.param_widgets[param_name]
                if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    widget.setValue(value)
                    applied_count += 1
        
        # 套用參數到參數最佳化欄（切換為固定值模式並設定值）
        for param_name, value in result.params.items():
            if param_name in getattr(self, 'optimization_param_widgets', {}):
                widgets = self.optimization_param_widgets[param_name]
                # 切換為「固定值」模式
                widgets['mode'].setCurrentText("固定值")
                # 設定固定值
                if isinstance(widgets['fixed'], (QSpinBox, QDoubleSpinBox)):
                    widgets['fixed'].setValue(value)
                    applied_count += 1
        
        # 顯示成功訊息
        message = f"已套用參數組合（排名 #{result.rank}）\n"
        message += f"夏普比率: {result.metrics.get('sharpe_ratio', 0):.2f}\n"
        message += f"年化報酬率: {result.metrics.get('annual_return', 0) * 100:.2f}%\n\n"
        message += f"已套用 {applied_count} 個參數：\n"
        message += "- 策略配置欄：可直接用於單檔/批次回測\n"
        message += "- 參數最佳化欄：已切換為「固定值」模式"
        
        QMessageBox.information(self, "成功", message)
    
    # ========== Walk-forward 驗證相關方法 ==========
    
    def _execute_walkforward(self):
        """執行 Walk-forward 驗證"""
        if not self.walkforward_service:
            QMessageBox.warning(self, "錯誤", "Walk-forward 服務未初始化")
            return
        
        # 獲取基本參數
        stock_code = self.stock_code_input.text().strip()
        if not stock_code:
            QMessageBox.warning(self, "錯誤", "請輸入股票代號")
            return
        
        start_date = self.start_date.date().toString("yyyy-MM-dd")
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        
        selected_strategy_id = self.strategy_combo.currentData()
        if not selected_strategy_id:
            QMessageBox.warning(self, "錯誤", "請選擇策略")
            return
        
        # 獲取策略參數
        params = self._get_strategy_params()
        
        # 創建策略規格
        strategy_info = StrategyRegistry.list_strategies().get(selected_strategy_id, {})
        strategy_spec = StrategySpec(
            strategy_id=selected_strategy_id,
            strategy_version="1.0",
            name=strategy_info.get('name', selected_strategy_id),
            description=strategy_info.get('description', ''),
            regime=[],
            risk_level="medium",
            target_type="stock",
            config={
                **self._get_default_strategy_config(),
                'params': params
            }
        )
        
        # 獲取其他設定
        capital = self.capital_input.value()
        fee_bps = self.fee_bps_input.value()
        slippage_bps = self.slippage_bps_input.value()
        stop_loss_pct = self.stop_loss_input.value() / 100.0 if self.stop_loss_input.value() > 0 else None
        take_profit_pct = self.take_profit_input.value() / 100.0 if self.take_profit_input.value() > 0 else None
        
        # 禁用按鈕
        self.wf_execute_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在執行 Walk-forward 驗證...")
        
        # 創建 Worker
        def walkforward_task():
            mode = self.wf_mode_combo.currentText()
            
            if mode == "Train-Test Split":
                train_report, test_report = self.walkforward_service.train_test_split(
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    strategy_spec=strategy_spec,
                    train_ratio=self.wf_train_ratio.value(),
                    capital=capital,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct
                )
                return {
                    'mode': 'split',
                    'train_report': train_report,
                    'test_report': test_report
                }
            else:  # Walk-forward
                results = self.walkforward_service.walk_forward(
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    strategy_spec=strategy_spec,
                    train_months=self.wf_train_months.value(),
                    test_months=self.wf_test_months.value(),
                    step_months=self.wf_step_months.value(),
                    capital=capital,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct
                )
                summary = self.walkforward_service.summarize_walkforward(results)
                return {
                    'mode': 'walkforward',
                    'results': results,
                    'summary': summary
                }
        
        self.worker = TaskWorker(walkforward_task)
        self.worker.finished.connect(self._on_walkforward_finished)
        self.worker.error.connect(self._on_walkforward_error)
        self.worker.start()
    
    def _on_walkforward_finished(self, result_data):
        """Walk-forward 驗證完成"""
        self.wf_execute_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        mode = result_data.get('mode')
        
        if mode == 'split':
            train_report = result_data.get('train_report')
            test_report = result_data.get('test_report')
            
            # 顯示結果
            summary_lines = [
                "=== Train-Test Split 驗證結果 ===",
                "",
                "【訓練集】",
                f"總報酬率: {train_report.total_return * 100:.2f}%",
                f"年化報酬率: {train_report.annual_return * 100:.2f}%",
                f"夏普比率: {train_report.sharpe_ratio:.2f}",
                f"最大回撤: {train_report.max_drawdown * 100:.2f}%",
                f"勝率: {train_report.win_rate * 100:.2f}%",
                "",
                "【測試集】",
                f"總報酬率: {test_report.total_return * 100:.2f}%",
                f"年化報酬率: {test_report.annual_return * 100:.2f}%",
                f"夏普比率: {test_report.sharpe_ratio:.2f}",
                f"最大回撤: {test_report.max_drawdown * 100:.2f}%",
                f"勝率: {test_report.win_rate * 100:.2f}%",
                "",
                "【退化分析】",
            ]
            
            # 計算退化程度
            train_sharpe = train_report.sharpe_ratio if train_report.sharpe_ratio != 0 else 0.01
            test_sharpe = test_report.sharpe_ratio
            degradation = (test_sharpe - train_sharpe) / abs(train_sharpe) * 100 if train_sharpe != 0 else 0
            
            summary_lines.append(f"夏普比率退化: {degradation:.2f}%")
            
            if degradation > -20:
                summary_lines.append("✓ 策略穩定性良好（退化 < 20%）")
            elif degradation > -50:
                summary_lines.append("⚠ 策略穩定性一般（退化 20-50%）")
            else:
                summary_lines.append("✗ 策略可能過擬合（退化 > 50%）")
            
            self.summary_text.setPlainText("\n".join(summary_lines))
            
        else:  # walkforward
            results = result_data.get('results', [])
            summary = result_data.get('summary', {})
            
            # 建立結果表格
            import pandas as pd
            wf_data = []
            for r in results:
                wf_data.append({
                    'Fold': len(wf_data) + 1,
                    '訓練期': f"{r.train_period[0]} ~ {r.train_period[1]}",
                    '測試期': f"{r.test_period[0]} ~ {r.test_period[1]}",
                    '訓練Sharpe': f"{r.train_metrics['sharpe_ratio']:.2f}",
                    '測試Sharpe': f"{r.test_metrics['sharpe_ratio']:.2f}",
                    '退化%': f"{r.degradation * 100:.1f}%",
                    '測試報酬率%': f"{r.test_metrics['total_return'] * 100:.2f}%",
                })
            
            wf_df = pd.DataFrame(wf_data)
            self.trades_model = PandasTableModel(wf_df)
            self.trades_table.setModel(self.trades_model)
            self.trades_table.resizeColumnsToContents()
            
            # 顯示摘要
            summary_lines = [
                "=== Walk-forward 驗證結果 ===",
                f"總 Fold 數: {summary.get('total_folds', 0)}",
                f"平均訓練 Sharpe: {summary.get('avg_train_sharpe', 0):.2f}",
                f"平均測試 Sharpe: {summary.get('avg_test_sharpe', 0):.2f}",
                f"平均退化: {summary.get('avg_degradation', 0) * 100:.1f}%",
                f"一致性: {summary.get('consistency', 0) * 100:.1f}%",
                "",
                "詳細結果請查看交易明細表格"
            ]
            
            self.summary_text.setPlainText("\n".join(summary_lines))
        
        QMessageBox.information(self, "完成", "Walk-forward 驗證完成！")
    
    def _on_walkforward_error(self, error_msg: str):
        """Walk-forward 驗證錯誤"""
        self.wf_execute_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        QMessageBox.critical(self, "錯誤", f"Walk-forward 驗證失敗：\n\n{error_msg}")
    
    # ========== 圖表相關方法 ==========
    
    def _update_chart_run_combo(self):
        """更新圖表 run 下拉選單"""
        if not hasattr(self, 'chart_run_combo') or not self.run_repository:
            return
        
        self.chart_run_combo.clear()
        self.chart_run_combo.addItem("-- 選擇回測結果 --", None)
        
        runs = self.run_repository.list_runs(limit=50)
        for run in runs:
            run_name = run.get('run_name', '')
            stock_code = run.get('stock_code', '')
            run_id = run.get('run_id', '')
            display_name = f"{run_name} ({stock_code})"
            self.chart_run_combo.addItem(display_name, run_id)
    
    def _on_chart_run_changed(self):
        """圖表 run 選擇改變"""
        if not hasattr(self, 'chart_run_combo') or not self.chart_data_service:
            return
        
        run_id = self.chart_run_combo.currentData()
        if not run_id:
            return
        
        # 載入並繪製所有圖表
        self._update_all_charts(run_id)
    
    def _plot_charts_from_report(self, report: BacktestReportDTO):
        """直接從 BacktestReportDTO 繪製圖表（不需要保存）"""
        if not hasattr(self, 'equity_chart'):
            return
        
        import numpy as np
        details = report.details
        
        # 1. 權益曲線
        equity_curve = details.get('equity_curve')
        equity_series = None
        if equity_curve is not None and isinstance(equity_curve, pd.DataFrame) and len(equity_curve) > 0:
            if 'equity' in equity_curve.columns:
                equity_series = equity_curve['equity']
            elif len(equity_curve.columns) > 0:
                equity_series = equity_curve.iloc[:, 0]
            
            # 確保索引是日期類型
            if equity_series is not None and len(equity_series) > 0:
                # 如果索引不是日期，嘗試轉換
                if not isinstance(equity_series.index, pd.DatetimeIndex):
                    try:
                        equity_series.index = pd.to_datetime(equity_series.index)
                    except:
                        pass
                
                # 獲取基準（如果可用）
                benchmark_series = None
                start_date = details.get('start_date')
                end_date = details.get('end_date')
                if start_date and end_date and self.chart_data_service:
                    try:
                        benchmark_series = self.chart_data_service.get_benchmark_series(
                            start_date, end_date
                        )
                    except:
                        pass
                
                # 獲取交易明細（用於顯示買賣點）
                trade_list = details.get('trade_list')
                
                self.equity_chart.plot(equity_series, benchmark_series, report.annual_return, trade_list)
        
        # 2. 回撤曲線
        if equity_series is not None and len(equity_series) > 0:
            try:
                # 計算回撤
                cummax = equity_series.cummax()
                drawdown_series = (equity_series - cummax) / cummax
                
                # 計算最大回撤資訊
                max_dd_value = drawdown_series.min()
                max_dd_date = drawdown_series.idxmin()
                
                peak_date = None
                peak_value = None
                if max_dd_date is not None:
                    try:
                        before_dd = equity_series.loc[:max_dd_date]
                        if len(before_dd) > 0:
                            peak_date = before_dd.idxmax()
                            peak_value = equity_series.loc[peak_date] if peak_date else None
                    except:
                        pass
                
                max_dd_info = {
                    'max_drawdown': max_dd_value,
                    'max_drawdown_date': max_dd_date,
                    'peak_date': peak_date,
                    'peak_value': peak_value
                }
                
                self.drawdown_chart.plot(drawdown_series, max_dd_info)
            except Exception as e:
                print(f"[BacktestView] 繪製回撤曲線失敗: {e}")
                import traceback
                traceback.print_exc()
        
        # 3. 交易報酬分佈
        trade_list = details.get('trade_list')
        if trade_list is not None and isinstance(trade_list, pd.DataFrame) and len(trade_list) > 0:
            try:
                # 提取報酬率
                returns = None
                if '報酬率%' in trade_list.columns:
                    returns = trade_list['報酬率%'].values
                elif 'return_pct' in trade_list.columns:
                    returns = trade_list['return_pct'].values * 100
                
                if returns is not None and len(returns) > 0:
                    # 移除 NaN 和無效值
                    returns = returns[~np.isnan(returns)]
                    returns = returns[np.isfinite(returns)]
                    
                    if len(returns) > 0:
                        # 計算統計（包含 95% VaR）
                        stats = {
                            'mean': float(np.mean(returns)),
                            'median': float(np.median(returns)),
                            'std': float(np.std(returns)) if len(returns) > 1 else 0.0,
                            'var_95': float(np.percentile(returns, 5))  # 95% VaR（5% 分位數）
                        }
                        self.return_hist.plot(returns, stats)
            except Exception as e:
                print(f"[BacktestView] 繪製報酬分佈失敗: {e}")
                import traceback
                traceback.print_exc()
        
        # 4. 持有天數分佈
        if trade_list is not None and isinstance(trade_list, pd.DataFrame) and len(trade_list) > 0:
            try:
                holding_days = None
                if '持有天數' in trade_list.columns:
                    holding_days = trade_list['持有天數'].values
                elif 'holding_days' in trade_list.columns:
                    holding_days = trade_list['holding_days'].values
                
                if holding_days is not None and len(holding_days) > 0:
                    # 移除 NaN 和無效值
                    holding_days = holding_days[~np.isnan(holding_days)]
                    holding_days = holding_days[np.isfinite(holding_days)]
                    # 轉換為整數
                    holding_days = holding_days.astype(int)
                    
                    if len(holding_days) > 0:
                        self.holding_hist.plot(holding_days)
            except Exception as e:
                print(f"[BacktestView] 繪製持有天數分佈失敗: {e}")
                import traceback
                traceback.print_exc()
    
    def _update_all_charts(self, run_id: str):
        """更新所有圖表（從已保存的 run）"""
        if not self.chart_data_service:
            return
        
        # 1. 權益曲線
        equity_series = self.chart_data_service.get_equity_series(run_id)
        if equity_series is not None and len(equity_series) > 0:
            # 計算 CAGR（用於顯示）
            run = self.run_repository.load_run(run_id)
            cagr = run.annual_return if run else None
            
            # 獲取基準（如果可用）
            benchmark_series = None
            if run:
                benchmark_series = self.chart_data_service.get_benchmark_series(
                    run.start_date, run.end_date
                )
            
            # 獲取交易明細（用於顯示買賣點）
            trade_list = self.chart_data_service.get_trade_list(run_id)
            
            self.equity_chart.plot(equity_series, benchmark_series, cagr, trade_list)
        
        # 2. 回撤曲線
        drawdown_series = self.chart_data_service.get_drawdown_series(run_id)
        max_dd_info = self.chart_data_service.get_max_drawdown_info(run_id)
        if drawdown_series is not None:
            self.drawdown_chart.plot(drawdown_series, max_dd_info)
        
        # 3. 交易報酬分佈
        returns = self.chart_data_service.get_trade_returns(run_id)
        stats = self.chart_data_service.get_trade_statistics(run_id)
        if returns is not None:
            self.return_hist.plot(returns, stats)
        
        # 4. 持有天數分佈
        holding_days = self.chart_data_service.get_holding_days(run_id)
        if holding_days is not None:
            self.holding_hist.plot(holding_days)
    
    # ========== 批次回測相關方法 ==========
    
    def _execute_batch_backtest(
        self,
        stock_codes: List[str],
        start_date: str,
        end_date: str,
        strategy_spec: StrategySpec,
        capital: float,
        fee_bps: float,
        slippage_bps: float,
        execution_price: str,
        stop_loss_pct: Optional[float],
        take_profit_pct: Optional[float],
        stop_loss_atr_mult: Optional[float],
        take_profit_atr_mult: Optional[float],
        sizing_mode: str,
        fixed_amount: Optional[float],
        risk_pct: Optional[float],
        max_positions: Optional[int],
        position_sizing: str,
        allow_pyramid: bool,
        allow_reentry: bool,
        reentry_cooldown_days: int,
        enable_limit: bool,
        enable_volume: bool,
        max_participation: float
    ):
        """執行批次回測"""
        total = len(stock_codes)
        
        # 定義進度回調函數（在主線程中更新 UI）
        def progress_callback(current: int, total_count: int, stock_code: str, message: str):
            """進度回調：更新進度條和文字"""
            # 使用 QTimer.singleShot 確保在主線程執行
            QTimer.singleShot(0, lambda: self._update_batch_progress(current, total_count, stock_code, message))
        
        # 創建 Worker
        def batch_backtest_task():
            return self.batch_backtest_service.run_batch_backtest(
                stock_codes=stock_codes,
                start_date=start_date,
                end_date=end_date,
                strategy_spec=strategy_spec,
                capital=capital,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                execution_price=execution_price,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                stop_loss_atr_mult=stop_loss_atr_mult,
                take_profit_atr_mult=take_profit_atr_mult,
                sizing_mode=sizing_mode,
                fixed_amount=fixed_amount,
                risk_pct=risk_pct,
                max_positions=max_positions,
                position_sizing=position_sizing,
                allow_pyramid=allow_pyramid,
                allow_reentry=allow_reentry,
                reentry_cooldown_days=reentry_cooldown_days,
                enable_limit_up_down=enable_limit,
                enable_volume_constraint=enable_volume,
                max_participation_rate=max_participation,
                save_runs=True,
                progress_callback=progress_callback
            )
        
        self.worker = TaskWorker(batch_backtest_task)
        self.worker.finished.connect(self._on_batch_backtest_finished)
        self.worker.error.connect(self._on_batch_backtest_error)
        self.worker.start()
    
    def _update_batch_progress(self, current: int, total: int, stock_code: str, message: str):
        """更新批次回測進度（在主線程中調用）"""
        if hasattr(self, 'progress_bar') and hasattr(self, 'progress_label'):
            self.progress_bar.setValue(current)
            progress_text = f"正在回測 {stock_code} ({current}/{total})"
            self.progress_label.setText(progress_text)
    
    def _on_batch_backtest_finished(self, batch_result):
        """批次回測完成"""
        from app_module.batch_backtest_service import BatchBacktestResultDTO
        
        self.execute_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 保存當前批次結果
        self.current_batch_result = batch_result
        
        # 顯示排行榜
        self._update_batch_leaderboard(batch_result)
        
        # 顯示整體統計
        self._update_batch_stats(batch_result)
        
        # 刷新歷史列表和圖表下拉選單（批次回測會自動保存每個結果）
        if self.run_repository:
            self._refresh_history()
        if hasattr(self, 'chart_run_combo'):
            self._update_chart_run_combo()
        
        # 切換到批次結果 Tab
        if hasattr(self, 'batch_leaderboard_table'):
            # 找到結果 TabWidget（右側的 result_tabs）
            result_tabs = None
            for widget in self.findChildren(QTabWidget):
                # 檢查是否包含「批次結果」Tab
                for i in range(widget.count()):
                    if widget.tabText(i) == "批次結果":
                        result_tabs = widget
                        widget.setCurrentIndex(i)
                        break
                if result_tabs:
                    break
        
        QMessageBox.information(
            self,
            "完成",
            f"批次回測完成！\n共回測 {len(batch_result.stock_results)} 檔股票。\n已保存的結果可在「比較」和「圖表」Tab 中查看。"
        )
    
    def _on_batch_backtest_error(self, error_msg: str):
        """批次回測錯誤"""
        self.execute_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        QMessageBox.critical(self, "錯誤", f"批次回測失敗：\n\n{error_msg}")
    
    def _update_batch_leaderboard(self, batch_result):
        """更新排行榜表格"""
        if not hasattr(self, 'batch_leaderboard_table'):
            return
        
        # 獲取排序方式
        sort_by_map = {
            "CAGR-MDD": "cagr_mdd",
            "CAGR": "cagr",
            "Sharpe": "sharpe",
            "MDD": "mdd"
        }
        sort_by = sort_by_map.get(self.batch_sort_combo.currentText(), "cagr_mdd")
        
        # 創建排行榜 DataFrame
        df = self.batch_backtest_service.create_leaderboard_dataframe(batch_result, sort_by=sort_by)
        
        # 格式化數值顯示
        for col in ['CAGR%', 'MDD%', 'WinRate%']:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
        
        for col in ['Sharpe', 'PF']:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
        
        # 設置表格模型
        self.batch_leaderboard_model = PandasTableModel(df)
        self.batch_leaderboard_table.setModel(self.batch_leaderboard_model)
        self.batch_leaderboard_table.resizeColumnsToContents()
        
        # 保存 run_id 映射（用於點擊載入）
        self.batch_run_id_map = {}
        for idx, row in df.iterrows():
            stock_code = row['股票代號']
            run_id = row.get('RunID', '')
            if run_id:
                self.batch_run_id_map[stock_code] = run_id
    
    def _update_batch_stats(self, batch_result):
        """更新整體統計"""
        if not hasattr(self, 'batch_stats_text'):
            return
        
        stats = batch_result.overall_stats
        
        stats_lines = [
            f"總股票數: {stats.get('total_stocks', 0)} 檔",
            f"成功回測: {stats.get('successful_stocks', 0)} 檔",
            f"賺錢股票: {stats.get('profitable_stocks', 0)} 檔",
            f"股票層級勝率: {stats.get('win_rate', 0) * 100:.1f}%",
            f"CAGR 中位數: {stats.get('cagr_median', 0) * 100:.2f}%",
            f"MDD 中位數: {stats.get('mdd_median', 0) * 100:.2f}%"
        ]
        
        self.batch_stats_text.setPlainText("\n".join(stats_lines))
    
    def _on_batch_sort_changed(self, sort_text: str):
        """批次排序方式改變"""
        if hasattr(self, 'current_batch_result') and self.current_batch_result:
            self._update_batch_leaderboard(self.current_batch_result)
    
    def _on_batch_row_double_clicked(self, index):
        """批次排行榜行雙擊事件"""
        if not hasattr(self, 'batch_leaderboard_model') or not self.batch_leaderboard_model:
            return
        
        # 獲取選中的行數據
        row = index.row()
        df = self.batch_leaderboard_model.getDataFrame()
        
        if row >= len(df):
            return
        
        stock_code = df.iloc[row]['股票代號']
        
        # 獲取 run_id（從 DataFrame 的 'RunID' 欄位或從 batch_result 中查找）
        run_id = None
        
        # 方法1：從 DataFrame 的 'RunID' 欄位獲取
        if 'RunID' in df.columns:
            run_id = df.iloc[row]['RunID']
            if pd.isna(run_id) or run_id == '':
                run_id = None
        
        # 方法2：如果沒有 RunID，從 batch_result 中查找
        if not run_id and hasattr(self, 'current_batch_result'):
            for result in self.current_batch_result.stock_results:
                if result.stock_code == stock_code and result.run_id:
                    run_id = result.run_id
                    break
        
        if not run_id:
            QMessageBox.warning(self, "提示", f"股票 {stock_code} 沒有可載入的結果（可能未保存）")
            return
        
        # 載入該 run 的結果
        self._load_run_and_switch_tab(run_id)
    
    def _load_run_and_switch_tab(self, run_id: str):
        """載入 run 並切換到結果 Tab"""
        if not self.run_repository:
            return
        
        # 載入 run 數據
        run_data = self.run_repository.load_run_data(run_id)
        if not run_data:
            QMessageBox.warning(self, "錯誤", "載入失敗")
            return
        
        # 顯示摘要
        summary_lines = [
            f"執行名稱: {run_data.get('run_name', '')}",
            f"股票代號: {run_data.get('stock_code', '')}",
            f"日期範圍: {run_data.get('start_date', '')} ~ {run_data.get('end_date', '')}",
            f"策略: {run_data.get('strategy_id', '')}",
            "",
            "=== 績效摘要 ===",
            f"總報酬率: {run_data.get('total_return', 0) * 100:.2f}%",
            f"年化報酬率: {run_data.get('annual_return', 0) * 100:.2f}%",
            f"夏普比率: {run_data.get('sharpe_ratio', 0):.2f}",
            f"最大回撤: {run_data.get('max_drawdown', 0) * 100:.2f}%",
            f"勝率: {run_data.get('win_rate', 0) * 100:.2f}%",
            f"總交易次數: {run_data.get('total_trades', 0)}",
        ]
        
        self.summary_text.setPlainText("\n".join(summary_lines))
        
        # 顯示交易明細
        if 'trade_list' in run_data and isinstance(run_data['trade_list'], pd.DataFrame):
            trade_list = run_data['trade_list']
            if len(trade_list) > 0:
                self.trades_model = PandasTableModel(trade_list)
                self.trades_table.setModel(self.trades_model)
                self.trades_table.resizeColumnsToContents()
            else:
                self.trades_table.setModel(None)
        else:
            self.trades_table.setModel(None)
        
        # 更新圖表並切換到結果 Tab
        if hasattr(self, 'chart_run_combo') and self.chart_data_service:
            # 選中該 run
            index = self.chart_run_combo.findData(run_id)
            if index >= 0:
                self.chart_run_combo.setCurrentIndex(index)
        
        # 切換到結果 Tab（顯示摘要和明細）
        for widget in self.findChildren(QTabWidget):
            for i in range(widget.count()):
                if widget.tabText(i) == "結果":
                    widget.setCurrentIndex(i)
                    break

