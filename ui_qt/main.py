"""
PySide6 主應用程式
"""

import sys
from pathlib import Path

# 添加項目根目錄到系統路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from PySide6.QtWidgets import QApplication, QMainWindow, QStatusBar, QTabWidget, QMessageBox, QLabel
from typing import Dict, Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from data_module.config import TWStockConfig
from app_module.screening_service import ScreeningService
from app_module.regime_service import RegimeService
from app_module.decision_desk_dtos import DecisionDeskQuality, MarketRegimeSummary
from app_module.market_breadth_service import MarketBreadthService, SQLiteDailyPriceMarketBreadthProvider
from app_module.sector_rotation_service import SectorRotationService, SQLiteIndustryIndexSectorRotationProvider
from app_module.watchlist_trigger_service import WatchlistTriggerService, WatchlistServiceWatchlistProvider, SQLiteRankingProvider
from app_module.relative_strength_liquidity_service import (
    RelativeStrengthLiquidityService,
    SQLiteDailyPriceRelativeStrengthLiquidityProvider,
)
from app_module.recommendation_service import RecommendationService
from app_module.portfolio_alert_service import PortfolioAlertService
from app_module.portfolio_condition_monitor import PortfolioConditionMonitor
from app_module.portfolio_chip_service import PortfolioChipService
from app_module.update_service import UpdateService
from app_module.backtest_service import BacktestService
from app_module.batch_backtest_service import BatchBacktestService
from app_module.watchlist_service import WatchlistService
from app_module.universe_service import UniverseService
from app_module.research_session import ResearchSessionStore
# 導入策略模組以觸發註冊
import app_module.strategies
from ui_qt.views.strong_stocks_view import StrongStocksView
from ui_qt.views.weak_stocks_view import WeakStocksView
from ui_qt.views.market_regime_view import MarketRegimeView
from ui_qt.views.strong_industries_view import StrongIndustriesView
from ui_qt.views.weak_industries_view import WeakIndustriesView
from ui_qt.views.recommendation_view import RecommendationView
from ui_qt.views.update_view import UpdateView
from ui_qt.views.backtest_view import BacktestView
from ui_qt.views.watchlist_view import WatchlistView
from ui_qt.widgets.session_context_strip import SessionContextStrip
from ui_qt.views.smart_money.smart_money_flow_view import SmartMoneyFlowView
from app_module.broker_flow_service import BrokerFlowService
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder
from ui_qt.views.decision_desk_view import DecisionDeskView

# Runtime Observatory Imports
from app_module.runtime_services.runtime_controller import RuntimeController
from ui_qt.bridges.runtime_event_bridge import QtRuntimeBridge
from ui_qt.views.runtime_view import RuntimeView
from PySide6.QtCore import QTimer
import os


