"""
回測配置面板
包含所有實驗模式、策略預設、輸入來源、策略風控參數、參數最佳化與進階驗證等配置控制項
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QGroupBox, QProgressBar,
    QLineEdit, QDoubleSpinBox, QDateEdit, QComboBox, 
    QFormLayout, QSpinBox, QCheckBox
)
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QFont
from ui_qt.widgets.info_button import InfoButton
from ui_qt.views.backtest.helpers import RESEARCH_LAB_MODES


class BacktestConfigPanel(QWidget):
    """回測配置面板 (左側控制面板)"""
    
    def __init__(self, parent_view, parent=None):
        """初始化配置面板
        
        Args:
            parent_view: 父視圖 BacktestView 實例，用於獲取服務和回調方法
            parent: 父窗口
        """
        super().__init__(parent)
        self.parent_view = parent_view
        # 先行注入以避免 _setup_ui 中 callback 呼叫 parent_view 導致的時序問題
        parent_view.config_panel = self
        self.parameter_descriptions = getattr(parent_view, "parameter_descriptions", {})
        
        self._setup_ui()
        
    def _setup_ui(self):
        config_layout = QVBoxLayout(self)
        config_layout.setSpacing(10)
        config_layout.setContentsMargins(10, 10, 10, 10)

        # 實驗模式群組
        mode_group = QGroupBox("實驗模式")
        mode_layout = QVBoxLayout()
        self.research_lab_mode_combo = QComboBox()
        for mode in RESEARCH_LAB_MODES:
            self.research_lab_mode_combo.addItem(mode["label"], mode["id"])
        self.research_lab_mode_hint = QLabel(self._research_lab_mode_hint_text(0))
        self.research_lab_mode_hint.setWordWrap(True)
        self.research_lab_mode_hint.setStyleSheet("color: #666;")
        mode_layout.addWidget(self.research_lab_mode_combo)
        mode_layout.addWidget(self.research_lab_mode_hint)
        mode_group.setLayout(mode_layout)
        config_layout.addWidget(mode_group)
        self.research_lab_mode_combo.currentIndexChanged.connect(self._on_research_lab_mode_changed)
        
        # ========== 策略預設區塊 ==========
        if self.parent_view.preset_service:
            self.strategy_preset_group = QGroupBox("策略來源 / 預設")
            preset_layout = QVBoxLayout()
            
            preset_row = QHBoxLayout()
            self.preset_combo = QComboBox()
            self.preset_combo.setEditable(False)
            preset_row.addWidget(self.preset_combo)
            
            preset_btn_row = QHBoxLayout()
            self.save_preset_btn = QPushButton("儲存")
            self.save_preset_btn.setMaximumWidth(60)
            self.save_preset_btn.clicked.connect(lambda: self.parent_view._save_preset())
            preset_btn_row.addWidget(self.save_preset_btn)
            
            self.load_preset_btn = QPushButton("載入")
            self.load_preset_btn.setMaximumWidth(60)
            self.load_preset_btn.clicked.connect(lambda: self.parent_view._load_preset())
            preset_btn_row.addWidget(self.load_preset_btn)
            
            self.delete_preset_btn = QPushButton("刪除")
            self.delete_preset_btn.setMaximumWidth(60)
            self.delete_preset_btn.clicked.connect(lambda: self.parent_view._delete_preset())
            preset_btn_row.addWidget(self.delete_preset_btn)
            
            preset_layout.addLayout(preset_row)
            preset_layout.addLayout(preset_btn_row)
            self.strategy_preset_group.setLayout(preset_layout)
            config_layout.addWidget(self.strategy_preset_group)
            
            # 填滿預設下拉選單 (這會由 parent_view 的方法執行)
            self.parent_view._populate_preset_combo()
        else:
            self.strategy_preset_group = None
            self.preset_combo = None
            self.save_preset_btn = None
            self.load_preset_btn = None
            self.delete_preset_btn = None
        
        # ========== 輸入來源 ==========
        self.input_source_group = QGroupBox("輸入來源")
        config_form = QFormLayout()
        
        # 建立股票選擇容器
        self.stock_selection_container = QWidget()
        stock_selection_layout = QFormLayout(self.stock_selection_container)
        stock_selection_layout.setContentsMargins(0, 0, 0, 0)
        
        # 股票代號（支援單一/清單模式）
        stock_mode_row = QHBoxLayout()
        self.stock_mode_combo = QComboBox()
        self.stock_mode_combo.addItems(["單一股票", "選股清單"])
        self.stock_mode_combo.currentTextChanged.connect(self._on_stock_mode_changed)
        stock_mode_row.addWidget(QLabel("模式:"))
        stock_mode_row.addWidget(self.stock_mode_combo)
        stock_selection_layout.addRow(stock_mode_row)
        
        # 單一股票輸入
        self.stock_code_input = QLineEdit()
        self.stock_code_input.setPlaceholderText("例如：2330")
        stock_selection_layout.addRow("股票代號:", self.stock_code_input)
        
        # 選股清單（初始隱藏）
        self.watchlist_widget = QWidget()
        watchlist_layout = QVBoxLayout(self.watchlist_widget)
        watchlist_row = QHBoxLayout()
        self.watchlist_combo = QComboBox()
        self.watchlist_combo.setEditable(False)
        watchlist_row.addWidget(QLabel("清單:"))
        watchlist_row.addWidget(self.watchlist_combo)
        watchlist_btn = QPushButton("管理")
        watchlist_btn.setMaximumWidth(60)
        watchlist_btn.clicked.connect(lambda: self.parent_view._manage_watchlists())
        watchlist_row.addWidget(watchlist_btn)
        watchlist_layout.addLayout(watchlist_row)
        self.watchlist_widget.setVisible(False)
        stock_selection_layout.addRow(self.watchlist_widget)
        
        config_form.addRow(self.stock_selection_container)
        
        # 填滿 watchlist (由 parent_view 方法執行)
        self.parent_view._populate_watchlist_combo()
        
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

        self.input_source_group.setLayout(config_form)
        config_layout.addWidget(self.input_source_group)

        # ========== 策略與風控：資金成本 / 執行 ==========
        self.risk_cost_group = QGroupBox("策略與風控：資金成本 / 執行")
        risk_form = QFormLayout()
        
        # 初始資金
        self.capital_input = QDoubleSpinBox()
        self.capital_input.setRange(10000, 100000000)
        self.capital_input.setValue(1000000)
        self.capital_input.setPrefix("$ ")
        self.capital_input.setDecimals(0)
        if 'capital' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['capital']['tooltip_lines'])
            self.capital_input.setToolTip(tooltip_text)
        risk_form.addRow("初始資金:", self.capital_input)
        
        # 手續費
        self.fee_bps_input = QDoubleSpinBox()
        self.fee_bps_input.setRange(0, 1000)
        self.fee_bps_input.setValue(14.25)
        self.fee_bps_input.setSuffix(" bps")
        self.fee_bps_input.setDecimals(2)
        if 'fee_bps' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['fee_bps']['tooltip_lines'])
            self.fee_bps_input.setToolTip(tooltip_text)
        risk_form.addRow("手續費:", self.fee_bps_input)
        
        # 滑價
        self.slippage_bps_input = QDoubleSpinBox()
        self.slippage_bps_input.setRange(0, 1000)
        self.slippage_bps_input.setValue(5.0)
        self.slippage_bps_input.setSuffix(" bps")
        self.slippage_bps_input.setDecimals(2)
        if 'slippage_bps' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['slippage_bps']['tooltip_lines'])
            self.slippage_bps_input.setToolTip(tooltip_text)
        risk_form.addRow("滑價:", self.slippage_bps_input)
        
        # 執行價格
        self.execution_price_combo = QComboBox()
        self.execution_price_combo.addItems(["下一根K開盤價 (next_open)", "當根K收盤價 (close)"])
        self.execution_price_combo.setCurrentIndex(0)
        if 'execution_price' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['execution_price']['tooltip_lines'])
            self.execution_price_combo.setToolTip(tooltip_text)
        risk_form.addRow("執行價格:", self.execution_price_combo)
        
        # 停損停利模式
        self.stop_profit_mode_combo = QComboBox()
        self.stop_profit_mode_combo.addItems(["百分比模式", "ATR 倍數模式"])
        self.stop_profit_mode_combo.setCurrentIndex(0)
        self.stop_profit_mode_combo.currentTextChanged.connect(self._on_stop_profit_mode_changed)
        if 'stop_profit_mode' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['stop_profit_mode']['tooltip_lines'])
            self.stop_profit_mode_combo.setToolTip(tooltip_text)
        risk_form.addRow("停損停利模式:", self.stop_profit_mode_combo)
        
        # 停損（%）
        self.stop_loss_input = QDoubleSpinBox()
        self.stop_loss_input.setRange(0, 50)
        self.stop_loss_input.setValue(0)
        self.stop_loss_input.setSuffix("%")
        self.stop_loss_input.setDecimals(2)
        self.stop_loss_input.setSpecialValueText("關閉")
        if 'stop_loss_pct' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['stop_loss_pct']['tooltip_lines'])
            self.stop_loss_input.setToolTip(tooltip_text)
        risk_form.addRow("停損 (%):", self.stop_loss_input)
        
        # 停利（%）
        self.take_profit_input = QDoubleSpinBox()
        self.take_profit_input.setRange(0, 100)
        self.take_profit_input.setValue(0)
        self.take_profit_input.setSuffix("%")
        self.take_profit_input.setDecimals(2)
        self.take_profit_input.setSpecialValueText("關閉")
        if 'take_profit_pct' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['take_profit_pct']['tooltip_lines'])
            self.take_profit_input.setToolTip(tooltip_text)
        risk_form.addRow("停利 (%):", self.take_profit_input)
        
        # 停損（ATR）
        self.stop_loss_atr_input = QDoubleSpinBox()
        self.stop_loss_atr_input.setRange(0, 10)
        self.stop_loss_atr_input.setValue(0)
        self.stop_loss_atr_input.setSuffix(" × ATR")
        self.stop_loss_atr_input.setDecimals(2)
        self.stop_loss_atr_input.setSpecialValueText("關閉")
        self.stop_loss_atr_input.setVisible(False)
        if 'stop_loss_atr' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['stop_loss_atr']['tooltip_lines'])
            self.stop_loss_atr_input.setToolTip(tooltip_text)
        risk_form.addRow("停損 (ATR):", self.stop_loss_atr_input)
        
        # 停利（ATR）
        self.take_profit_atr_input = QDoubleSpinBox()
        self.take_profit_atr_input.setRange(0, 20)
        self.take_profit_atr_input.setValue(0)
        self.take_profit_atr_input.setSuffix(" × ATR")
        self.take_profit_atr_input.setDecimals(2)
        self.take_profit_atr_input.setSpecialValueText("關閉")
        self.take_profit_atr_input.setVisible(False)
        if 'take_profit_atr' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['take_profit_atr']['tooltip_lines'])
            self.take_profit_atr_input.setToolTip(tooltip_text)
        risk_form.addRow("停利 (ATR):", self.take_profit_atr_input)
        
        self.risk_cost_group.setLayout(risk_form)
        config_layout.addWidget(self.risk_cost_group)
        
        # ========== 部位 Sizing 配置 ==========
        self.sizing_group = QGroupBox("策略與風控：部位 Sizing")
        sizing_form = QFormLayout()
        
        self.sizing_mode_combo = QComboBox()
        self.sizing_mode_combo.addItems(["全倉", "固定金額", "風險百分比"])
        self.sizing_mode_combo.currentTextChanged.connect(self._on_sizing_mode_changed)
        if 'sizing_mode' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['sizing_mode']['tooltip_lines'])
            self.sizing_mode_combo.setToolTip(tooltip_text)
        sizing_form.addRow("Sizing 模式:", self.sizing_mode_combo)
        
        self.fixed_amount_input = QDoubleSpinBox()
        self.fixed_amount_input.setRange(10000, 10000000)
        self.fixed_amount_input.setValue(100000)
        self.fixed_amount_input.setPrefix("$ ")
        self.fixed_amount_input.setDecimals(0)
        self.fixed_amount_input.setVisible(False)
        if 'fixed_amount' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['fixed_amount']['tooltip_lines'])
            self.fixed_amount_input.setToolTip(tooltip_text)
        sizing_form.addRow("固定金額:", self.fixed_amount_input)
        
        self.risk_pct_input = QDoubleSpinBox()
        self.risk_pct_input.setRange(0.1, 10)
        self.risk_pct_input.setValue(2.0)
        self.risk_pct_input.setSuffix("%")
        self.risk_pct_input.setDecimals(1)
        self.risk_pct_input.setVisible(False)
        if 'risk_pct' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['risk_pct']['tooltip_lines'])
            self.risk_pct_input.setToolTip(tooltip_text)
        sizing_form.addRow("風險百分比:", self.risk_pct_input)
        
        self.sizing_group.setLayout(sizing_form)
        config_layout.addWidget(self.sizing_group)
        
        # ========== 部位管理配置 ==========
        self.position_mgmt_group = QGroupBox("策略與風控：部位管理")
        position_mgmt_form = QFormLayout()
        
        self.max_positions_input = QSpinBox()
        self.max_positions_input.setRange(1, 50)
        self.max_positions_input.setValue(1)
        self.max_positions_input.setSpecialValueText("無限制")
        if 'max_positions' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['max_positions']['tooltip_lines'])
            self.max_positions_input.setToolTip(tooltip_text)
        position_mgmt_form.addRow("最大持有部位數:", self.max_positions_input)
        
        self.position_sizing_combo = QComboBox()
        self.position_sizing_combo.addItems(["等權重", "分數加權", "波動調整"])
        self.position_sizing_combo.setCurrentIndex(0)
        if 'position_sizing' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['position_sizing']['tooltip_lines'])
            self.position_sizing_combo.setToolTip(tooltip_text)
        position_mgmt_form.addRow("部位加權方式:", self.position_sizing_combo)
        
        self.allow_pyramid_checkbox = QCheckBox("允許加碼（金字塔式建倉）")
        self.allow_pyramid_checkbox.setChecked(False)
        if 'allow_pyramid' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['allow_pyramid']['tooltip_lines'])
            self.allow_pyramid_checkbox.setToolTip(tooltip_text)
        position_mgmt_form.addRow(self.allow_pyramid_checkbox)
        
        self.allow_reentry_checkbox = QCheckBox("允許重新進場")
        self.allow_reentry_checkbox.setChecked(True)
        self.allow_reentry_checkbox.toggled.connect(self._on_allow_reentry_changed)
        if 'allow_reentry' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['allow_reentry']['tooltip_lines'])
            self.allow_reentry_checkbox.setToolTip(tooltip_text)
        position_mgmt_form.addRow(self.allow_reentry_checkbox)
        
        self.reentry_cooldown_input = QSpinBox()
        self.reentry_cooldown_input.setRange(0, 30)
        self.reentry_cooldown_input.setValue(5)
        self.reentry_cooldown_input.setSuffix(" 天")
        if 'reentry_cooldown_days' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['reentry_cooldown_days']['tooltip_lines'])
            self.reentry_cooldown_input.setToolTip(tooltip_text)
        position_mgmt_form.addRow("重新進場冷卻天數:", self.reentry_cooldown_input)
        
        self.position_mgmt_group.setLayout(position_mgmt_form)
        config_layout.addWidget(self.position_mgmt_group)
        
        # ========== 市場限制配置 ==========
        self.market_constraints_group = QGroupBox("策略與風控：市場限制")
        market_constraints_form = QFormLayout()
        
        self.enable_limit_checkbox = QCheckBox("啟用漲跌停限制")
        self.enable_limit_checkbox.setChecked(True)
        if 'enable_limit' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['enable_limit']['tooltip_lines'])
            self.enable_limit_checkbox.setToolTip(tooltip_text)
        market_constraints_form.addRow(self.enable_limit_checkbox)
        
        self.enable_volume_checkbox = QCheckBox("啟用成交量約束")
        self.enable_volume_checkbox.setChecked(True)
        if 'enable_volume' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['enable_volume']['tooltip_lines'])
            self.enable_volume_checkbox.setToolTip(tooltip_text)
        market_constraints_form.addRow(self.enable_volume_checkbox)
        
        self.max_participation_input = QDoubleSpinBox()
        self.max_participation_input.setRange(0.1, 50)
        self.max_participation_input.setValue(5.0)
        self.max_participation_input.setSuffix("%")
        self.max_participation_input.setDecimals(1)
        if 'max_participation' in self.parameter_descriptions:
            tooltip_text = '\n'.join(self.parameter_descriptions['max_participation']['tooltip_lines'])
            self.max_participation_input.setToolTip(tooltip_text)
        market_constraints_form.addRow("最大參與率:", self.max_participation_input)
        
        self.market_constraints_group.setLayout(market_constraints_form)
        config_layout.addWidget(self.market_constraints_group)
        
        # ========== 策略與風控：策略配置 ==========
        self.strategy_config_group = QGroupBox("策略與風控：策略配置")
        strategy_layout = QVBoxLayout()
        
        strategy_layout.addWidget(QLabel("策略:"))
        self.strategy_combo = QComboBox()
        strategy_layout.addWidget(self.strategy_combo)
        
        self.params_widget = QWidget()
        self.params_layout = QFormLayout(self.params_widget)
        strategy_layout.addWidget(self.params_widget)
        
        self.strategy_desc = QLabel()
        self.strategy_desc.setStyleSheet("color: #888; font-size: 10px;")
        self.strategy_desc.setWordWrap(True)
        strategy_layout.addWidget(self.strategy_desc)
        
        self.strategy_combo.currentTextChanged.connect(lambda: self.parent_view._on_strategy_changed())
        
        self.strategy_config_group.setLayout(strategy_layout)
        config_layout.addWidget(self.strategy_config_group)
        
        # 填滿策略 (由 parent_view 的方法執行)
        self.parent_view._populate_strategy_combo()
        self.parent_view._on_strategy_changed()
        
        # ========== 參數最佳化區塊 ==========
        if self.parent_view.optimizer_service:
            self.optimization_group = QGroupBox("進階驗證：參數最佳化")
            self.optimization_group.setCheckable(True)
            self.optimization_group.setChecked(False)
            self.optimization_group.toggled.connect(self._on_optimization_toggled)
            optimization_layout = QVBoxLayout()
            
            objective_row = QHBoxLayout()
            objective_row.addWidget(QLabel("目標指標:"))
            self.objective_combo = QComboBox()
            self.objective_combo.addItems(["夏普比率", "年化報酬率", "CAGR-MDD權衡"])
            if 'optimization_objective' in self.parameter_descriptions:
                tooltip_text = '\n'.join(self.parameter_descriptions['optimization_objective']['tooltip_lines'])
                self.objective_combo.setToolTip(tooltip_text)
            objective_row.addWidget(self.objective_combo)
            optimization_layout.addLayout(objective_row)
            
            self.optimization_params_widget = QWidget()
            self.optimization_params_layout = QFormLayout(self.optimization_params_widget)
            optimization_layout.addWidget(self.optimization_params_widget)
            
            self.strategy_combo.currentTextChanged.connect(lambda: self.parent_view._update_optimization_params_form())
            
            # 使用 QTimer 延遲更新，確保 UI 初始化完成後再繪製
            QTimer.singleShot(100, lambda: self.parent_view._update_optimization_params_form())
            
            self.optimize_btn = QPushButton("執行參數掃描")
            self.optimize_btn.setStyleSheet("background-color: #2196F3; color: white;")
            self.optimize_btn.clicked.connect(lambda: self.parent_view._execute_optimization())
            optimization_layout.addWidget(self.optimize_btn)
            
            self.optimization_group.setLayout(optimization_layout)
            config_layout.addWidget(self.optimization_group)
        else:
            self.optimization_group = None
            self.objective_combo = None
            self.optimization_params_widget = None
            self.optimization_params_layout = None
            self.optimize_btn = None
            
        # ========== Walk-forward 驗證區塊 ==========
        if self.parent_view.walkforward_service:
            self.wf_group = QGroupBox("進階驗證：Walk-forward 驗證")
            self.wf_group.setCheckable(True)
            self.wf_group.setChecked(False)
            self.wf_group.toggled.connect(self._on_wf_group_toggled)
            wf_layout = QVBoxLayout()
            
            wf_mode_row = QHBoxLayout()
            wf_mode_row.addWidget(QLabel("模式:"))
            self.wf_mode_combo = QComboBox()
            self.wf_mode_combo.addItems(["Train-Test Split", "Walk-forward"])
            if 'walkforward_mode' in self.parameter_descriptions:
                tooltip_text = '\n'.join(self.parameter_descriptions['walkforward_mode']['tooltip_lines'])
                self.wf_mode_combo.setToolTip(tooltip_text)
            wf_mode_row.addWidget(self.wf_mode_combo)
            wf_layout.addLayout(wf_mode_row)
            
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
            
            def on_wf_mode_changed(mode):
                if mode == "Train-Test Split":
                    self.wf_split_widget.setVisible(True)
                    self.wf_wf_widget.setVisible(False)
                else:
                    self.wf_split_widget.setVisible(False)
                    self.wf_wf_widget.setVisible(True)
            
            self.wf_mode_combo.currentTextChanged.connect(on_wf_mode_changed)
            
            self.wf_execute_btn = QPushButton("執行驗證")
            self.wf_execute_btn.setStyleSheet("background-color: #FF9800; color: white;")
            self.wf_execute_btn.clicked.connect(lambda: self.parent_view._execute_walkforward())
            wf_layout.addWidget(self.wf_execute_btn)
            
            self.wf_group.setLayout(wf_layout)
            config_layout.addWidget(self.wf_group)
        else:
            self.wf_group = None
            self.wf_mode_combo = None
            self.wf_split_widget = None
            self.wf_train_ratio = None
            self.wf_wf_widget = None
            self.wf_train_months = None
            self.wf_test_months = None
            self.wf_step_months = None
            self.wf_execute_btn = None

        # ========== 推薦回放設定 ==========
        self.recommendation_portfolio_group = QGroupBox("推薦回放設定")
        self.recommendation_portfolio_group.setCheckable(True)
        self.recommendation_portfolio_group.setChecked(False)
        recommendation_portfolio_layout = QVBoxLayout()

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.recommendation_portfolio_profile_label = QLabel("尚未從推薦頁載入")
        profile_row.addWidget(self.recommendation_portfolio_profile_label)
        profile_row.addStretch()
        recommendation_portfolio_layout.addLayout(profile_row)

        recommendation_portfolio_form = QFormLayout()
        self.recommendation_portfolio_top_n = QSpinBox()
        self.recommendation_portfolio_top_n.setRange(1, 50)
        self.recommendation_portfolio_top_n.setValue(5)
        recommendation_portfolio_form.addRow("每次推薦檔數:", self.recommendation_portfolio_top_n)

        self.recommendation_portfolio_max_stocks = QSpinBox()
        self.recommendation_portfolio_max_stocks.setRange(10, 500)
        self.recommendation_portfolio_max_stocks.setValue(50)
        self.recommendation_portfolio_max_stocks.setSingleStep(10)
        recommendation_portfolio_form.addRow("每期候選上限:", self.recommendation_portfolio_max_stocks)

        self.recommendation_portfolio_holding_days = QSpinBox()
        self.recommendation_portfolio_holding_days.setRange(1, 60)
        self.recommendation_portfolio_holding_days.setValue(5)
        recommendation_portfolio_form.addRow("持有天數:", self.recommendation_portfolio_holding_days)

        self.recommendation_portfolio_rebalance = QComboBox()
        self.recommendation_portfolio_rebalance.addItems(["每週重播", "只跑一次"])
        recommendation_portfolio_form.addRow("重播頻率:", self.recommendation_portfolio_rebalance)

        self.recommendation_portfolio_allocation = QComboBox()
        self.recommendation_portfolio_allocation.addItems(["等權配置", "分數加權"])
        recommendation_portfolio_form.addRow("資金配置:", self.recommendation_portfolio_allocation)
        recommendation_portfolio_layout.addLayout(recommendation_portfolio_form)

        self.execute_recommendation_portfolio_btn = QPushButton("執行推薦回放")
        self.execute_recommendation_portfolio_btn.setStyleSheet("background-color: #607D8B; color: white; font-weight: bold;")
        self.execute_recommendation_portfolio_btn.clicked.connect(lambda: self.parent_view._execute_recommendation_portfolio_backtest())
        recommendation_portfolio_layout.addWidget(self.execute_recommendation_portfolio_btn)

        # 推薦組合回測保存與歷史管理
        if self.parent_view.portfolio_run_repository:
            portfolio_btn_row = QHBoxLayout()
            self.save_portfolio_result_btn = QPushButton("保存推薦回放")
            self.save_portfolio_result_btn.setEnabled(False)
            self.save_portfolio_result_btn.clicked.connect(lambda: self.parent_view._save_recommendation_portfolio_result())
            portfolio_btn_row.addWidget(self.save_portfolio_result_btn)
            
            self.delete_portfolio_result_btn = QPushButton("刪除推薦回放")
            self.delete_portfolio_result_btn.setEnabled(False)
            self.delete_portfolio_result_btn.clicked.connect(lambda: self.parent_view._delete_recommendation_portfolio_result())
            portfolio_btn_row.addWidget(self.delete_portfolio_result_btn)

            self.promote_portfolio_result_btn = QPushButton("升級策略版本")
            self.promote_portfolio_result_btn.setEnabled(False)
            self.promote_portfolio_result_btn.clicked.connect(lambda: self.parent_view._promote_recommendation_portfolio_result())
            portfolio_btn_row.addWidget(self.promote_portfolio_result_btn)
            recommendation_portfolio_layout.addLayout(portfolio_btn_row)
            
            portfolio_history_row = QHBoxLayout()
            portfolio_history_row.addWidget(QLabel("歷史記錄:"))
            self.portfolio_history_combo = QComboBox()
            self.portfolio_history_combo.currentIndexChanged.connect(lambda idx: self.parent_view._on_portfolio_history_changed(idx))
            portfolio_history_row.addWidget(self.portfolio_history_combo)
            recommendation_portfolio_layout.addLayout(portfolio_history_row)
        else:
            self.save_portfolio_result_btn = None
            self.delete_portfolio_result_btn = None
            self.promote_portfolio_result_btn = None
            self.portfolio_history_combo = None

        self.recommendation_portfolio_group.setLayout(recommendation_portfolio_layout)
        config_layout.addWidget(self.recommendation_portfolio_group)
        
        # ========== 執行與下一步 ==========
        execute_row = QHBoxLayout()
        self.execute_btn = QPushButton("執行實驗")
        self.execute_btn.setMinimumHeight(40)
        self.execute_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.execute_btn.clicked.connect(lambda: self.parent_view._execute_backtest())
        execute_row.addWidget(self.execute_btn)
        
        # 保存結果按鈕
        if self.parent_view.run_repository:
            self.save_result_btn = QPushButton("保存結果")
            self.save_result_btn.setMaximumWidth(100)
            self.save_result_btn.setEnabled(False)
            self.save_result_btn.clicked.connect(lambda: self.parent_view._save_backtest_result())
            execute_row.addWidget(self.save_result_btn)
        else:
            self.save_result_btn = None
        
        # Promote 按鈕
        if self.parent_view.promotion_service:
            self.promote_btn = QPushButton("升級為策略版本")
            self.promote_btn.setMaximumWidth(120)
            self.promote_btn.setEnabled(False)
            self.promote_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
            self.promote_btn.clicked.connect(lambda: self.parent_view._promote_backtest_result())
            execute_row.addWidget(self.promote_btn)
        else:
            self.promote_btn = None
        
        # 進度列與狀態
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

        execution_group = QGroupBox("執行與下一步")
        execution_layout = QVBoxLayout()
        execution_layout.addLayout(execute_row)
        execution_layout.addWidget(progress_widget)
        execution_group.setLayout(execution_layout)
        config_layout.addWidget(execution_group)
        
        config_layout.addStretch()

    # ========== UI 內部事件處理 ==========
    
    def _research_lab_mode_hint_text(self, index: int) -> str:
        """建立 Research Lab 模式提示文字。"""
        if index < 0 or index >= len(RESEARCH_LAB_MODES):
            return ""
        mode = RESEARCH_LAB_MODES[index]
        return f"{mode['description']}｜主要輸入：{mode['primary_input']}"

    def _on_research_lab_mode_changed(self, index: int):
        """更新 Research Lab 模式提示並調整 UI 狀態。"""
        self.research_lab_mode_hint.setText(self._research_lab_mode_hint_text(index))
        if index >= 0 and index < len(RESEARCH_LAB_MODES):
            mode = RESEARCH_LAB_MODES[index]
            self._update_ui_state_by_mode(mode["id"])

    def _update_ui_state_by_mode(self, mode_id: str):
        """根據 Research Lab 模式調整左側配置面板的顯示狀態。"""
        is_single = (mode_id == "single_stock")
        is_batch = (mode_id == "batch_stock")
        is_fixed = (mode_id == "fixed_basket")
        is_replay = (mode_id == "recommendation_replay")
        is_research = (mode_id == "strategy_research")

        # 1. 策略預設群組
        if self.strategy_preset_group:
            self.strategy_preset_group.setVisible(is_single or is_batch or is_fixed or is_research)

        # 2. 輸入來源群組
        if self.input_source_group:
            self.input_source_group.setVisible(True)
            self.stock_selection_container.setVisible(not is_replay)
            # 自動切換單一/清單下拉選單
            if is_single:
                self.stock_mode_combo.blockSignals(True)
                self.stock_mode_combo.setCurrentText("單一股票")
                self.stock_mode_combo.blockSignals(False)
                self._on_stock_mode_changed("單一股票")
            elif is_batch or is_fixed:
                self.stock_mode_combo.blockSignals(True)
                self.stock_mode_combo.setCurrentText("選股清單")
                self.stock_mode_combo.blockSignals(False)
                self._on_stock_mode_changed("選股清單")

        # 3. 策略與風控群組
        if self.risk_cost_group:
            self.risk_cost_group.setVisible(not is_replay)
        if self.sizing_group:
            self.sizing_group.setVisible(not is_replay)
        if self.position_mgmt_group:
            self.position_mgmt_group.setVisible(not is_replay)
        if self.market_constraints_group:
            self.market_constraints_group.setVisible(not is_replay)
        if self.strategy_config_group:
            self.strategy_config_group.setVisible(not is_replay)

        # 4. 推薦回放群組
        if self.recommendation_portfolio_group:
            self.recommendation_portfolio_group.setVisible(is_replay)
            if is_replay:
                self.recommendation_portfolio_group.setChecked(True)

        # 5. 進階參數最佳化群組
        if self.optimization_group:
            self.optimization_group.setVisible(is_single or is_research)
            if is_research:
                self.optimization_group.setChecked(True)
            else:
                self.optimization_group.setChecked(False)

        # 6. 進階 Walk-forward 驗證群組
        if self.wf_group:
            self.wf_group.setVisible(is_single or is_research)
            if is_research:
                self.wf_group.setChecked(True)
            else:
                self.wf_group.setChecked(False)

    def _on_stock_mode_changed(self, mode: str):
        """股票模式切換"""
        if mode == "單一股票":
            self.stock_code_input.setVisible(True)
            self.watchlist_widget.setVisible(False)
        else:
            self.stock_code_input.setVisible(False)
            self.watchlist_widget.setVisible(True)

    def _on_stop_profit_mode_changed(self, mode: str):
        """停損停利模式切換"""
        if mode == "百分比模式":
            self.stop_loss_input.setVisible(True)
            self.take_profit_input.setVisible(True)
            self.stop_loss_atr_input.setVisible(False)
            self.take_profit_atr_input.setVisible(False)
        else:
            self.stop_loss_input.setVisible(False)
            self.take_profit_input.setVisible(False)
            self.stop_loss_atr_input.setVisible(True)
            self.take_profit_atr_input.setVisible(True)

    def _on_allow_reentry_changed(self, checked: bool):
        """允許重新進場切換"""
        self.reentry_cooldown_input.setEnabled(checked)

    def _on_sizing_mode_changed(self, mode: str):
        """Sizing 模式切換"""
        if mode == "固定金額":
            self.fixed_amount_input.setVisible(True)
            self.risk_pct_input.setVisible(False)
        elif mode == "風險百分比":
            self.fixed_amount_input.setVisible(False)
            self.risk_pct_input.setVisible(True)
        else:
            self.fixed_amount_input.setVisible(False)
            self.risk_pct_input.setVisible(False)

    def _update_execute_button_text(self):
        """根據進階選項更新執行按鈕文字"""
        opt_checked = self.optimization_group.isChecked() if self.optimization_group else False
        wf_checked = self.wf_group.isChecked() if self.wf_group else False
        
        if opt_checked:
            self.execute_btn.setText("執行參數最佳化")
        elif wf_checked:
            self.execute_btn.setText("執行 Walk-forward 驗證")
        else:
            self.execute_btn.setText("執行實驗")

    def _on_wf_group_toggled(self, checked: bool):
        """Walk-forward 驗證區塊勾選狀態變更"""
        self._update_execute_button_text()

    def _on_optimization_toggled(self, checked: bool):
        """參數最佳化區塊勾選狀態變更"""
        self._update_execute_button_text()
        if checked:
            self.params_widget.setVisible(False)
            self.parent_view._update_optimization_params_form()
        else:
            self.params_widget.setVisible(True)
            if self.optimization_params_layout:
                while self.optimization_params_layout.count():
                    child = self.optimization_params_layout.takeAt(0)
                    widget = child.widget()
                    if widget:
                        widget.deleteLater()
