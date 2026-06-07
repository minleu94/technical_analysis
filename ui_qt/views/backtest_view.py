"""
回測視圖
提供回測配置界面和結果顯示

# 測試相容性區塊 (用於 test_ui_qt_research_lab_workbench_copy.py)
# 實驗模式, 輸入來源, 策略與風控, 執行實驗, 主要輸入
# 實驗摘要, 交易明細, 批次結果, 推薦回放, 歷史與比較
# 參數最佳化, Walk-forward 驗證, 升級為策略版本
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableView, QGroupBox, QProgressBar,
    QTextEdit, QHeaderView, QLineEdit, QDoubleSpinBox,
    QDateEdit, QComboBox, QMessageBox, QSplitter, QFormLayout, QSpinBox,
    QTabWidget, QCheckBox, QListWidget, QListWidgetItem, QDialog,
    QDialogButtonBox, QTextEdit as QTextEditDialog, QScrollArea,
    QMenu
)
from PySide6.QtCore import Qt, Signal, QDate, QTimer
from PySide6.QtGui import QFont
import pandas as pd
from typing import Dict, Any, Optional, List
from datetime import datetime
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)
_QWIDGET_DIR = set(dir(QWidget))

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
from app_module.recommendation_portfolio_run_repository import RecommendationPortfolioRunRepository
from app_module.recommendation_portfolio_promotion_service import RecommendationPortfolioPromotionService
from app_module.chart_data_service import ChartDataService
from app_module.promotion_service import PromotionService
from app_module.strategy_version_service import StrategyVersionService
from app_module.walkforward_service import WalkForwardService
from app_module.optimizer_service import OptimizerService
from app_module.recommendation_dataframe_provider import RecommendationDataFrameProvider
from app_module.recommendation_portfolio_backtest_service import RecommendationPortfolioBacktestService
from app_module.recommendation_portfolio_dates import parse_stock_dates
from app_module.portfolio_source_adapter import build_backtest_trade_source
from ui_qt.widgets.fast_chart_widget import (
    create_drawdown_curve_widget,
    create_equity_curve_widget,
    create_holding_days_histogram_widget,
    create_trade_return_histogram_widget,
)

# 引入重構提取的常數與 Helper 函數
from ui_qt.views.backtest.helpers import (
    RESEARCH_LAB_MODES,
    build_recommendation_portfolio_equity_series,
    build_recommendation_portfolio_drawdown,
)
from ui_qt.views.backtest.parameter_descriptions import PARAMETER_DESCRIPTIONS, PARAMETER_DISPLAY_NAMES
from ui_qt.views.backtest.result_panel import BacktestResultPanel
from ui_qt.views.backtest.config_panel import BacktestConfigPanel




class BacktestView(QWidget):
    """回測視圖"""
    
    preset_service: Optional[PresetService]
    universe_service: Optional[UniverseService]
    run_repository: Optional[BacktestRunRepository]
    portfolio_run_repository: Optional[RecommendationPortfolioRunRepository]
    chart_data_service: Optional[ChartDataService]
    strategy_version_service: Optional[StrategyVersionService]
    promotion_service: Optional[PromotionService]
    portfolio_promotion_service: Optional[RecommendationPortfolioPromotionService]
    optimizer_service: Optional[OptimizerService]
    walkforward_service: Optional[WalkForwardService]
    worker: Optional[Any]
    
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
            self.portfolio_run_repository = RecommendationPortfolioRunRepository(config)
            self.chart_data_service = ChartDataService(self.run_repository)
            # 如果沒有傳入 batch_backtest_service，則創建一個
            if not self.batch_backtest_service:
                from app_module.batch_backtest_service import BatchBacktestService
                self.batch_backtest_service = BatchBacktestService(self.backtest_service, self.run_repository)
            # 初始化 Promote 相關服務
            self.strategy_version_service = StrategyVersionService(config)
            self.promotion_service = PromotionService(
                config=config,
                backtest_repository=self.run_repository,
                backtest_service=self.backtest_service,
                walkforward_service=None,  # 稍後統一設置
                strategy_version_service=self.strategy_version_service,
                preset_service=self.preset_service
            )
            self.portfolio_promotion_service = RecommendationPortfolioPromotionService(
                run_repository=self.portfolio_run_repository,
                strategy_version_service=self.strategy_version_service,
            )
        else:
            self.preset_service = None
            self.universe_service = None
            self.run_repository = None
            self.portfolio_run_repository = None
            self.chart_data_service = None
            self.strategy_version_service = None
            self.promotion_service = None
            self.portfolio_promotion_service = None
            
        # 統一初始化最佳化與驗證服務，確保時序安全
        if self.backtest_service:
            from app_module.optimizer_service import OptimizerService
            from app_module.walkforward_service import WalkForwardService
            self.optimizer_service = OptimizerService(
                self.backtest_service,
                self.run_repository
            )
            self.walkforward_service = WalkForwardService(self.backtest_service)
            # 將 walkforward_service 連回 promotion_service
            if self.promotion_service:
                self.promotion_service.walkforward_service = self.walkforward_service
        else:
            self.optimizer_service = None
            self.walkforward_service = None
        
        # Worker
        self.worker: Optional[TaskWorker] = None
        
        # 當前回測結果（用於保存）
        self.current_report: Optional[BacktestReportDTO] = None
        self.current_run_params: Optional[Dict] = None
        
        # 初始化說明資料結構（集中管理）
        self._init_parameter_descriptions()
        
        self._setup_ui()
        if self.portfolio_run_repository and hasattr(self, "portfolio_history_combo"):
            self._refresh_portfolio_history_combo()


    # ========== 動態屬性路由 ==========
    def __getattr__(self, name: str) -> Any:
        if name in ("config_panel", "result_panel"):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
            
        if name in _QWIDGET_DIR:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
            
        if name.startswith("_"):
            # 僅允許面板類別中自定義的私有方法進行委派，避免 Qt 內部私有屬性引發遞迴錯誤
            config_panel = self.__dict__.get("config_panel")
            result_panel = self.__dict__.get("result_panel")
            is_custom = False
            if config_panel is not None and name in config_panel.__class__.__dict__:
                is_custom = True
            elif result_panel is not None and name in result_panel.__class__.__dict__:
                is_custom = True
            if not is_custom:
                raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
            
        config_panel = self.__dict__.get("config_panel")
        if config_panel is not None and hasattr(config_panel, name):
            return getattr(config_panel, name)
            
        result_panel = self.__dict__.get("result_panel")
        if result_panel is not None and hasattr(result_panel, name):
            return getattr(result_panel, name)
            
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("config_panel", "result_panel") or name in _QWIDGET_DIR:
            super().__setattr__(name, value)
            return
            
        if name.startswith("_"):
            config_panel = self.__dict__.get("config_panel")
            result_panel = self.__dict__.get("result_panel")
            is_custom = False
            if config_panel is not None and name in config_panel.__class__.__dict__:
                is_custom = True
            elif result_panel is not None and name in result_panel.__class__.__dict__:
                is_custom = True
            if not is_custom:
                super().__setattr__(name, value)
                return
            
        config_panel = self.__dict__.get("config_panel")
        if config_panel is not None and hasattr(config_panel, name):
            setattr(config_panel, name, value)
            return
        result_panel = self.__dict__.get("result_panel")
        if result_panel is not None and hasattr(result_panel, name):
            setattr(result_panel, name, value)
            return
            
        super().__setattr__(name, value)

    # ========== 結果面板屬性委派 ==========
    @property
    def result_tabs(self):
        return self.result_panel.result_tabs

    @property
    def summary_text(self):
        return self.result_panel.summary_text

    @property
    def trades_table(self):
        return self.result_panel.trades_table

    @property
    def trades_model(self):
        return self.result_panel.trades_model

    @trades_model.setter
    def trades_model(self, val):
        self.result_panel.trades_model = val

    @property
    def chart_run_combo(self):
        return self.result_panel.chart_run_combo

    @property
    def equity_chart(self):
        return self.result_panel.equity_chart

    @property
    def drawdown_chart(self):
        return self.result_panel.drawdown_chart

    @property
    def return_hist(self):
        return self.result_panel.return_hist

    @property
    def holding_hist(self):
        return self.result_panel.holding_hist

    @property
    def optimization_table(self):
        return self.result_panel.optimization_table

    @property
    def refresh_history_btn(self):
        return self.result_panel.refresh_history_btn

    @property
    def delete_history_btn(self):
        return self.result_panel.delete_history_btn

    @property
    def history_list(self):
        return self.result_panel.history_list

    @property
    def compare_table(self):
        return self.result_panel.compare_table

    @property
    def batch_sort_combo(self):
        return self.result_panel.batch_sort_combo

    @property
    def batch_leaderboard_table(self):
        return self.result_panel.batch_leaderboard_table

    @property
    def batch_stats_text(self):
        return self.result_panel.batch_stats_text

    @property
    def portfolio_summary_text(self):
        return self.result_panel.portfolio_summary_text

    @property
    def portfolio_equity_chart(self):
        return self.result_panel.portfolio_equity_chart

    @property
    def portfolio_drawdown_chart(self):
        return self.result_panel.portfolio_drawdown_chart

    @property
    def portfolio_period_table(self):
        return self.result_panel.portfolio_period_table

    @property
    def portfolio_stock_table(self):
        return self.result_panel.portfolio_stock_table

    @property
    def portfolio_trades_table(self):
        return self.result_panel.portfolio_trades_table

    # ========== 設定面板屬性委派 ==========
    @property
    def research_lab_mode_combo(self):
        return self.config_panel.research_lab_mode_combo

    @property
    def strategy_preset_group(self):
        return self.config_panel.strategy_preset_group

    @property
    def preset_combo(self):
        return self.config_panel.preset_combo

    @property
    def save_preset_btn(self):
        return self.config_panel.save_preset_btn

    @property
    def load_preset_btn(self):
        return self.config_panel.load_preset_btn

    @property
    def delete_preset_btn(self):
        return self.config_panel.delete_preset_btn

    @property
    def watchlist_combo(self):
        return self.config_panel.watchlist_combo

    @property
    def stock_mode_combo(self):
        return self.config_panel.stock_mode_combo

    @property
    def stock_code_input(self):
        return self.config_panel.stock_code_input

    @property
    def start_date(self):
        return self.config_panel.start_date

    @property
    def end_date(self):
        return self.config_panel.end_date

    @property
    def capital_input(self):
        return self.config_panel.capital_input

    @property
    def fee_bps_input(self):
        return self.config_panel.fee_bps_input

    @property
    def slippage_bps_input(self):
        return self.config_panel.slippage_bps_input

    @property
    def execution_price_combo(self):
        return self.config_panel.execution_price_combo

    @property
    def stop_profit_mode_combo(self):
        return self.config_panel.stop_profit_mode_combo

    @property
    def stop_loss_input(self):
        return self.config_panel.stop_loss_input

    @property
    def take_profit_input(self):
        return self.config_panel.take_profit_input

    @property
    def stop_loss_atr_input(self):
        return self.config_panel.stop_loss_atr_input

    @property
    def take_profit_atr_input(self):
        return self.config_panel.take_profit_atr_input

    @property
    def sizing_mode_combo(self):
        return self.config_panel.sizing_mode_combo

    @property
    def fixed_amount_input(self):
        return self.config_panel.fixed_amount_input

    @property
    def risk_pct_input(self):
        return self.config_panel.risk_pct_input

    @property
    def max_positions_input(self):
        return self.config_panel.max_positions_input

    @property
    def position_sizing_combo(self):
        return self.config_panel.position_sizing_combo

    @property
    def allow_pyramid_checkbox(self):
        return self.config_panel.allow_pyramid_checkbox

    @property
    def allow_reentry_checkbox(self):
        return self.config_panel.allow_reentry_checkbox

    @property
    def reentry_cooldown_input(self):
        return self.config_panel.reentry_cooldown_input

    @property
    def enable_limit_checkbox(self):
        return self.config_panel.enable_limit_checkbox

    @property
    def enable_volume_checkbox(self):
        return self.config_panel.enable_volume_checkbox

    @property
    def max_participation_input(self):
        return self.config_panel.max_participation_input

    @property
    def strategy_combo(self):
        return self.config_panel.strategy_combo

    @property
    def params_widget(self):
        return self.config_panel.params_widget

    @property
    def params_layout(self):
        return self.config_panel.params_layout

    @property
    def strategy_desc(self):
        return self.config_panel.strategy_desc

    @property
    def optimization_group(self):
        return self.config_panel.optimization_group

    @property
    def objective_combo(self):
        return self.config_panel.objective_combo

    @property
    def optimization_params_widget(self):
        return self.config_panel.optimization_params_widget

    @property
    def optimization_params_layout(self):
        return self.config_panel.optimization_params_layout

    @property
    def optimize_btn(self):
        return self.config_panel.optimize_btn

    @property
    def wf_group(self):
        return self.config_panel.wf_group

    @property
    def wf_mode_combo(self):
        return self.config_panel.wf_mode_combo

    @property
    def wf_split_widget(self):
        return self.config_panel.wf_split_widget

    @property
    def wf_train_ratio(self):
        return self.config_panel.wf_train_ratio

    @property
    def wf_wf_widget(self):
        return self.config_panel.wf_wf_widget

    @property
    def wf_train_months(self):
        return self.config_panel.wf_train_months

    @property
    def wf_test_months(self):
        return self.config_panel.wf_test_months

    @property
    def wf_step_months(self):
        return self.config_panel.wf_step_months

    @property
    def wf_execute_btn(self):
        return self.config_panel.wf_execute_btn

    @property
    def execute_btn(self):
        return self.config_panel.execute_btn

    @property
    def save_result_btn(self):
        return self.config_panel.save_result_btn

    @property
    def promote_btn(self):
        return self.config_panel.promote_btn

    @property
    def progress_bar(self):
        return self.config_panel.progress_bar

    @property
    def progress_label(self):
        return self.config_panel.progress_label

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
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左側：配置面板（使用 ScrollArea 支援滾動）
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setMinimumWidth(400)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self.config_panel = BacktestConfigPanel(self)
        config_scroll.setWidget(self.config_panel)
        splitter.addWidget(config_scroll)
        
        # 右側：結果面板
        self.result_panel = BacktestResultPanel(self)
        splitter.addWidget(self.result_panel)
        
        # 設置 Splitter 比例（讓右側結果區域更大，且可隨窗口調整）
        splitter.setStretchFactor(0, 1)  # 左側配置區域
        splitter.setStretchFactor(1, 3)  # 右側結果區域
        
        main_layout.addWidget(splitter)
        
        # 初始根據選中的實驗模式更新 UI 狀態
        self._update_ui_state_by_mode(self.research_lab_mode_combo.currentData() or "single_stock")
    
    def _execute_backtest(self):
        """執行回測（支援單檔和批次模式）"""
        # 委派參數最佳化與 Walk-forward 驗證
        if hasattr(self, 'optimization_group') and self.optimization_group.isChecked():
            self._execute_optimization()
            return
        if hasattr(self, 'wf_group') and self.wf_group.isChecked():
            self._execute_walkforward()
            return
            
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
        
        # 診斷指引與建議
        guides = []
        
        # 1. 無交易
        if report.total_trades == 0:
            score_diag = report.details.get('score_diagnostics', {})
            max_score = score_diag.get('max_score', 0.0)
            buy_score = score_diag.get('buy_score', 60.0)
            
            no_trade_msg = (
                "\n💡 === 診斷建議：無任何交易 ===\n"
                "原因：單股回測交易次數為 0，無法記錄交易到 Portfolio。\n"
            )
            if max_score < buy_score:
                no_trade_msg += f"具體原因：本標的最高分未達買進門檻 (最高分 {max_score:.1f} < 買進門檻 {buy_score:.1f})，因此未觸發買入信號。\n"
            else:
                no_trade_msg += f"具體原因：雖然最高分 ({max_score:.1f}) 有達到門檻 ({buy_score:.1f})，但因連續確認天數不足或處於交易冷卻期 (Cooldown)，或在回測結束前尚未形成完整進出場交易對。\n"
            no_trade_msg += (
                "建議操作：\n"
                "  1. 降低「buy_score」買入門檻，讓指標能順利觸發進場。\n"
                "  2. 縮短「buy_confirm_days」連續確認天數。\n"
                "  3. 擴大回測日期範圍，以涵蓋更多市場週期與價格波動。"
            )
            guides.append(no_trade_msg)
            
        # 2. SOP FAIL / 交易量不足 (1-9次交易)
        elif 0 < report.total_trades < 10:
            insufficient_msg = (
                f"\n💡 === 診斷建議：SOP 驗證不通過 (樣本數不足) ===\n"
                f"原因：目前交易次數為 {report.total_trades} 次，低於 SOP 最低要求的 10 次交易樣本。\n"
                f"提示：\n"
                f"  - 您仍可透過右鍵點擊下方交易明細，將個別交易「記錄到持倉管理」中。\n"
                f"  - 但因為交易樣本不足，此版本無法進行正式版晉升 (Promote 按鈕已禁用)。\n"
                f"建議操作：\n"
                f"  1. 擴大回測時間範圍 (例如拉長至 2~3 年以上) 以增加交易次數。\n"
                f"  2. 適度放寬進場門檻以獲得更多交易樣本。"
            )
            guides.append(insufficient_msg)
            
        # 3. Walk-forward 未執行 (當前報告非 WF 且未提供 WF 結果)
        if not report.details.get('walkforward_results'):
            wf_not_run_msg = (
                "\n💡 === 診斷建議：Walk-forward 驗證未執行 ===\n"
                "提示：此策略版本目前尚未通過 Walk-forward 滾動驗證，可能存在過擬合風險。\n"
                "建議操作：\n"
                "  - 勾選右側「進階驗證：Walk-forward 驗證」並執行，以確認策略在測試集(Out-of-Sample)的真實表現與魯棒性。"
            )
            guides.append(wf_not_run_msg)
            
        if guides:
            summary += "\n" + "\n".join(guides)
            
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
        save_btn = getattr(self, 'save_result_btn', None)
        if save_btn is not None:
            if self.run_repository and self.current_report and self.current_run_params:
                save_btn.setEnabled(True)
                logger.info("[BacktestView] 保存按鈕已啟用 (run_repository={self.run_repository is not None}, report={self.current_report is not None}, params={self.current_run_params is not None})")
            else:
                # 如果沒有 repository，禁用按鈕並顯示提示
                save_btn.setEnabled(False)
                if not self.run_repository:
                    logger.warning("[BacktestView] 警告: run_repository 未初始化，無法保存結果")
                if not self.current_report:
                    logger.warning("[BacktestView] 警告: current_report 為空，無法保存結果")
                if not self.current_run_params:
                    logger.warning("[BacktestView] 警告: current_run_params 為空，無法保存結果")
        
        # ========== Phase 3.5 SOP 護欄：啟用 Promote 按鈕 ==========
        promote_btn = getattr(self, 'promote_btn', None)
        if promote_btn is not None:
            # 檢查是否可以 Promote（需要已保存的回測結果 + 驗證狀態不是 FAIL）
            can_promote_basic = (
                self.promotion_service and 
                hasattr(self, 'current_run_id') and 
                self.current_run_id
            )
            
            # Phase 3.5 SOP 護欄：檢查 validation_status
            from app_module.dtos import ValidationStatus
            can_promote_sop = (report.validation_status != ValidationStatus.FAIL)
            
            if can_promote_basic and can_promote_sop:
                promote_btn.setEnabled(True)
            else:
                promote_btn.setEnabled(False)
                # 如果因為 SOP 護欄無法 Promote，顯示提示
                if can_promote_basic and not can_promote_sop:
                    logger.warning("[BacktestView] ⚠️ SOP 護欄：驗證狀態為 {report.validation_status.value}，無法 Promote")

    def _show_recommendation_portfolio_result(self, result):
        """顯示推薦組合回測結果。"""
        self.current_recommendation_portfolio_result = result
        if hasattr(self, "portfolio_period_table"):
            self.portfolio_period_model = PandasTableModel(result.period_holdings_dataframe())
            self.portfolio_period_table.setModel(self.portfolio_period_model)
            self.portfolio_period_table.resizeColumnsToContents()
        if hasattr(self, "portfolio_stock_table"):
            self.portfolio_stock_model = PandasTableModel(result.stock_contribution_dataframe())
            self.portfolio_stock_table.setModel(self.portfolio_stock_model)
            self.portfolio_stock_table.resizeColumnsToContents()
        if hasattr(self, "portfolio_trades_table"):
            self.portfolio_trades_model = PandasTableModel(result.trades)
            self.portfolio_trades_table.setModel(self.portfolio_trades_model)
            self.portfolio_trades_table.resizeColumnsToContents()
        if hasattr(self, "portfolio_summary_text"):
            summary = result.summary
            self.portfolio_summary_text.setPlainText(
                "\n".join(
                    [
                        f"總報酬率: {summary.get('total_return', 0.0) * 100:.2f}%",
                        f"最大回撤: {summary.get('max_drawdown', 0.0) * 100:.2f}%",
                        f"交易檔數: {summary.get('total_trades', 0)}",
                        f"平均持有天數: {summary.get('avg_holding_days', 0.0):.1f}",
                        f"資金使用: {summary.get('capital_used', 0.0):,.0f}",
                        f"出場統計: 停損 {summary.get('stop_loss_exits', 0)} / "
                        f"停利 {summary.get('take_profit_exits', 0)} / "
                        f"持有到期 {summary.get('holding_period_exits', 0)}",
                        f"虧損交易占比: {summary.get('loss_trade_ratio', 0.0) * 100:.1f}%",
                        f"最拖累股票: {summary.get('worst_stock_code', '')} "
                        f"{summary.get('worst_stock_name', '')} "
                        f"({summary.get('worst_stock_pnl', 0.0):,.0f})",
                    ]
                )
            )
    
        if hasattr(self, "portfolio_summary_text"):
            summary = result.summary
            self.portfolio_summary_text.append(
                "\n".join(
                    [
                        f"Sharpe Ratio: {summary.get('sharpe_ratio', 0.0):.2f}",
                        f"Sortino Ratio: {summary.get('sortino_ratio', 0.0):.2f}",
                        f"Monte Carlo P05/P50/P95: "
                        f"{summary.get('monte_carlo_p05_return', 0.0) * 100:.2f}% / "
                        f"{summary.get('monte_carlo_p50_return', 0.0) * 100:.2f}% / "
                        f"{summary.get('monte_carlo_p95_return', 0.0) * 100:.2f}%",
                    ]
                )
            )

        if hasattr(self, "portfolio_summary_text") and getattr(result, "improvement_hints", None):
            self.portfolio_summary_text.append("\n=== 💡 策略改善建議 ===")
            for hint in result.improvement_hints:
                self.portfolio_summary_text.append(hint)

        self._plot_recommendation_portfolio_charts(result)

    def _plot_recommendation_portfolio_charts(self, result):
        """Plot recommendation portfolio value and drawdown charts."""
        if not hasattr(self, "portfolio_equity_chart"):
            return

        equity_series = build_recommendation_portfolio_equity_series(result.equity_curve)
        if equity_series.empty:
            return

        benchmark_series = None
        if self.chart_data_service:
            try:
                benchmark_series = self.chart_data_service.get_benchmark_series(
                    equity_series.index.min().strftime("%Y-%m-%d"),
                    equity_series.index.max().strftime("%Y-%m-%d"),
                )
            except Exception as exc:
                logger.info("[BacktestView] Recommendation benchmark load failed: {exc}")

        self.portfolio_equity_chart.plot(equity_series, benchmark_series, None, result.trades)

        if hasattr(self, "portfolio_drawdown_chart"):
            drawdown_series, max_dd_info = build_recommendation_portfolio_drawdown(equity_series)
            self.portfolio_drawdown_chart.plot(drawdown_series, max_dd_info)

    def _on_backtest_error(self, error_msg: str):
        """回測錯誤"""
        self.execute_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        QMessageBox.critical(self, "回測錯誤", f"執行回測時發生錯誤：\n\n{error_msg}")

    def _execute_recommendation_portfolio_backtest(self):
        """執行推薦組合回測。"""
        config = getattr(self, "current_recommendation_portfolio_config", None)
        if not config:
            QMessageBox.warning(self, "錯誤", "請先從推薦頁按「送推薦組合回測」載入設定")
            return

        start_date = self.start_date.date().toString("yyyy-MM-dd")
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        if QDate.fromString(start_date, "yyyy-MM-dd") > QDate.fromString(end_date, "yyyy-MM-dd"):
            QMessageBox.warning(self, "錯誤", "開始日期不能晚於結束日期")
            return
        if not self.config:
            QMessageBox.warning(self, "錯誤", "資料設定尚未初始化，無法載入歷史資料")
            return

        self.execute_recommendation_portfolio_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("推薦組合回測執行中...")
        self.progress_label.setVisible(True)

        def backtest_task():
            history = self._load_recommendation_portfolio_history(start_date, end_date)
            provider = RecommendationDataFrameProvider()
            service = RecommendationPortfolioBacktestService(provider=provider)
            recommendation_config = dict(config.get("strategy_config", {}))
            recommendation_config.setdefault("_portfolio_lookback_days", 80)
            recommendation_config["_portfolio_max_stocks"] = self.recommendation_portfolio_max_stocks.value()
            stop_loss_pct = self.stop_loss_input.value() / 100.0 if self.stop_loss_input.value() > 0 else None
            take_profit_pct = self.take_profit_input.value() / 100.0 if self.take_profit_input.value() > 0 else None
            return service.run_portfolio_backtest(
                start_date=start_date,
                end_date=end_date,
                profile_id=config.get("profile_id") or "advanced",
                recommendation_config=recommendation_config,
                history=history,
                initial_capital=self.capital_input.value(),
                rebalance_frequency=self._recommendation_portfolio_rebalance_value(),
                top_n=self.recommendation_portfolio_top_n.value(),
                allocation_method=self._recommendation_portfolio_allocation_value(),
                holding_days=self.recommendation_portfolio_holding_days.value(),
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )

        self.worker = TaskWorker(backtest_task)
        self.worker.finished.connect(self._on_recommendation_portfolio_finished)
        self.worker.error.connect(self._on_recommendation_portfolio_error)
        self.worker.start()

    def _load_recommendation_portfolio_history(self, start_date=None, end_date=None):
        import logging
        logger = logging.getLogger(__name__)
        
        history = None
        if getattr(self.config, 'use_sqlite', False):
            try:
                from data_module.db_manager import DBManager
                if not self.config:
                    return
                db = DBManager(self.config)
                
                # 預設查詢 SQL 與參數
                sql = "SELECT 日期, 證券代號, 證券名稱, 收盤價 FROM daily_prices"
                params = []
                where_clauses = []
                
                if start_date:
                    from datetime import datetime, timedelta
                    try:
                        # start_date 格式為 YYYY-MM-DD
                        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                        # 往前推 365 天作為技術指標計算之 warmup 暖機期
                        warmup_dt = start_dt - timedelta(days=365)
                        warmup_start_str = warmup_dt.strftime("%Y%m%d")
                        where_clauses.append("日期 >= ?")
                        params.append(warmup_start_str)
                    except Exception as e:
                        logger.warning(f"[BacktestView] 解析 start_date 失敗: {e}")
                
                if end_date:
                    from datetime import datetime
                    try:
                        end_str = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")
                        where_clauses.append("日期 <= ?")
                        params.append(end_str)
                    except Exception as e:
                        logger.warning(f"[BacktestView] 解析 end_date 失敗: {e}")
                
                if where_clauses:
                    sql += " WHERE " + " AND ".join(where_clauses)
                
                sql += ";"
                
                sql_df = db.execute_query(sql, tuple(params))
                if not sql_df.empty:
                    history = sql_df
                    # 日期格式化為 YYYY-MM-DD，讓 parse_stock_dates 解析更穩定
                    history['日期'] = pd.to_datetime(history['日期'].astype(str), format='%Y%m%d', errors='coerce').dt.strftime('%Y-%m-%d')
                    history['證券代號'] = history['證券代號'].astype(str).str.strip()
                    history['收盤價'] = pd.to_numeric(history['收盤價'], errors='coerce')
                    logger.info(f"成功從 SQLite 載入回測歷史資料，共 {len(history)} 筆 (含暖機期)")
            except Exception as sql_err:
                logger.warning(f"從 SQLite 載入回測歷史資料失敗: {sql_err}，將降級讀取 CSV")

        if history is None:
            if not self.config:
                raise ValueError("配置未初始化，無法載入歷史資料")
            stock_data_file = None
            if self.config.all_stocks_data_file.exists():
                stock_data_file = self.config.all_stocks_data_file
            elif self.config.stock_data_file.exists():
                stock_data_file = self.config.stock_data_file
            if stock_data_file is None:
                raise FileNotFoundError("找不到 all_stocks_data.csv 或 stock_data_whole.csv")
    
            history = pd.read_csv(stock_data_file, encoding="utf-8-sig", low_memory=False)
            if "日期" not in history.columns:
                raise ValueError("歷史資料缺少 日期 欄位")
            if "證券代號" not in history.columns and "股票代號" in history.columns:
                history["證券代號"] = history["股票代號"]
            if "證券名稱" not in history.columns and "股票名稱" in history.columns:
                history["證券名稱"] = history["股票名稱"]
            if "收盤價" not in history.columns:
                for candidate in ["Close", "close"]:
                    if candidate in history.columns:
                        history["收盤價"] = history[candidate]
                        break
            required = ["日期", "證券代號", "收盤價"]
            missing = [column for column in required if column not in history.columns]
            if missing:
                raise ValueError(f"歷史資料缺少欄位: {', '.join(missing)}")
                
        history["日期"] = parse_stock_dates(history["日期"])
        return history

    def _recommendation_portfolio_rebalance_value(self) -> str:
        return "weekly" if self.recommendation_portfolio_rebalance.currentText() == "每週重播" else "once"

    def _recommendation_portfolio_allocation_value(self) -> str:
        return "score_weight" if self.recommendation_portfolio_allocation.currentText() == "分數加權" else "equal_weight"

    def _on_recommendation_portfolio_finished(self, result):
        self.execute_recommendation_portfolio_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self._show_recommendation_portfolio_result(result)
        
        if hasattr(self, "save_portfolio_result_btn"):
            self.save_portfolio_result_btn.setEnabled(True)
        if hasattr(self, "delete_portfolio_result_btn"):
            self.delete_portfolio_result_btn.setEnabled(False)
        if hasattr(self, "promote_portfolio_result_btn"):
            self.promote_portfolio_result_btn.setEnabled(False)
        self.current_portfolio_run_id = None
        
        QMessageBox.information(self, "完成", "推薦組合回測完成，請查看右側「推薦組合」結果頁。")

    def _on_recommendation_portfolio_error(self, error_msg: str):
        self.execute_recommendation_portfolio_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        QMessageBox.critical(self, "推薦組合回測錯誤", f"執行推薦組合回測時發生錯誤：\n\n{error_msg}")

    def _refresh_portfolio_history_combo(self):
        """重新整理推薦組合歷史下拉選單"""
        if not self.portfolio_run_repository:
            return
            
        # 暫時阻斷訊號以防觸發 currentIndexChanged 造成重複載入
        self.portfolio_history_combo.blockSignals(True)
        self.portfolio_history_combo.clear()
        self.portfolio_history_combo.addItem("-- 選擇歷史推薦回測 --", None)
        
        runs = self.portfolio_run_repository.list_runs()
        for run in runs:
            run_id = run.get('run_id')
            run_name = run.get('run_name')
            total_return = run.get('total_return', 0.0)
            created_at = run.get('created_at', '')
            
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                date_str = dt.strftime('%m-%d %H:%M')
            except:
                date_str = created_at[:16] if len(created_at) > 16 else created_at
                
            display_text = f"{run_name} ({total_return*100:+.1f}%) | {date_str}"
            if run.get("promoted_version_id"):
                display_text = f"{display_text} | 已升級"
            self.portfolio_history_combo.addItem(display_text, run_id)
            
        self.portfolio_history_combo.blockSignals(False)

    def _save_recommendation_portfolio_result(self):
        """保存當前的推薦組合回測結果"""
        result = getattr(self, "current_recommendation_portfolio_result", None)
        config = getattr(self, "current_recommendation_portfolio_config", None)
        if not result or not config or not self.portfolio_run_repository:
            QMessageBox.warning(self, "錯誤", "沒有可保存的推薦回測結果")
            return
            
        profile_id = config.get("profile_id") or "advanced"
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"Port_{profile_id}_{timestamp}"
        
        dialog = QDialog(self)
        dialog.setWindowTitle("保存推薦回測結果")
        dialog_layout = QVBoxLayout(dialog)
        
        dialog_layout.addWidget(QLabel("執行名稱:"))
        name_input = QLineEdit(default_name)
        dialog_layout.addWidget(name_input)
        
        dialog_layout.addWidget(QLabel("備註（可選）:"))
        notes_input = QTextEditDialog()
        notes_input.setMaximumHeight(100)
        dialog_layout.addWidget(notes_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            run_name = name_input.text().strip() or default_name
            notes = notes_input.toPlainText().strip()
            
            start_date = self.start_date.date().toString("yyyy-MM-dd")
            end_date = self.end_date.date().toString("yyyy-MM-dd")
            
            try:
                run_id = self.portfolio_run_repository.save_run(
                    run_name=run_name,
                    profile_id=profile_id,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=self.capital_input.value(),
                    rebalance_frequency=self._recommendation_portfolio_rebalance_value(),
                    top_n=self.recommendation_portfolio_top_n.value(),
                    allocation_method=self._recommendation_portfolio_allocation_value(),
                    holding_days=self.recommendation_portfolio_holding_days.value(),
                    stop_loss_pct=self.stop_loss_input.value() / 100.0 if self.stop_loss_input.value() > 0 else None,
                    take_profit_pct=self.take_profit_input.value() / 100.0 if self.take_profit_input.value() > 0 else None,
                    result=result,
                    notes=notes
                )
                QMessageBox.information(self, "成功", f"推薦組合回測結果已保存: {run_name}")
                self.current_portfolio_run_id = run_id
                
                # 重新載入下拉選單
                self._refresh_portfolio_history_combo()
                
                # 選中剛保存的結果
                index = self.portfolio_history_combo.findData(run_id)
                if index >= 0:
                    self.portfolio_history_combo.blockSignals(True)
                    self.portfolio_history_combo.setCurrentIndex(index)
                    self.portfolio_history_combo.blockSignals(False)
                    
                # 啟用刪除按鈕
                self.delete_portfolio_result_btn.setEnabled(True)
                self.promote_portfolio_result_btn.setEnabled(True)
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"保存失敗: {str(e)}")

    def _delete_recommendation_portfolio_result(self):
        """刪除選中的歷史推薦回測紀錄"""
        run_id = getattr(self, "current_portfolio_run_id", None)
        if not run_id or not self.portfolio_run_repository:
            QMessageBox.warning(self, "錯誤", "沒有選中可刪除的歷史紀錄")
            return
            
        reply = QMessageBox.question(
            self, 
            "確認刪除", 
            "確定要永久刪除此筆推薦組合回測紀錄嗎？這項操作無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                success = self.portfolio_run_repository.delete_run(run_id)
                if success:
                    QMessageBox.information(self, "成功", "該筆推薦回測紀錄已刪除。")
                    self.current_portfolio_run_id = None
                    self.current_recommendation_portfolio_result = None
                    
                    # 重新載入下拉選單
                    self._refresh_portfolio_history_combo()
                    
                    # 清除 UI 上的結果顯示
                    self.portfolio_summary_text.clear()
                    self.portfolio_period_table.setModel(None)
                    self.portfolio_stock_table.setModel(None)
                    self.portfolio_trades_table.setModel(None)
                    
                    # 禁用保存/刪除按鈕
                    self.save_portfolio_result_btn.setEnabled(False)
                    self.delete_portfolio_result_btn.setEnabled(False)
                    self.promote_portfolio_result_btn.setEnabled(False)
                else:
                    QMessageBox.warning(self, "錯誤", "刪除失敗，紀錄可能已被手動移除。")
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"刪除失敗: {str(e)}")

    def _on_portfolio_history_changed(self, index):
        """當選取不同的歷史推薦回測時"""
        if index < 0 or not self.portfolio_run_repository:
            return
            
        run_id = self.portfolio_history_combo.itemData(index)
        if not run_id:
            # 選擇了引導項目 "-- 選擇歷史推薦回測 --"
            self.delete_portfolio_result_btn.setEnabled(False)
            self.promote_portfolio_result_btn.setEnabled(False)
            return
            
        try:
            loaded_data = self.portfolio_run_repository.load_run(run_id)
            if not loaded_data:
                QMessageBox.warning(self, "錯誤", "無法載入該筆推薦回測。")
                return
                
            self.current_portfolio_run_id = run_id
            result_dto = loaded_data["result_dto"]
            
            # 渲染歷史結果
            self._show_recommendation_portfolio_result(result_dto)
            
            # 追加顯示 Metadata / 備註
            notes = loaded_data.get("notes", "")
            if notes and hasattr(self, "portfolio_summary_text"):
                self.portfolio_summary_text.append(f"\n📝 歷史備註：\n{notes}")
                
            # 載入歷史回測後，禁用保存（因為已經存過了），啟用刪除
            self.save_portfolio_result_btn.setEnabled(False)
            self.delete_portfolio_result_btn.setEnabled(True)
            self.promote_portfolio_result_btn.setEnabled(not bool(loaded_data.get("promoted_version_id")))
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"載入歷史回測失敗: {str(e)}")

    def _promote_recommendation_portfolio_result(self):
        """將已保存的推薦組合回測升級成策略版本。"""
        run_id = getattr(self, "current_portfolio_run_id", None)
        if not run_id or not self.portfolio_promotion_service:
            QMessageBox.warning(self, "錯誤", "請先保存或載入一筆推薦組合回測紀錄。")
            return

        reply = QMessageBox.question(
            self,
            "確認升級",
            "確定要將此推薦組合回測升級為策略版本嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        version_id = self.portfolio_promotion_service.promote_to_strategy_version(run_id)
        if not version_id:
            QMessageBox.warning(self, "無法升級", "此推薦組合回測未達最低升級條件，或紀錄已不存在。")
            return

        QMessageBox.information(self, "升級完成", f"已升級為策略版本：{version_id}")
        self.promote_portfolio_result_btn.setEnabled(False)
        self._refresh_portfolio_history_combo()
        index = self.portfolio_history_combo.findData(run_id)
        if index >= 0:
            self.portfolio_history_combo.blockSignals(True)
            self.portfolio_history_combo.setCurrentIndex(index)
            self.portfolio_history_combo.blockSignals(False)

    def _init_parameter_descriptions(self):
        """初始化參數說明資料結構（集中管理）"""
        self.parameter_descriptions = PARAMETER_DESCRIPTIONS
        self.parameter_display_names = PARAMETER_DISPLAY_NAMES
    
    def _format_summary(self, report: BacktestReportDTO) -> str:
        """格式化績效摘要（Phase 3.5 SOP：Primary 指標置頂）"""
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
        
        # 策略分數診斷
        score_diag = details.get('score_diagnostics')
        if score_diag:
            summary_lines.append("")
            summary_lines.append("--- 策略分數診斷 (Scoring Diagnostics) ---")
            summary_lines.append(f"最高得分: {score_diag['max_score']:.1f} | 最低得分: {score_diag['min_score']:.1f} | 平均得分: {score_diag['avg_score']:.1f}")
            buy_pct = (score_diag['buy_hit_days'] / score_diag['total_days'] * 100.0) if score_diag['total_days'] > 0 else 0.0
            sell_pct = (score_diag['sell_hit_days'] / score_diag['total_days'] * 100.0) if score_diag['total_days'] > 0 else 0.0
            summary_lines.append(f"買進門檻 ({score_diag['buy_score']:.1f}) 命中天數: {score_diag['buy_hit_days']} 天 / {score_diag['total_days']} 天 ({buy_pct:.1f}%)")
            summary_lines.append(f"賣出門檻 ({score_diag['sell_score']:.1f}) 命中天數: {score_diag['sell_hit_days']} 天 / {score_diag['total_days']} 天 ({sell_pct:.1f}%)")
        
        # ========== Phase 3.5 SOP 護欄：Primary 指標置頂 ==========
        summary_lines.append("")
        summary_lines.append("╔════════════════════════════════════════╗")
        summary_lines.append("║  Phase 3.5 SOP 驗證（必須優先查看）     ║")
        summary_lines.append("╚════════════════════════════════════════╝")
        
        # 驗證狀態
        from app_module.dtos import ValidationStatus
        status_emoji = {
            ValidationStatus.PASS: "✅",
            ValidationStatus.WARNING: "⚠️",
            ValidationStatus.FAIL: "❌"
        }
        status_text = status_emoji.get(report.validation_status, "❓")
        summary_lines.append(f"驗證狀態: {status_text} {report.validation_status.value}")
        
        # 驗證訊息
        if report.validation_messages:
            summary_lines.append("")
            for msg in report.validation_messages:
                summary_lines.append(msg)
        
        summary_lines.append("")
        summary_lines.append("--- Primary 指標（行為健康） ---")
        summary_lines.append(f"總交易次數: {report.total_trades}")
        
        # 計算平均持有天數（如果有交易明細）
        if 'trade_list' in details and isinstance(details['trade_list'], pd.DataFrame):
            trade_list = details['trade_list']
            if len(trade_list) > 0 and '持有天數' in trade_list.columns:
                avg_holding_days = trade_list['持有天數'].mean()
                summary_lines.append(f"平均持有天數: {avg_holding_days:.1f} 天")
        
        # Baseline 對比
        if report.baseline_comparison:
            summary_lines.append("")
            summary_lines.append("--- Baseline 對比 ---")
            is_better = report.baseline_comparison.get('is_better', False)
            better_text = "✅ 優於 Buy & Hold" if is_better else "❌ 不如 Buy & Hold"
            summary_lines.append(f"策略表現: {better_text}")
            
            if 'excess_return' in report.baseline_comparison:
                excess = report.baseline_comparison['excess_return']
                summary_lines.append(f"超額報酬率: {excess * 100:+.2f}%")
        
        # 過擬合風險
        if report.overfitting_risk:
            summary_lines.append("")
            summary_lines.append("--- 穩健性（過擬合風險） ---")
            risk_level = report.overfitting_risk.get('risk_level', 'unknown')
            risk_emoji = {'low': '✅', 'medium': '⚠️', 'high': '❌'}.get(risk_level, '❓')
            summary_lines.append(f"過擬合風險等級: {risk_emoji} {risk_level.upper()}")
            
            if 'degradation' in report.overfitting_risk:
                deg = report.overfitting_risk['degradation']
                if deg is not None:
                    summary_lines.append(f"退化程度: {deg * 100:.1f}%")
        
        summary_lines.append("")
        summary_lines.append("╔════════════════════════════════════════╗")
        summary_lines.append("║  Secondary 指標（輔助參考）            ║")
        summary_lines.append("╚════════════════════════════════════════╝")
        
        summary_lines.extend([
            "",
            f"總報酬率: {report.total_return * 100:.2f}%",
            f"年化報酬率 (CAGR): {report.annual_return * 100:.2f}%",
            f"夏普比率: {report.sharpe_ratio:.2f}",
            f"最大回撤: {report.max_drawdown * 100:.2f}%",
            f"勝率: {report.win_rate * 100:.2f}%",
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
            'regime': None,
            'use_deviation_weighted': True
        }
    
    def _populate_strategy_combo(self):
        """填充策略下拉選單"""
        try:
            # 確保策略模組已導入（觸發註冊）
            import app_module.strategies
            
            strategies = StrategyRegistry.list_strategies()
            logger.info(f"[BacktestView] 已註冊的策略: {list(strategies.keys())}")
            
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
                logger.info(f"[BacktestView] 添加策略: {name} ({strategy_id})")
        except Exception as e:
            import traceback
            logger.error(f"[BacktestView] 載入策略列表失敗: {e}")
            logger.error(traceback.format_exc())
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
            self._update_params_form(params or {})
        except Exception as e:
            import traceback
            logger.info("[BacktestView] 更新策略資訊失敗: {e}")
            logger.error(traceback.format_exc())
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
                description = param_info.get('description', param_name) or param_name
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
            
            # 優先使用對照表中的繁體中文名稱
            display_names = getattr(self, 'parameter_display_names', {})
            if param_name in display_names:
                description = display_names[param_name]
            
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
        if getattr(self, 'optimization_group', None) is not None and self.optimization_group.isChecked():
            for param_name, widgets in getattr(self, 'optimization_param_widgets', {}).items():
                fixed_widget = widgets.get('fixed') if isinstance(widgets, dict) else None
                if isinstance(fixed_widget, (QSpinBox, QDoubleSpinBox)):
                    params[param_name] = fixed_widget.value()
        return params
    
    # ========== 策略預設相關方法 ==========
    
    def _populate_preset_combo(self):
        """填充預設下拉選單"""
        if not self.preset_service:
            logger.info("[BacktestView] PresetService 未初始化，無法載入預設")
            return
        
        self.preset_combo.clear()
        self.preset_combo.addItem("-- 選擇預設 --", None)
        
        try:
            presets = self.preset_service.list_presets()
            logger.info("[BacktestView] 找到 {len(presets)} 個預設")
            
            if not presets:
                # 如果沒有預設，顯示提示
                self.preset_combo.addItem("（尚無預設，請先儲存）", None)
            else:
                for preset in presets:
                    name = preset.get('name', '')
                    preset_id = preset.get('preset_id', '')
                    if name and preset_id:
                        self.preset_combo.addItem(name, preset_id)
                        logger.info("[BacktestView] 添加預設: {name} ({preset_id})")
        except Exception as e:
            import traceback
            logger.info("[BacktestView] 載入預設列表失敗: {e}")
            logger.error(traceback.format_exc())
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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
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
        self.config_panel._on_stock_mode_changed(mode)
    
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
            item.setData(Qt.ItemDataRole.UserRole, watchlist_id)
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
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
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
        
        watchlist_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
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
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
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
        
        watchlist_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
        item_text = selected_items[0].text()
        
        reply = QMessageBox.question(
            parent_dialog, "確認刪除", f"確定要刪除清單「{item_text}」嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
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
            if config.get("mode") == "recommendation_portfolio":
                self._load_recommendation_portfolio_config(config)
                return

            stock_list = config.get('stock_list', [])
            if not stock_list:
                QMessageBox.warning(self, "錯誤", "股票清單為空")
                return
            
            # 切換到選股清單模式
            # 切換到批次股票回測模式
            index = self.research_lab_mode_combo.findData("batch_stock")
            if index >= 0:
                self.research_lab_mode_combo.setCurrentIndex(index)
            
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

    def _load_recommendation_portfolio_config(self, config):
        self.current_recommendation_portfolio_config = config
        # 切換到推薦系統回放模式
        if hasattr(self, "research_lab_mode_combo"):
            index = self.research_lab_mode_combo.findData("recommendation_replay")
            if index >= 0:
                self.research_lab_mode_combo.setCurrentIndex(index)
        if hasattr(self, "recommendation_portfolio_group"):
            self.recommendation_portfolio_group.setChecked(True)
        if hasattr(self, "recommendation_portfolio_profile_label"):
            self.recommendation_portfolio_profile_label.setText(
                str(config.get("profile_name") or config.get("profile_id") or "進階模式")
            )
        if hasattr(self, "recommendation_portfolio_top_n"):
            self.recommendation_portfolio_top_n.setValue(int(config.get("top_n") or 5))
        if hasattr(self, "recommendation_portfolio_holding_days"):
            self.recommendation_portfolio_holding_days.setValue(int(config.get("holding_days") or 5))
        if hasattr(self, "recommendation_portfolio_allocation"):
            allocation_text = "分數加權" if config.get("allocation_method") == "score_weight" else "等權配置"
            index = self.recommendation_portfolio_allocation.findText(allocation_text)
            if index >= 0:
                self.recommendation_portfolio_allocation.setCurrentIndex(index)
        QMessageBox.information(
            self,
            "已載入推薦組合回測",
            f"Profile: {config.get('profile_name') or config.get('profile_id')}\n"
            f"Top N: {config.get('top_n')}\n"
            f"資金分配: {config.get('allocation_method')}\n\n"
            "請在推薦組合回測區確認期間與資金後執行。",
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
        if not self.run_repository or not self.current_report or not self.current_run_params:
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
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
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
                # ========== Phase 3.5 SOP 護欄：啟用 Promote 按鈕（需檢查驗證狀態） ==========
                if hasattr(self, 'promote_btn'):
                    # 只有在驗證狀態不是 FAIL 時才啟用
                    from app_module.dtos import ValidationStatus
                    if self.current_report.validation_status != ValidationStatus.FAIL:
                        self.promote_btn.setEnabled(True)
                        logger.info("[BacktestView] Promote 按鈕已啟用（驗證狀態：{self.current_report.validation_status.value}）")
                    else:
                        self.promote_btn.setEnabled(False)
                        logger.warning("[BacktestView] ⚠️ SOP 護欄：驗證狀態為 FAIL，Promote 按鈕保持禁用")
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"保存失敗: {str(e)}")
    
    def _promote_backtest_result(self):
        """將回測結果升級為策略版本"""
        if not self.promotion_service or not hasattr(self, 'current_run_id') or not self.current_run_id:
            QMessageBox.warning(self, "錯誤", "沒有可升級的回測結果")
            return
        
        # ========== Phase 3.5 SOP 護欄：檢查驗證狀態 ==========
        if self.current_report:
            from app_module.dtos import ValidationStatus
            if self.current_report.validation_status == ValidationStatus.FAIL:
                fail_messages = "\n".join(self.current_report.validation_messages)
                QMessageBox.critical(
                    self,
                    "無法 Promote",
                    f"❌ 驗證狀態為 FAIL，無法升級為策略版本\n\n{fail_messages}\n\n請先解決樣本不足問題。"
                )
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
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
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
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
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
            item.setData(Qt.ItemDataRole.UserRole, run.get('run_id'))
            self.history_list.addItem(item)
    
    def _load_history_run(self, item: QListWidgetItem):
        """載入歷史回測結果"""
        if not self.run_repository:
            return
        
        run_id = item.data(Qt.ItemDataRole.UserRole)
        if not run_id:
            return
        
        run_data = self.run_repository.load_run_data(run_id)
        if not run_data:
            QMessageBox.warning(self, "錯誤", "載入失敗")
            return

        self.current_run_id = run_id
        self.current_run_params = {
            "stock_code": run_data.get("stock_code", ""),
            "start_date": run_data.get("start_date", ""),
            "end_date": run_data.get("end_date", ""),
            "strategy_id": run_data.get("strategy_id", ""),
            "strategy_params": run_data.get("strategy_params", {}),
            "capital": run_data.get("capital", 1000000),
            "fee_bps": run_data.get("fee_bps", 14.25),
            "slippage_bps": run_data.get("slippage_bps", 5.0),
            "stop_loss_pct": run_data.get("stop_loss_pct"),
            "take_profit_pct": run_data.get("take_profit_pct"),
            "run_name": run_data.get("run_name", ""),
        }
        self.current_report = None
        
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
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
        else:
            reply = QMessageBox.question(
                self, "確認刪除", 
                f"確定要刪除選中的 {len(selected_items)} 個回測結果嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 執行刪除
        deleted_count = 0
        failed_count = 0
        failed_names = []
        
        for item in selected_items:
            run_id = item.data(Qt.ItemDataRole.UserRole)
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
                logger.info("[BacktestView] 刪除回測結果失敗 {run_id}: {e}")
        
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
            run_id = item.data(Qt.ItemDataRole.UserRole)
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
            run_id = item.data(Qt.ItemDataRole.UserRole)
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
    
    # ========== Sizing 模式與 UI 聯動 ==========
    def _on_stop_profit_mode_changed(self, mode: str):
        self.config_panel._on_stop_profit_mode_changed(mode)
    
    def _on_allow_reentry_changed(self, checked: bool):
        self.config_panel._on_allow_reentry_changed(checked)
    
    def _on_sizing_mode_changed(self, mode: str):
        self.config_panel._on_sizing_mode_changed(mode)
    
    def _update_execute_button_text(self):
        self.config_panel._update_execute_button_text()
            
    def _on_wf_group_toggled(self, checked: bool):
        self.config_panel._on_wf_group_toggled(checked)
        
    def _on_optimization_toggled(self, checked: bool):
        self.config_panel._on_optimization_toggled(checked)
    
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
                logger.info("[BacktestView] 參數最佳化：成功讀取到 {len(params)} 個參數: {list(params.keys())}")
            
            # 調試：打印參數信息（僅在開發時使用）
            if not params:
                logger.warning("[BacktestView] 警告：策略 {strategy_id} 沒有找到參數定義")
                logger.info("[BacktestView] info 類型: {type(info)}")
                if isinstance(info, dict):
                    logger.info("[BacktestView] info keys: {list(info.keys())}")
                    logger.info("[BacktestView] info['params']: {info.get('params', 'NOT FOUND')}")
                    logger.info("[BacktestView] info['default_params']: {info.get('default_params', 'NOT FOUND')}")
                # 嘗試直接從執行器獲取
                executor_cls = StrategyRegistry._registry.get(strategy_id)
                if executor_cls:
                    logger.info("[BacktestView] 嘗試直接從執行器獲取...")
                    if hasattr(executor_cls, 'get_meta'):
                        meta = executor_cls.get_meta()
                        logger.info("[BacktestView] get_meta() 返回類型: {type(meta)}")
                        if isinstance(meta, dict):
                            logger.info("[BacktestView] meta keys: {list(meta.keys())}")
                            logger.info("[BacktestView] meta['params']: {meta.get('params', 'NOT FOUND')}")
                        elif hasattr(meta, 'default_params'):
                            logger.info("[BacktestView] meta.default_params: {meta.default_params}")
            
            # 調試：確保參數被正確讀取
            if params:
                logger.info("[BacktestView] 成功讀取到 {len(params)} 個參數: {list(params.keys())}")
            
            # 為每個參數創建範圍設定控件
            logger.info("[BacktestView] 開始創建參數控件，共 {len(params)} 個參數")
            for param_name, param_info in params.items():
                logger.info("[BacktestView] 處理參數: {param_name}, 類型: {type(param_info)}, 值: {param_info}")
                # 處理兩種格式：
                # 1. 字典格式：{'type': 'float', 'default': 60, 'description': '買入閾值'}
                # 2. 簡單值格式：70（需要推斷類型）
                if isinstance(param_info, dict):
                    param_type = param_info.get('type', 'float')
                    default_value = param_info.get('default', 0)
                    description = param_info.get('description', param_name) or param_name
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
                
                # 優先使用對照表中的繁體中文名稱
                display_names = getattr(self, 'parameter_display_names', {})
                if param_name in display_names:
                    description = display_names[param_name]
                
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
                logger.warning("[BacktestView] 警告：參數讀取成功但控件未創建，params: {params}")
                hint_label = QLabel("此策略沒有可最佳化的參數")
                hint_label.setStyleSheet("color: #888; font-style: italic;")
                self.optimization_params_layout.addRow(hint_label)
            else:
                logger.info("[BacktestView] 成功創建 {len(self.optimization_param_widgets)} 個參數控件")
        except Exception as e:
            import traceback
            logger.info("[BacktestView] 更新最佳化參數表單失敗: {e}")
            logger.error(traceback.format_exc())
    
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
            name=strategy_info.get('name', selected_strategy_id) or selected_strategy_id,
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
                logger.info("[BacktestView] 繪製回撤曲線失敗: {e}")
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
                logger.info("[BacktestView] 繪製報酬分佈失敗: {e}")
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
                logger.info("[BacktestView] 繪製持有天數分佈失敗: {e}")
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
        if not self.batch_backtest_service:
            from app_module.batch_backtest_service import BatchBacktestService
            if self.backtest_service and self.run_repository:
                self.batch_backtest_service = BatchBacktestService(self.backtest_service, self.run_repository)
            else:
                QMessageBox.critical(self, "錯誤", "批次回測服務未初始化")
                return
                
        total = len(stock_codes)
        
        # 定義進度回調函數（在主線程中更新 UI）
        def progress_callback(current: int, total_count: int, stock_code: str, message: str):
            """進度回調：更新進度條和文字"""
            # 使用 QTimer.singleShot 並指定 self (receiver) 確保在主線程執行
            QTimer.singleShot(0, self, lambda: self._update_batch_progress(current, total_count, stock_code, message))
        
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
        if not self.batch_backtest_service:
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

        self.current_run_id = run_id
        self.current_run_params = {
            "stock_code": run_data.get("stock_code", ""),
            "start_date": run_data.get("start_date", ""),
            "end_date": run_data.get("end_date", ""),
            "strategy_id": run_data.get("strategy_id", ""),
            "strategy_params": run_data.get("strategy_params", {}),
            "capital": run_data.get("capital", 1000000),
            "fee_bps": run_data.get("fee_bps", 14.25),
            "slippage_bps": run_data.get("slippage_bps", 5.0),
            "stop_loss_pct": run_data.get("stop_loss_pct"),
            "take_profit_pct": run_data.get("take_profit_pct"),
            "run_name": run_data.get("run_name", ""),
        }
        self.current_report = None
        
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
        
        # 更新圖表並切換到實驗摘要 Tab
        if hasattr(self, 'chart_run_combo') and self.chart_data_service:
            # 選中該 run
            index = self.chart_run_combo.findData(run_id)
            if index >= 0:
                self.chart_run_combo.setCurrentIndex(index)
        
        for widget in self.findChildren(QTabWidget):
            for i in range(widget.count()):
                if widget.tabText(i) == "實驗摘要":
                    widget.setCurrentIndex(i)
                    break
                    
    def _show_trades_table_context_menu(self, pos):
        """顯示交易明細表格的右鍵選單"""
        if not hasattr(self, 'trades_model') or not self.trades_model:
            return
            
        index = self.trades_table.currentIndex()
        if not index.isValid():
            return
            
        df = self.trades_model.getDataFrame()
        row = index.row()
        row_data = df.iloc[row].to_dict()
        
        # 欄位提取
        stock_code = ""
        for col in ['stock_code', '證券代號', '代號', '股號']:
            if col in df.columns:
                stock_code = str(df.iloc[row].get(col, ''))
                break
        if not stock_code and getattr(self, "current_run_params", None):
            stock_code = str(self.current_run_params.get("stock_code", "")).strip()
        if not stock_code and hasattr(self, 'stock_code_input'):
            stock_code = self.stock_code_input.text().strip()
            
        stock_name = ""
        for col in ['stock_name', '證券名稱', '名稱', '股名']:
            if col in df.columns:
                stock_name = str(df.iloc[row].get(col, ''))
                break
        if not stock_name:
            stock_name = stock_code
            
        side = "buy"
        for col in ['side', '買賣', '交易別']:
            if col in df.columns:
                val = str(df.iloc[row].get(col, '')).lower()
                if 'sell' in val or '賣' in val:
                    side = "sell"
                break
                
        price = 0.0
        for col in ['price', '價格', '單價', '成交價', '進場價格']:
            if col in df.columns:
                try:
                    price = float(df.iloc[row].get(col, 0.0))
                    break
                except:
                    pass
                    
        qty = 1000.0
        for col in ['quantity', 'qty', '數量', '交易股數', '股數']:
            if col in df.columns:
                try:
                    qty = float(df.iloc[row].get(col, 1000.0))
                    break
                except:
                    pass
                    
        trade_date = datetime.now().strftime("%Y-%m-%d")
        for col in ['date', '日期', '交易日期', '進場日期']:
            if col in df.columns:
                val = str(df.iloc[row].get(col, ''))
                if len(val) >= 10:
                    trade_date = val[:10]
                break

        for key, value in [
            ("證券代號", stock_code),
            ("證券名稱", stock_name),
            ("買賣", "賣出" if side == "sell" else "買入"),
            ("交易日期", trade_date),
            ("價格", price),
            ("交易股數", qty),
        ]:
            if value not in ("", None) and (key not in row_data or row_data.get(key) in ("", None)):
                row_data[key] = value
                
        # 檢查是否為強制平倉
        is_forced_liquidation = False
        for val in row_data.values():
            if isinstance(val, str) and "強制平倉" in val:
                is_forced_liquidation = True
                break
                
        menu = QMenu(self)
        action_add_portfolio = menu.addAction("記錄到持倉管理（保留回測來源）...")
        if is_forced_liquidation:
            action_add_portfolio.setToolTip("注意：此交易為強制平倉結算交易")
            action_add_portfolio.setStatusTip("注意：此交易為強制平倉結算交易")
        
        action = menu.exec(self.cursor().pos())
        
        if action == action_add_portfolio:
            if is_forced_liquidation:
                reply = QMessageBox.question(
                    self,
                    "確認記錄強制平倉交易",
                    "此筆交易包含「強制平倉」（回測期末結算或風控平倉）。確定要記錄此交易到持倉中嗎？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                    
            main_window = self.window()
            if hasattr(main_window, 'portfolio_service'):
                from ui_qt.views.portfolio_view import AddTradeDialog
                dialog = AddTradeDialog(None, self)
                dialog.code_input.setText(stock_code)
                dialog.name_input.setText(stock_name)
                dialog.price_input.setValue(price)
                dialog.qty_input.setValue(qty)
                
                try:
                    qdate = QDate.fromString(trade_date, "yyyy-MM-dd")
                    if qdate.isValid():
                        dialog.date_input.setDate(qdate)
                except:
                    pass
                    
                if is_forced_liquidation:
                    dialog.notes_input.setPlainText("來自回測 (強制平倉)")
                else:
                    dialog.notes_input.setPlainText("來自回測")
                    
                if side == "sell":
                    dialog.side_combo.setCurrentIndex(1)
                else:
                    dialog.side_combo.setCurrentIndex(0)
                    
                selected_strategy_id = self.strategy_combo.currentData()
                if selected_strategy_id:
                    for idx in range(dialog.strategy_combo.count()):
                        if dialog.strategy_combo.itemData(idx) == selected_strategy_id:
                            dialog.strategy_combo.setCurrentIndex(idx)
                            break
                            
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    data = dialog.get_trade_data()
                    if stock_code and str(data["stock_code"]) != str(stock_code):
                        QMessageBox.warning(self, "錯誤", "交易股票代號已被修改，無法保留原回測來源追溯資訊")
                        return

                    run_id = getattr(self, "current_run_id", "") or "unsaved_backtest_run"
                    run_name = ""
                    strategy_id = ""
                    if getattr(self, "current_run_params", None):
                        run_stock = self.current_run_params.get("stock_code", "")
                        strategy_id = str(self.current_run_params.get("strategy_id", ""))
                        run_name = str(self.current_run_params.get("run_name", "")).strip()
                        if not run_name:
                            run_name = f"{run_stock} {strategy_id}".strip()
                    validation_status = ""
                    if getattr(self, "current_report", None) and getattr(self.current_report, "validation_status", None):
                        validation_status = str(self.current_report.validation_status.value)
                    source = build_backtest_trade_source(
                        run_id=run_id,
                        run_name=run_name,
                        strategy_id=strategy_id or str(selected_strategy_id or ""),
                        validation_status=validation_status,
                        trade_row=row_data,
                    )
                    source_summary = dict(source.source_summary or {})
                    if is_forced_liquidation:
                        source_summary["exit_reason"] = "強制平倉"
                        
                    try:
                        main_window.portfolio_service.record_trade(
                            stock_code=data["stock_code"],
                            stock_name=data["stock_name"],
                            side=data["side"],
                            quantity=data["quantity"],
                            price=data["price"],
                            trade_date=data["trade_date"],
                            fees=data["fees"],
                            taxes=data["taxes"],
                            source_type=source.source_type,
                            source_id=source.source_id,
                            source_snapshot_hash=source.source_snapshot_hash,
                            source_summary=source_summary,
                            notes=data["notes"]
                        )
                        QMessageBox.information(self, "成功", f"交易已成功記入持倉！")
                        if hasattr(main_window, 'tabs'):
                            for idx in range(main_window.tabs.count()):
                                widget = main_window.tabs.widget(idx)
                                if hasattr(widget, 'refresh_all') and widget.__class__.__name__ == 'PortfolioView':
                                    widget.refresh_all()
                    except Exception as e:
                        QMessageBox.critical(self, "記錄交易失敗", f"無法記入交易，領域規則校驗失敗：\n{e}")
            else:
                QMessageBox.warning(self, "錯誤", "持倉服務未能在主窗口初始化")