class MainWindow(QMainWindow):
    """主窗口"""
    
    class _DecisionDeskMarketRegimeProvider:
        """僅供主畫面使用的 market regime provider（決策桌面適配器）。"""

        def __init__(self, regime_service: RegimeService):
            self.regime_service = regime_service

        def _to_confidence_bp(self, confidence) -> int | None:
            if confidence is None:
                return None
            try:
                value = float(confidence)
            except (TypeError, ValueError):
                return None
            if 0 <= value <= 1:
                return int(value * 10000)
            if 0 <= value <= 100:
                return int(value * 100)
            return int(value)

        def fetch_market_regime(self, as_of_date):
            if self.regime_service is None:
                return None
            try:
                as_of_date_str = as_of_date.isoformat()
                try:
                    result = self.regime_service.detect_regime(as_of_date=as_of_date_str)
                except TypeError:
                    result = self.regime_service.detect_regime(date=as_of_date_str)
                except Exception:
                    result = self.regime_service.detect_regime(as_of_date_str)
                details = dict(getattr(result, "details", {}) or {})
                confidence_bp = self._to_confidence_bp(getattr(result, "confidence", None))
                regime_score = details.get("ma20_slope")
                if regime_score is None:
                    regime_score = details.get("score")
                if regime_score is None:
                    regime_score = details.get("regime_score")
                if regime_score is not None:
                    try:
                        regime_score = int(float(regime_score) * 100)
                    except (TypeError, ValueError):
                        regime_score = None

                return MarketRegimeSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.OBSERVED,
                    warnings=(),
                    regime_label=getattr(result, "regime_name_cn", None) or getattr(result, "regime", None),
                    regime_score=regime_score,
                    regime_confidence=confidence_bp,
                    meta=details,
                )
            except Exception:
                return None

        def fetch_market_breadth(self, as_of_date):
            return None

        def fetch_sector_rotation(self, as_of_date):
            return None

        def fetch_watchlist_triggers(self, as_of_date):
            return None

        def fetch_portfolio_alerts(self, as_of_date):
            return None

    def _create_decision_desk_builder(self) -> DecisionDeskSnapshotBuilder:
        provider = self._DecisionDeskMarketRegimeProvider(self.regime_service)
        market_breadth_service = None
        try:
            market_breadth_service = MarketBreadthService(
                SQLiteDailyPriceMarketBreadthProvider(self.config.db_file)
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 MarketBreadthService 初始化失敗：{exc}")

        sector_rotation_service = None
        try:
            sector_rotation_service = SectorRotationService(
                SQLiteIndustryIndexSectorRotationProvider(self.config.db_file)
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 SectorRotationService 初始化失敗：{exc}")

        portfolio_alert_service = None
        try:
            condition_monitor = PortfolioConditionMonitor()
            chip_summary_provider = None
            try:
                chip_summary_provider = PortfolioChipService(
                    self.config,
                    broker_flow_service=getattr(self, "broker_flow_service", None),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[MainWindow] 決策桌面 PortfolioChipService 初始化失敗：{exc}")
            portfolio_alert_service = PortfolioAlertService(
                portfolio_service=self.portfolio_service,
                condition_monitor=condition_monitor,
                chip_summary_provider=chip_summary_provider,
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 PortfolioAlertService 初始化失敗：{exc}")

        watchlist_trigger_service = None
        try:
            watchlist_provider = WatchlistServiceWatchlistProvider(self.watchlist_service)
            ranking_provider = SQLiteRankingProvider(self.config.db_file)
            watchlist_trigger_service = WatchlistTriggerService(
                watchlist_provider=watchlist_provider,
                ranking_provider=ranking_provider,
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 WatchlistTriggerService 初始化失敗：{exc}")

        relative_strength_liquidity_service = None
        try:
            relative_strength_liquidity_provider = SQLiteDailyPriceRelativeStrengthLiquidityProvider(self.config.db_file)
            relative_strength_liquidity_service = RelativeStrengthLiquidityService(
                provider=relative_strength_liquidity_provider
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 RelativeStrengthLiquidityService 初始化失敗：{exc}")

        return DecisionDeskSnapshotBuilder(
            provider=provider,
            market_breadth_service=market_breadth_service,
            sector_rotation_service=sector_rotation_service,
            relative_strength_liquidity_service=relative_strength_liquidity_service,
            watchlist_trigger_service=watchlist_trigger_service,
            portfolio_alert_service=portfolio_alert_service,
        )

    def __init__(self):
        super().__init__()
        self.setWindowTitle("台股技術分析系統")
        self.setGeometry(100, 100, 1400, 800)
        
        # 設置窗口 icon
        icon_path = Path(__file__).parent / 'app_icon.png'
        if icon_path.exists():
            icon_path_abs = icon_path.resolve()  # 使用絕對路徑
            self.setWindowIcon(QIcon(str(icon_path_abs)))
        
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # 初始化配置和服務
            self.config = TWStockConfig()
            
            # 共享 IndustryMapper 實例，避免重複載入資料
            # from ui_app.industry_mapper import IndustryMapper
            from decision_module.industry_mapper import IndustryMapper
            shared_industry_mapper = IndustryMapper(self.config)
            
            self.screening_service = ScreeningService(self.config, industry_mapper=shared_industry_mapper)
            self.regime_service = RegimeService(self.config)
            self.recommendation_service = RecommendationService(self.config, industry_mapper=shared_industry_mapper)
            self.update_service = UpdateService(self.config)
            self.backtest_service = BacktestService(self.config)
            self.broker_flow_service = BrokerFlowService(self.config)
            self.research_session_store = ResearchSessionStore()
            
            # 初始化持倉與日記服務
            from app_module.portfolio_service import PortfolioService 
            from app_module.journal_service import JournalService
            self.portfolio_service = PortfolioService(self.config)
            self.journal_service = JournalService(self.config)
            
            # 觀察清單服務初始化（可能失敗，需要特別處理）
            try:
                self.watchlist_service = WatchlistService(self.config)
            except Exception as e:
                logger.error(f"初始化觀察清單服務失敗: {e}")
                # 創建一個空的服務實例，避免後續錯誤
                self.watchlist_service = None
                print(f"警告：觀察清單服務初始化失敗，將使用空服務: {e}")
            
            # 選股清單服務初始化（用於推薦結果自動創建選股清單）
            try:
                self.universe_service = UniverseService(self.config)
            except Exception as e:
                logger.error(f"初始化選股清單服務失敗: {e}")
                self.universe_service = None
                print(f"警告：選股清單服務初始化失敗: {e}")
            
            # 設置 UI
            self._setup_ui()
        except Exception as e:
            logger.error(f"初始化主窗口失敗: {e}")
            import traceback
            print(f"錯誤：初始化主窗口失敗\n{str(e)}\n\n詳細信息：\n{traceback.format_exc()}")
            raise
    
    def _setup_ui(self):
        """設置 UI"""
        print("[MainWindow] 開始設置 UI...")
        
        try:
            # 創建標籤頁
            tabs = QTabWidget()
            
            # 數據更新標籤
            print("[MainWindow] 創建數據更新視圖...")
            update_view = UpdateView(
                update_service=self.update_service,
                parent=self
            )
            tabs.addTab(update_view, "數據更新")
            print("[MainWindow] 數據更新視圖創建成功")
        
            # 市場觀察標籤頁（包含多個子標籤）
            print("[MainWindow] 創建市場觀察視圖...")
            market_tabs = QTabWidget()
            
            # 大盤指數標籤（放在最前面）
            print("[MainWindow] 創建大盤指數視圖...")
            market_regime = MarketRegimeView(
                regime_service=self.regime_service,
                parent=self
            )
            market_tabs.addTab(market_regime, "大盤指數")
            print("[MainWindow] 大盤指數視圖創建成功")
            
            # 強勢個股標籤
            print("[MainWindow] 創建強勢個股視圖...")
            strong_stocks = StrongStocksView(
                screening_service=self.screening_service,
                watchlist_service=self.watchlist_service,
                parent=self
            )
            market_tabs.addTab(strong_stocks, "強勢個股")
            print("[MainWindow] 強勢個股視圖創建成功")
            
            # 弱勢個股標籤
            print("[MainWindow] 創建弱勢個股視圖...")
            weak_stocks = WeakStocksView(
                screening_service=self.screening_service,
                watchlist_service=self.watchlist_service,
                parent=self
            )
            market_tabs.addTab(weak_stocks, "弱勢個股")
            print("[MainWindow] 弱勢個股視圖創建成功")
            
            # 強勢產業標籤
            print("[MainWindow] 創建強勢產業視圖...")
            strong_industries = StrongIndustriesView(
                screening_service=self.screening_service,
                parent=self
            )
            market_tabs.addTab(strong_industries, "強勢產業")
            print("[MainWindow] 強勢產業視圖創建成功")
            
            # 弱勢產業標籤
            print("[MainWindow] 創建弱勢產業視圖...")
            weak_industries = WeakIndustriesView(
                screening_service=self.screening_service,
                parent=self
            )
            market_tabs.addTab(weak_industries, "弱勢產業")
            print("[MainWindow] 弱勢產業視圖創建成功")
            
            # 主力流向標籤 (Smart Money Flow)
            print("[MainWindow] 創建主力流向視圖...")
            smart_money_flow = SmartMoneyFlowView(
                broker_flow_service=self.broker_flow_service,
                watchlist_service=self.watchlist_service,
                parent=self
            )
            market_tabs.addTab(smart_money_flow, "主力流向")
            print("[MainWindow] 主力流向視圖創建成功")
        
            # 監聽市場觀察 tab 切換事件
            def on_market_tab_changed(index):
                """當市場觀察 tab 被點擊時，檢查是否需要載入數據"""
                if index == 0:  # 大盤指數（不需要自動載入，用戶點擊按鈕）
                    pass
                elif index == 1:  # 強勢個股
                    strong_stocks.load_data_if_needed()
                elif index == 2:  # 弱勢個股
                    weak_stocks.load_data_if_needed()
                elif index == 3:  # 強勢產業
                    strong_industries.load_data_if_needed()
                elif index == 4:  # 弱勢產業
                    weak_industries.load_data_if_needed()
                elif index == 5:  # 主力流向
                    smart_money_flow.load_data_if_needed()
            
            market_tabs.currentChanged.connect(on_market_tab_changed)
            
            tabs.addTab(market_tabs, "市場觀察")
            print("[MainWindow] 市場觀察標籤頁創建成功")
            
            # 監聽主 tab 切換事件（當切換到市場觀察時）
            def on_main_tab_changed(index):
                """當主 tab 切換時"""
                # 如果切換到市場觀察 tab（index=1），觸發子 tab 的載入檢查
                if index == 1:  # 市場觀察是第二個 tab（index 0 是數據更新）
                    current_sub_index = market_tabs.currentIndex()
                    on_market_tab_changed(current_sub_index)
            
            tabs.currentChanged.connect(on_main_tab_changed)

            # 每日決策分頁（失敗時降級，不影響整體啟動）
            print("[MainWindow] 開始建立每日決策分頁...")
            try:
                self.decision_desk_builder = self._create_decision_desk_builder()
                decision_desk_view = DecisionDeskView(
                    decision_desk_builder=self.decision_desk_builder,
                    parent=self,
                )
                tabs.addTab(decision_desk_view, "每日決策")
                print("[MainWindow] 每日決策分頁建立成功")
            except Exception as e:
                print(f"[MainWindow] 警告：每日決策分頁初始化失敗：{e}")
                fallback_tab = QLabel(f"每日決策初始化失敗，已降級顯示：{e}")
                fallback_tab.setWordWrap(True)
                tabs.addTab(fallback_tab, "每日決策")
            
            # 策略回測標籤（先創建，因為推薦分析需要引用它）
            print("[MainWindow] 創建策略回測視圖...")
            backtest = BacktestView(
                backtest_service=self.backtest_service,
                config=self.config,
                watchlist_service=self.watchlist_service,
                parent=self
            )
            tabs.addTab(backtest, "策略回測")
            print("[MainWindow] 策略回測視圖創建成功")
            
            # 推薦分析標籤
            print("[MainWindow] 創建推薦分析視圖...")
            recommendation = RecommendationView(
                recommendation_service=self.recommendation_service,
                regime_service=self.regime_service,
                watchlist_service=self.watchlist_service,
                config=self.config,
                universe_service=self.universe_service,
                parent=self
            )
            # 連接一鍵送回測信號（Phase 3.3）
            recommendation.sendToBacktestRequested.connect(
                lambda config: self._handle_send_to_backtest(backtest, config)
            )
            tabs.addTab(recommendation, "推薦分析")
            print("[MainWindow] 推薦分析視圖創建成功")
            
            # 觀察清單標籤（作為獨立 Tab，方便管理）
            # 只有在 watchlist_service 可用時才創建
            if self.watchlist_service is not None:
                try:
                    print("[MainWindow] 創建觀察清單視圖...")
                    watchlist = WatchlistView(
                        watchlist_service=self.watchlist_service,
                        config=self.config,
                        parent=self
                    )
                    watchlist_tab_index = tabs.addTab(watchlist, "觀察清單")
                    print("[MainWindow] 觀察清單視圖創建成功")
                    
                    # 當切換到觀察清單 Tab 時，自動刷新數據確保同步
                    def on_tab_changed_to_watchlist(index):
                        if index == watchlist_tab_index:
                            if hasattr(watchlist, 'refresh_all'):
                                watchlist.refresh_all()
                    
                    tabs.currentChanged.connect(on_tab_changed_to_watchlist)
                except Exception as e:
                    print(f"[MainWindow] 警告：無法創建觀察清單標籤: {e}")
                    import traceback
                    print(f"[MainWindow] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            else:
                print("[MainWindow] 觀察清單服務不可用，跳過觀察清單標籤")
            
            # 持倉管理標籤 (Portfolio MVP)
            try:
                print("[MainWindow] 創建持倉管理視圖...")
                from ui_qt.views.portfolio_view import PortfolioView
                portfolio_view = PortfolioView(
                    portfolio_service=self.portfolio_service,
                    journal_service=self.journal_service,
                    recommendation_service=self.recommendation_service,
                    broker_flow_service=self.broker_flow_service,
                    parent=self
                )
                portfolio_tab_index = tabs.addTab(portfolio_view, "持倉管理")
                print("[MainWindow] 持倉管理視圖創建成功")
                
                # 當切換到持倉管理 Tab 時，自動刷新
                def on_tab_changed_to_portfolio(index):
                    if index == portfolio_tab_index:
                        if hasattr(portfolio_view, 'refresh_all'):
                            portfolio_view.refresh_all()
                
                tabs.currentChanged.connect(on_tab_changed_to_portfolio)
            except Exception as pe:
                print(f"[MainWindow] 警告：無法創建持倉管理標籤: {pe}")
                import traceback
                print(f"[MainWindow] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            
            self.setCentralWidget(tabs)
            print("[MainWindow] UI 設置完成")
            
            # 保存 tabs 和 backtest 引用（用於一鍵送回測）
            self.tabs = tabs
            self.backtest_view = backtest
            self.smart_money_flow = smart_money_flow
            self.market_tabs = market_tabs
            
            # --- Runtime Observatory MVP Integration ---
            try:
                print("[MainWindow] 初始化 Runtime Observatory...")
                project_root_str = str(project_root)
                self.runtime_controller = RuntimeController(os.path.join(project_root_str, "runtime"))
                self.runtime_bridge = QtRuntimeBridge(self.runtime_controller.event_bus, self)
                
                self.runtime_view = RuntimeView(parent=self)
                
                # Connect bridge signals to view slots
                self.runtime_bridge.state_updated.connect(self.runtime_view.on_state_updated)
                self.runtime_bridge.health_updated.connect(self.runtime_view.on_health_updated)
                self.runtime_bridge.event_received.connect(self.runtime_view.on_event_received)
                
                tabs.addTab(self.runtime_view, "Runtime Observatory")
                
                # Setup polling timer
                self.runtime_timer = QTimer(self)
                self.runtime_timer.timeout.connect(self.runtime_controller.poll_updates)
                self.runtime_timer.start(1000) # Poll every 1 second
                print("[MainWindow] Runtime Observatory 整合完成")
            except Exception as re:
                print(f"[MainWindow] 警告: Runtime Observatory 初始化失敗: {re}")
            # --------------------------------------------
            
            # 狀態欄
            self.statusBar().showMessage("就緒")
            self.session_context_strip = SessionContextStrip(self.research_session_store, self)
            self.statusBar().addPermanentWidget(self.session_context_strip, 1)
        except Exception as e:
            print(f"[MainWindow] 錯誤：設置 UI 失敗")
            print(f"[MainWindow] 錯誤類型: {type(e).__name__}")
            print(f"[MainWindow] 錯誤訊息: {str(e)}")
            import traceback
            print(f"[MainWindow] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            raise
    
    def _handle_send_to_backtest(self, backtest_view: BacktestView, config: Dict[str, Any]):
        """處理一鍵送回測請求（Phase 3.3）
        
        Args:
            backtest_view: 回測視圖實例
            config: 回測配置（包含股票清單、策略配置等）
        """
        try:
            # 切換到回測標籤
            if hasattr(self, 'tabs'):
                # 找到回測標籤的索引
                for i in range(self.tabs.count()):
                    if self.tabs.widget(i) == backtest_view:
                        self.tabs.setCurrentIndex(i)
                        break
            
            # 調用回測視圖的方法來載入配置
            if hasattr(backtest_view, 'load_from_recommendation'):
                backtest_view.load_from_recommendation(config)
            else:
                # 如果方法不存在，顯示提示
                QMessageBox.information(
                    self,
                    "提示",
                    f"已切換到策略回測標籤\n\n"
                    f"股票清單：{len(config.get('stock_list', []))} 檔\n"
                    f"請手動配置回測參數。"
                )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self,
                "錯誤",
                f"一鍵送回測失敗：\n{str(e)}\n\n{traceback.format_exc()}"
            )
        except Exception as e:
            print(f"[MainWindow] 錯誤：設置 UI 失敗")
            print(f"[MainWindow] 錯誤類型: {type(e).__name__}")
            print(f"[MainWindow] 錯誤訊息: {str(e)}")
            import traceback
            print(f"[MainWindow] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            raise
    
    def show_smart_money_flow_for_stock(self, stock_code: str):
        """切換至市場觀察 -> 主力流向，並定位至該個股"""
        try:
            if hasattr(self, 'tabs') and hasattr(self, 'market_tabs'):
                for i in range(self.tabs.count()):
                    if self.tabs.widget(i) == self.market_tabs:
                        self.tabs.setCurrentIndex(i)
                        break
                if hasattr(self, 'smart_money_flow'):
                    for j in range(self.market_tabs.count()):
                        if self.market_tabs.widget(j) == self.smart_money_flow:
                            self.market_tabs.setCurrentIndex(j)
                            break
                    self.smart_money_flow.select_stock(stock_code)
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self,
                "下鑽錯誤",
                f"無法下鑽主力流向：\n{str(e)}\n\n{traceback.format_exc()}"
            )

    def closeEvent(self, event):
        """關閉事件"""
        # TODO: 清理資源
        event.accept()


def main():
    """主函數"""
    import traceback
    
    print("[Main] 開始啟動應用程序...")
    
    try:
        print("[Main] 正在創建 QApplication...")
        app = QApplication(sys.argv)
        print("[Main] QApplication 創建成功")
        
        # 設置應用程序 icon（必須在創建窗口之前設置）
        icon_path = Path(__file__).parent / 'app_icon.png'
        if icon_path.exists():
            icon_path_abs = icon_path.resolve()  # 使用絕對路徑
            app.setWindowIcon(QIcon(str(icon_path_abs)))
            print(f"[Main] 應用程序 icon 設置完成: {icon_path_abs}")
        else:
            print(f"[Main] 警告: Icon 檔案不存在: {icon_path}")
        
        # 設置應用程序樣式（可選）
        app.setStyle('Fusion')
        print("[Main] 應用程序樣式設置完成")
        
        # 創建主窗口
        try:
            print("[Main] 正在創建主窗口...")
            window = MainWindow()
            print("[Main] 主窗口創建成功")
            
            print("[Main] 正在顯示主窗口...")
            window.show()
            print("[Main] 主窗口顯示成功")
            
            print("[Main] 應用程序準備就緒，進入事件循環...")
        except Exception as e:
            print(f"[Main] 錯誤：創建主窗口失敗")
            print(f"[Main] 錯誤類型: {type(e).__name__}")
            print(f"[Main] 錯誤訊息: {str(e)}")
            print(f"[Main] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            return 1
        
        # 運行應用程序
        print("[Main] 開始運行應用程序事件循環...")
        exit_code = app.exec()
        print(f"[Main] 應用程序退出，退出碼: {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        print(f"[Main] 錯誤：應用程序啟動失敗")
        print(f"[Main] 錯誤類型: {type(e).__name__}")
        print(f"[Main] 錯誤訊息: {str(e)}")
        print(f"[Main] 詳細堆疊追蹤:\n{traceback.format_exc()}")
        return 1


if __name__ == '__main__':
    main()


