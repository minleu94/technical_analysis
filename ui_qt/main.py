"""
PySide6 主應用程式
"""

import os
import sys
from pathlib import Path

# 添加項目根目錄到系統路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ui_qt.crash_diagnostics import install_crash_diagnostics, record_exception


def _configure_console_streams() -> None:
    """讓 Windows 非 UTF-8 console 不會因為啟動訊息而中止 App。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # Console／test capture stream 可能不允許重新設定；啟動流程
            # 仍應繼續，真正的 exception 會由 crash diagnostics 記錄。
            continue


# 直接啟動桌面 App 時，在載入 Qt 與各服務前先裝上 crash hooks；單元測試匯入
# ui_qt.main 時不會碰觸正式 DATA_ROOT。
_crash_diagnostics_log_path: Path | None = None
if __name__ == "__main__":
    _configure_console_streams()
    try:
        _crash_diagnostics_log_path = install_crash_diagnostics()
    except Exception as diagnostics_error:
        print(f"[Main] 無法啟用 crash diagnostics: {diagnostics_error}")

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QMessageBox,
    QLabel,
    QWidget,
)
from typing import Dict, Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon

from data_module.config import TWStockConfig
from app_module.market_breadth_service import (
    MarketBreadthService,
    SQLiteDailyPriceMarketBreadthProvider,
)
from app_module.sector_rotation_service import (
    SectorRotationService,
    SQLiteIndustryIndexSectorRotationProvider,
)
from app_module.watchlist_trigger_service import (
    WatchlistTriggerService,
    WatchlistServiceWatchlistProvider,
    SQLiteRankingProvider,
)
from app_module.relative_strength_liquidity_service import (
    RelativeStrengthLiquidityService,
    SQLiteDailyPriceRelativeStrengthLiquidityProvider,
)
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
from app_module.smart_money_semantic_service import (
    SmartMoneySemanticService,
    SQLiteSmartMoneyPriceProvider,
)
from app_module.decision_market_frame import DecisionMarketFrameLoader
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder
from app_module.market_data_visibility_service import MarketDataVisibilityService
from ui_qt.views.decision_desk_view import DecisionDeskView
from app_module.workbench_source_service import WorkbenchSourceService
from app_module.research_console_source_service import ResearchConsoleSourceService
from app_module.engineering_closure_dashboard_service import (
    EngineeringClosureDashboardService,
    EvidenceRehearsalDashboard,
)
from ui_qt.views.workbench_view import UnifiedDecisionWorkbenchView
from ui_qt.theme import build_global_stylesheet
from ui_qt.theme.fonts import (
    preferred_qt_chinese_font_family,
    register_qt_chinese_fonts,
)
from ui_qt.widgets.left_navigation import LeftNavigationWidget, NavigationItem
from ui_qt.widgets.adaptive_workspace_stack import AdaptiveWorkspaceStack
from ui_qt.widgets.text_sanitizer import sanitize_button_texts
from ui_qt.main_window_coordinator import WORKSPACE_DEFINITIONS, resolve_workspace_key
from ui_qt.runtime_composition import build_runtime_ui_composition
from ui_qt.workers.task_worker import (
    request_cooperative_task_worker_shutdown,
)
from app_module.decision_desk_composition import (
    DecisionDeskMarketRegimeProvider,
    build_decision_desk_composition,
    build_smart_money_composition,
)
from app_module.decision_service_composition import build_decision_service_composition

# Runtime Observatory Imports
from app_module.runtime_services.runtime_controller import RuntimeController
from app_module.runtime_services.environment_readiness_service import (
    EnvironmentReadinessService,
)
from ui_qt.bridges.runtime_event_bridge import QtRuntimeBridge
from ui_qt.views.runtime_view import RuntimeView
from PySide6.QtCore import QTimer


def apply_app_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    loaded_families = register_qt_chinese_fonts()
    preferred_family = preferred_qt_chinese_font_family(loaded_families)
    if preferred_family:
        font = QFont(preferred_family, app.font().pointSize())
        app.setFont(font)
    app.setStyleSheet(build_global_stylesheet())


class MainWindow(QMainWindow):
    """主窗口"""

    # Keep a usable compact viewport while allowing the responsive navigation
    # and workspace pages to shrink below their desktop size hints.  The
    # previous implicit QMainWindow minimum could be inherited from whichever
    # page was active (Runtime was about 480--800 px wide), so a narrow-window
    # smoke probe was constrained before the navigation-collapse logic ran.
    RESPONSIVE_MIN_WIDTH = 320

    _DecisionDeskMarketRegimeProvider = DecisionDeskMarketRegimeProvider

    def _create_decision_desk_builder(self) -> DecisionDeskSnapshotBuilder:
        composition = build_decision_desk_composition(
            config=self.config,
            regime_service=self.regime_service,
            portfolio_service=self.portfolio_service,
            watchlist_service=self.watchlist_service,
            broker_flow_service=getattr(self, "broker_flow_service", None),
            smart_money_service=getattr(self, "smart_money_semantic_service", None),
            market_frame_loader=getattr(self, "decision_market_frame_loader", None),
            dependencies={
                "DecisionMarketFrameLoader": DecisionMarketFrameLoader,
                "MarketBreadthService": MarketBreadthService,
                "SQLiteDailyPriceMarketBreadthProvider": SQLiteDailyPriceMarketBreadthProvider,
                "SectorRotationService": SectorRotationService,
                "SQLiteIndustryIndexSectorRotationProvider": SQLiteIndustryIndexSectorRotationProvider,
                "PortfolioConditionMonitor": PortfolioConditionMonitor,
                "PortfolioChipService": PortfolioChipService,
                "PortfolioAlertService": PortfolioAlertService,
                "WatchlistServiceWatchlistProvider": WatchlistServiceWatchlistProvider,
                "SQLiteRankingProvider": SQLiteRankingProvider,
                "WatchlistTriggerService": WatchlistTriggerService,
                "SQLiteDailyPriceRelativeStrengthLiquidityProvider": SQLiteDailyPriceRelativeStrengthLiquidityProvider,
                "RelativeStrengthLiquidityService": RelativeStrengthLiquidityService,
                "DecisionDeskSnapshotBuilder": DecisionDeskSnapshotBuilder,
                "MarketDataVisibilityService": MarketDataVisibilityService,
            },
        )
        self.decision_market_frame_loader = composition.market_frame_loader
        return composition.builder

    def __init__(self):
        super().__init__()
        self.setWindowTitle("baldr")
        self.setGeometry(100, 100, 1400, 800)
        self._navigation_collapsed_by_window = False

        # 設置窗口 icon
        icon_path = Path(__file__).parent / "app_icon.png"
        if icon_path.exists():
            icon_path_abs = icon_path.resolve()  # 使用絕對路徑
            self.setWindowIcon(QIcon(str(icon_path_abs)))

        import logging

        logger = logging.getLogger(__name__)

        try:
            # 初始化配置和服務
            self.config = TWStockConfig()

            decision_services = build_decision_service_composition(config=self.config)
            self.screening_service = decision_services.screening_service
            self.regime_service = decision_services.regime_service
            self.recommendation_service = decision_services.recommendation_service
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
            self.setMinimumWidth(self.RESPONSIVE_MIN_WIDTH)
        except Exception as e:
            logger.error(f"初始化主窗口失敗: {e}")
            import traceback

            print(
                f"錯誤：初始化主窗口失敗\n{str(e)}\n\n詳細信息：\n{traceback.format_exc()}"
            )
            raise

    def _default_workbench_replay_summary_path(self) -> Path | None:
        output_root = getattr(self.config, "output_root", None)
        if output_root is None:
            return None
        candidate = (
            Path(output_root)
            / "evidence_pipeline"
            / "historical_replay_reference_fix_20260706"
            / "historical_replay_2026-01-06_2026-07-06_reference_fix.json"
        )
        return candidate if candidate.exists() else None

    def _research_console_projection_path(self) -> Path | None:
        """只接受顯式 sanitized projection；不掃描 development 或正式資料目錄。"""
        configured_path = os.environ.get("RESEARCH_CONSOLE_PROJECTION")
        return Path(configured_path).expanduser().resolve() if configured_path else None

    def _p0_source_audit_path(self) -> Path | None:
        """只接受顯式 P0 audit artifact；不掃描正式資料或 QA 目錄。"""
        configured_path = os.environ.get("P0_SOURCE_CONTROL_CENTER_AUDIT")
        return Path(configured_path).expanduser().resolve() if configured_path else None

    def _p0_source_decision_path(self) -> Path | None:
        """只接受顯式 P0 owner decision artifact；不掃描正式資料或 QA 目錄。"""
        configured_path = os.environ.get("P0_SOURCE_CONTROL_CENTER_DECISIONS")
        return Path(configured_path).expanduser().resolve() if configured_path else None

    def _data_update_status_path(self) -> Path | None:
        """資料更新時間軸只讀取明確 artifact；未設定時使用固定排程出口。"""
        configured_path = os.environ.get("DATA_UPDATE_STATUS_ARTIFACT")
        if configured_path:
            return Path(configured_path).expanduser().resolve()
        output_root = getattr(self.config, "output_root", None)
        if output_root is None:
            return None
        return (
            Path(output_root)
            / "scheduled"
            / "data_update_quick"
            / "latest_status.json"
        ).resolve()

    def _data_freshness_status_path(self) -> Path | None:
        """資料 freshness 時間軸出口；不搜尋其他 latest_status。"""
        configured_path = os.environ.get("DATA_FRESHNESS_STATUS_ARTIFACT")
        if configured_path:
            return Path(configured_path).expanduser().resolve()
        output_root = getattr(self.config, "output_root", None)
        if output_root is None:
            return None
        return (
            Path(output_root)
            / "scheduled"
            / "data_freshness"
            / "latest_status.json"
        ).resolve()

    def _tpex_status_path(self) -> Path | None:
        """TPEX 背景流程狀態出口；只使用固定 meta_data 檔案。"""
        configured_path = os.environ.get("TPEX_REFRESH_STATUS_ARTIFACT")
        if configured_path:
            return Path(configured_path).expanduser().resolve()
        meta_data_dir = getattr(self.config, "meta_data_dir", None)
        if meta_data_dir is None:
            data_root = getattr(self.config, "data_root", None)
            if data_root is None:
                return None
            meta_data_dir = Path(data_root) / "meta_data"
        return (Path(meta_data_dir) / "tpex_full_refresh_status.json").resolve()

    def _controlled_rehearsal_dashboard(self) -> EvidenceRehearsalDashboard | None:
        """Read an explicitly configured controlled report without opening any database."""
        configured_path = os.environ.get("EVIDENCE_REHEARSAL_REPORT")
        if not configured_path:
            return None
        try:
            return EngineeringClosureDashboardService().load_rehearsal_report(
                Path(configured_path)
            )
        except ValueError as error:
            return EvidenceRehearsalDashboard(
                tier="engineering_fixture",
                status="blocked",
                coverage=(),
                blockers=(f"controlled_rehearsal_report_unavailable:{error}",),
            )

    def _select_main_workspace(self, key_or_label: str) -> None:
        workspace_stack = getattr(self, "workspace_stack", None)
        workspace_widgets = getattr(self, "workspace_widgets", {})
        if workspace_stack is None:
            return
        key = resolve_workspace_key(key_or_label)
        widget = workspace_widgets.get(key)
        if widget is None:
            return
        workspace_stack.setCurrentWidget(widget)
        left_navigation = getattr(self, "left_navigation", None)
        if left_navigation is not None:
            left_navigation.set_current_key(key)
        self._on_workspace_selected(key)

    def _select_main_tab(self, tab_name: str) -> None:
        self._select_main_workspace(tab_name)

    def _open_workbench_daily_decision(self) -> None:
        self._open_workbench_market_explore()

    def _open_workbench_market_explore(self) -> None:
        self._select_main_workspace("market_explore")
        market_tabs = getattr(self, "market_tabs", None)
        decision_desk_view = getattr(self, "decision_desk_view", None)
        if market_tabs is not None and decision_desk_view is not None:
            market_tabs.setCurrentWidget(decision_desk_view)

    def _open_workbench_evidence_review(self) -> None:
        self._select_main_workspace("backtest")
        backtest_view = getattr(self, "backtest_view", None)
        result_tabs = getattr(backtest_view, "result_tabs", None)
        if result_tabs is None:
            return
        for index in range(result_tabs.count()):
            if result_tabs.tabText(index) == "證據覆盤":
                result_tabs.setCurrentIndex(index)
                return

    def _open_workbench_portfolio(self) -> None:
        self._select_main_workspace("portfolio")

    def _on_workspace_selected(self, key: str) -> None:
        if key == "market_explore":
            market_tabs = getattr(self, "market_tabs", None)
            on_market_tab_changed = getattr(self, "_on_market_tab_changed", None)
            if market_tabs is not None and on_market_tab_changed is not None:
                on_market_tab_changed(market_tabs.currentIndex())
        elif key == "watchlist":
            watchlist = getattr(self, "watchlist_view", None)
            if hasattr(watchlist, "refresh_all"):
                watchlist.refresh_all()
        elif key == "portfolio":
            portfolio_view = getattr(self, "portfolio_view", None)
            if hasattr(portfolio_view, "refresh_all"):
                portfolio_view.refresh_all()

    def _setup_ui(self):
        """設置 UI"""
        print("[MainWindow] 開始設置 UI...")

        try:
            shell = QWidget()
            shell_layout = QHBoxLayout(shell)
            shell_layout.setContentsMargins(0, 0, 0, 0)
            shell_layout.setSpacing(0)
            workspace_stack = AdaptiveWorkspaceStack()
            workspace_widgets: dict[str, QWidget] = {}

            def add_workspace(key: str, widget: QWidget) -> int:
                workspace_widgets[key] = widget
                return workspace_stack.addWidget(widget)

            # 數據更新標籤
            print("[MainWindow] 創建數據更新視圖...")
            update_view = UpdateView(
                update_service=self.update_service,
                parent=self,
                p0_source_audit_path=self._p0_source_audit_path(),
                p0_source_decision_path=self._p0_source_decision_path(),
                data_update_status_path=self._data_update_status_path(),
                data_freshness_status_path=self._data_freshness_status_path(),
                tpex_status_path=self._tpex_status_path(),
            )
            self.update_view = update_view
            print("[MainWindow] 數據更新視圖創建成功")

            # 市場探索標籤頁（包含多個子標籤）
            print("[MainWindow] 創建市場探索視圖...")
            market_tabs = QTabWidget()

            # 大盤指數標籤（放在最前面）
            print("[MainWindow] 創建大盤指數視圖...")
            market_regime = MarketRegimeView(
                regime_service=self.regime_service, parent=self
            )
            market_tabs.addTab(market_regime, "大盤指數")
            print("[MainWindow] 大盤指數視圖創建成功")

            # 強勢個股標籤
            print("[MainWindow] 創建強勢個股視圖...")
            strong_stocks = StrongStocksView(
                screening_service=self.screening_service,
                watchlist_service=self.watchlist_service,
                parent=self,
            )
            market_tabs.addTab(strong_stocks, "強勢個股")
            print("[MainWindow] 強勢個股視圖創建成功")

            # 弱勢個股標籤
            print("[MainWindow] 創建弱勢個股視圖...")
            weak_stocks = WeakStocksView(
                screening_service=self.screening_service,
                watchlist_service=self.watchlist_service,
                parent=self,
            )
            market_tabs.addTab(weak_stocks, "弱勢個股")
            print("[MainWindow] 弱勢個股視圖創建成功")

            # 強勢產業標籤
            print("[MainWindow] 創建強勢產業視圖...")
            strong_industries = StrongIndustriesView(
                screening_service=self.screening_service, parent=self
            )
            market_tabs.addTab(strong_industries, "強勢產業")
            print("[MainWindow] 強勢產業視圖創建成功")

            # 弱勢產業標籤
            print("[MainWindow] 創建弱勢產業視圖...")
            weak_industries = WeakIndustriesView(
                screening_service=self.screening_service, parent=self
            )
            market_tabs.addTab(weak_industries, "弱勢產業")
            print("[MainWindow] 弱勢產業視圖創建成功")

            # 主力流向標籤 (Smart Money Flow)
            print("[MainWindow] 創建主力流向視圖...")
            smart_money_composition = build_smart_money_composition(
                config=self.config,
                broker_flow_service=self.broker_flow_service,
                market_frame_loader=getattr(self, "decision_market_frame_loader", None),
                dependencies={
                    "DecisionMarketFrameLoader": DecisionMarketFrameLoader,
                    "SQLiteSmartMoneyPriceProvider": SQLiteSmartMoneyPriceProvider,
                    "SmartMoneySemanticService": SmartMoneySemanticService,
                },
            )
            self.decision_market_frame_loader = smart_money_composition.market_frame_loader
            self.smart_money_semantic_service = smart_money_composition.service
            smart_money_flow = SmartMoneyFlowView(
                broker_flow_service=self.broker_flow_service,
                watchlist_service=self.watchlist_service,
                smart_money_semantic_service=self.smart_money_semantic_service,
                parent=self,
            )
            market_tabs.addTab(smart_money_flow, "主力流向")
            print("[MainWindow] 主力流向視圖創建成功")

            # 監聽市場觀察 tab 切換事件
            def on_market_tab_changed(index):
                """當市場觀察 tab 被點擊時，檢查是否需要載入數據"""
                current_widget = market_tabs.widget(index)
                if current_widget is strong_stocks:
                    strong_stocks.load_data_if_needed()
                elif current_widget is weak_stocks:
                    weak_stocks.load_data_if_needed()
                elif current_widget is strong_industries:
                    strong_industries.load_data_if_needed()
                elif current_widget is weak_industries:
                    weak_industries.load_data_if_needed()
                elif current_widget is smart_money_flow:
                    smart_money_flow.load_data_if_needed()

            market_tabs.currentChanged.connect(on_market_tab_changed)
            self._on_market_tab_changed = on_market_tab_changed
            print("[MainWindow] 市場探索標籤頁創建成功")

            # 市場總覽是 Decision Desk 的唯一實例，固定置於市場探索首頁。
            print("[MainWindow] 開始建立每日決策來源...")
            try:
                self.decision_desk_builder = self._create_decision_desk_builder()
                decision_desk_view = DecisionDeskView(
                    decision_desk_builder=self.decision_desk_builder,
                    navigate_to_smart_money_callback=self.show_smart_money_flow_for_stock,
                    parent=self,
                )
                self.decision_desk_view = decision_desk_view
                print("[MainWindow] 每日決策來源建立成功")
            except Exception as e:
                print(f"[MainWindow] 警告：每日決策來源初始化失敗：{e}")
                decision_desk_view = QLabel(f"每日決策初始化失敗，已降級顯示：{e}")
                decision_desk_view.setWordWrap(True)
                self.decision_desk_view = decision_desk_view

            market_tabs.insertTab(0, decision_desk_view, "市場總覽")
            market_tabs.setCurrentIndex(0)

            # Phase 2 Unified Decision Workbench shell（唯讀 DTO/service 邊界）
            print("[MainWindow] 開始建立決策工作台...")
            try:
                self.workbench_source_service = WorkbenchSourceService(self.config)
                self.research_console_source_service = ResearchConsoleSourceService(
                    projection_path=self._research_console_projection_path(),
                    p0_audit_path=self._p0_source_audit_path(),
                    p0_decision_path=self._p0_source_decision_path(),
                )
                workbench_view = UnifiedDecisionWorkbenchView(
                    source_service=self.workbench_source_service,
                    research_console_source_service=self.research_console_source_service,
                    replay_summary_json=self._default_workbench_replay_summary_path(),
                    evidence_rehearsal_dashboard=self._controlled_rehearsal_dashboard(),
                    navigate_to_daily_decision_callback=self._open_workbench_daily_decision,
                    navigate_to_market_explore_callback=self._open_workbench_market_explore,
                    navigate_to_evidence_review_callback=self._open_workbench_evidence_review,
                    navigate_to_portfolio_callback=self._open_workbench_portfolio,
                    navigate_to_update_callback=lambda: self._select_main_workspace("update"),
                    navigate_to_recommendation_callback=lambda: self._select_main_workspace("recommendation"),
                    auto_refresh=True,
                    parent=self,
                )
                self.workbench_view = workbench_view
                print("[MainWindow] 決策工作台建立成功")
            except Exception as e:
                print(f"[MainWindow] 警告：決策工作台初始化失敗：{e}")
                workbench_view = QLabel(f"決策工作台初始化失敗，已降級顯示：{e}")
                workbench_view.setWordWrap(True)
                self.workbench_view = workbench_view

            # 策略回測標籤（先創建，因為推薦分析需要引用它）
            print("[MainWindow] 創建策略回測視圖...")
            backtest = BacktestView(
                backtest_service=self.backtest_service,
                config=self.config,
                watchlist_service=self.watchlist_service,
                parent=self,
            )
            self.backtest_view = backtest
            print("[MainWindow] 策略回測視圖創建成功")

            # 推薦分析標籤
            print("[MainWindow] 創建推薦分析視圖...")
            recommendation = RecommendationView(
                recommendation_service=self.recommendation_service,
                regime_service=self.regime_service,
                watchlist_service=self.watchlist_service,
                config=self.config,
                universe_service=self.universe_service,
                parent=self,
            )
            # 連接一鍵送回測信號（Phase 3.3）
            recommendation.sendToBacktestRequested.connect(
                lambda config: self._handle_send_to_backtest(backtest, config)
            )
            self.recommendation_view = recommendation
            print("[MainWindow] 推薦分析視圖創建成功")

            # 觀察清單標籤（作為獨立 Tab，方便管理）
            # 只有在 watchlist_service 可用時才創建
            watchlist_widget: QWidget
            if self.watchlist_service is not None:
                try:
                    print("[MainWindow] 創建觀察清單視圖...")
                    watchlist = WatchlistView(
                        watchlist_service=self.watchlist_service,
                        config=self.config,
                        parent=self,
                    )
                    if hasattr(watchlist, "sendToBacktestRequested"):
                        watchlist.sendToBacktestRequested.connect(
                            lambda config: self._handle_send_to_backtest(backtest, config)
                        )
                    self.watchlist_view = watchlist
                    watchlist_widget = watchlist
                    print("[MainWindow] 觀察清單視圖創建成功")
                except Exception as e:
                    print(f"[MainWindow] 警告：無法創建觀察清單標籤: {e}")
                    import traceback

                    print(f"[MainWindow] 詳細堆疊追蹤:\n{traceback.format_exc()}")
                    watchlist_widget = QLabel(f"觀察清單初始化失敗，已降級顯示：{e}")
                    watchlist_widget.setWordWrap(True)
                    self.watchlist_view = watchlist_widget
            else:
                print("[MainWindow] 觀察清單服務不可用，跳過觀察清單標籤")
                watchlist_widget = QLabel("觀察清單服務不可用。")
                watchlist_widget.setWordWrap(True)
                self.watchlist_view = watchlist_widget

            # 持倉管理標籤 (Portfolio MVP)
            portfolio_widget: QWidget
            try:
                print("[MainWindow] 創建持倉管理視圖...")
                from ui_qt.views.portfolio_view import PortfolioView

                portfolio_view = PortfolioView(
                    portfolio_service=self.portfolio_service,
                    journal_service=self.journal_service,
                    recommendation_service=self.recommendation_service,
                    broker_flow_service=self.broker_flow_service,
                    parent=self,
                )
                self.portfolio_view = portfolio_view
                portfolio_widget = portfolio_view
                print("[MainWindow] 持倉管理視圖創建成功")
            except Exception as pe:
                print(f"[MainWindow] 警告：無法創建持倉管理標籤: {pe}")
                import traceback

                print(f"[MainWindow] 詳細堆疊追蹤:\n{traceback.format_exc()}")
                portfolio_widget = QLabel(f"持倉管理初始化失敗，已降級顯示：{pe}")
                portfolio_widget.setWordWrap(True)
                self.portfolio_view = portfolio_widget

            self.smart_money_flow = smart_money_flow
            self.market_tabs = market_tabs

            # --- Runtime Observatory MVP Integration ---
            runtime_widget: QWidget
            try:
                print("[MainWindow] 初始化 Runtime Observatory...")
                runtime_composition = build_runtime_ui_composition(
                    project_root=project_root,
                    parent=self,
                    scheduled_output_root=Path(self.config.output_root) / "scheduled",
                    dependencies={
                        "RuntimeController": RuntimeController,
                        "QtRuntimeBridge": QtRuntimeBridge,
                    "RuntimeView": RuntimeView,
                        "EnvironmentReadinessService": EnvironmentReadinessService,
                        "QTimer": QTimer,
                    },
                    environment_roots=(
                        Path(self.config.data_root),
                        Path(self.config.output_root),
                    ),
                )
                self.runtime_controller = runtime_composition.controller
                self.runtime_bridge = runtime_composition.bridge
                self.runtime_view = runtime_composition.view
                self.runtime_timer = runtime_composition.timer
                runtime_widget = runtime_composition.view
                print("[MainWindow] Runtime Observatory 整合完成")
            except Exception as re:
                print(f"[MainWindow] 警告: Runtime Observatory 初始化失敗: {re}")
                runtime_widget = QLabel(f"Runtime 初始化失敗，已降級顯示：{re}")
                runtime_widget.setWordWrap(True)
            # --------------------------------------------

            workspace_instances = {
                "workbench": workbench_view,
                "market_explore": market_tabs,
                "recommendation": recommendation,
                "backtest": backtest,
                "watchlist": watchlist_widget,
                "portfolio": portfolio_widget,
                "update": update_view,
                "runtime": runtime_widget,
            }
            for definition in WORKSPACE_DEFINITIONS:
                add_workspace(definition.key, workspace_instances[definition.key])

            workspace_items = tuple(
                NavigationItem(definition.key, definition.label, icon=definition.icon)
                for definition in WORKSPACE_DEFINITIONS
            )
            self.left_navigation = LeftNavigationWidget(workspace_items, parent=self)
            self.left_navigation.workspaceSelected.connect(self._select_main_workspace)
            shell_layout.addWidget(self.left_navigation)
            shell_layout.addWidget(workspace_stack, 1)

            self.workspace_stack = workspace_stack
            self.workspace_widgets = workspace_widgets
            self.tabs = workspace_stack
            self.left_navigation.set_current_key("workbench")
            self.workspace_stack.setCurrentWidget(workspace_widgets["workbench"])

            self.setCentralWidget(shell)
            print("[MainWindow] UI 設置完成")

            sanitize_button_texts(self)

            # 狀態欄
            self.statusBar().showMessage("就緒")
            self.session_context_strip = SessionContextStrip(
                self.research_session_store, self
            )
            self.statusBar().addPermanentWidget(self.session_context_strip, 1)
        except Exception as e:
            print(f"[MainWindow] 錯誤：設置 UI 失敗")
            print(f"[MainWindow] 錯誤類型: {type(e).__name__}")
            print(f"[MainWindow] 錯誤訊息: {str(e)}")
            import traceback

            print(f"[MainWindow] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            raise

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """在窄桌面視窗自動釋放導覽列空間，不覆寫使用者手動收合。"""

        super().resizeEvent(event)
        navigation = getattr(self, "left_navigation", None)
        if navigation is None:
            return

        if self.width() <= 1120:
            if not navigation.is_collapsed():
                navigation.set_collapsed(True)
                self._navigation_collapsed_by_window = True
            return

        if self.width() >= 1240 and self._navigation_collapsed_by_window:
            navigation.set_collapsed(False)
            self._navigation_collapsed_by_window = False

    def _handle_send_to_backtest(
        self, backtest_view: BacktestView, config: Dict[str, Any]
    ):
        """處理一鍵送回測請求（Phase 3.3）

        Args:
            backtest_view: 回測視圖實例
            config: 回測配置（包含股票清單、策略配置等）
        """
        try:
            # 切換到回測標籤
            self._select_main_workspace("backtest")

            # 調用回測視圖的方法來載入配置
            if hasattr(backtest_view, "load_from_recommendation"):
                backtest_view.load_from_recommendation(config)
            else:
                # 如果方法不存在，顯示提示
                QMessageBox.information(
                    self,
                    "提示",
                    f"已切換到策略回測標籤\n\n"
                    f"股票清單：{len(config.get('stock_list', []))} 檔\n"
                    f"請手動配置回測參數。",
                )
        except Exception as e:
            import traceback

            QMessageBox.critical(
                self, "錯誤", f"一鍵送回測失敗：\n{str(e)}\n\n{traceback.format_exc()}"
            )
        except Exception as e:
            print(f"[MainWindow] 錯誤：設置 UI 失敗")
            print(f"[MainWindow] 錯誤類型: {type(e).__name__}")
            print(f"[MainWindow] 錯誤訊息: {str(e)}")
            import traceback

            print(f"[MainWindow] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            raise

    def show_smart_money_flow_for_stock(self, stock_code: str):
        """切換至市場探索 -> 主力流向，並定位至該個股"""
        try:
            self._select_main_workspace("market_explore")
            if hasattr(self, "market_tabs") and hasattr(self, "smart_money_flow"):
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
                f"無法下鑽主力流向：\n{str(e)}\n\n{traceback.format_exc()}",
            )

    def closeEvent(self, event):
        """只在所有受管背景工作安全結束後才允許關閉。"""
        remaining_workers = request_cooperative_task_worker_shutdown()
        update_view = getattr(self, "update_view", None)
        background_process_running = bool(
            update_view is not None
            and getattr(
                update_view,
                "has_running_background_process",
                lambda: False,
            )()
        )
        if remaining_workers or background_process_running:
            parts: list[str] = []
            if remaining_workers:
                parts.append(f"{len(remaining_workers)} 個合作式取消中的背景工作")
            if background_process_running:
                parts.append("TPEX 背景更新程序")
            self.statusBar().showMessage(
                "已暫停關閉：" + "、".join(parts) + "。工作安全結束後請再次關閉。",
                10_000,
            )
            event.ignore()
            return
        event.accept()


def main():
    """主函數"""
    import traceback

    _configure_console_streams()
    print("[Main] 開始啟動應用程序...")
    if _crash_diagnostics_log_path is not None:
        print(f"[Main] Crash diagnostics: {_crash_diagnostics_log_path}")

    try:
        print("[Main] 正在創建 QApplication...")
        app = QApplication(sys.argv)
        print("[Main] QApplication 創建成功")

        # 設置應用程序 icon（必須在創建窗口之前設置）
        icon_path = Path(__file__).parent / "app_icon.png"
        if icon_path.exists():
            icon_path_abs = icon_path.resolve()  # 使用絕對路徑
            app.setWindowIcon(QIcon(str(icon_path_abs)))
            print(f"[Main] 應用程序 icon 設置完成: {icon_path_abs}")
        else:
            print(f"[Main] 警告: Icon 檔案不存在: {icon_path}")

        # 設置應用程序樣式（可選）
        apply_app_theme(app)
        print("[Main] Midnight Analyst 樣式設置完成")

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
            record_exception("main_window_initialization", e)
            print(f"[Main] 錯誤：創建主窗口失敗")
            print(f"[Main] 錯誤類型: {type(e).__name__}")
            print(f"[Main] 錯誤訊息: {str(e)}")
            print(f"[Main] 詳細堆疊追蹤:\n{traceback.format_exc()}")
            return 1

        # 運行應用程序
        print("[Main] 開始運行應用程序事件循環...")
        exit_code = app.exec()
        print(f"[Main] 應用程序退出，退出碼: {exit_code}")
        return int(exit_code)
    except Exception as e:
        record_exception("application_startup", e)
        print(f"[Main] 錯誤：應用程序啟動失敗")
        print(f"[Main] 錯誤類型: {type(e).__name__}")
        print(f"[Main] 錯誤訊息: {str(e)}")
        print(f"[Main] 詳細堆疊追蹤:\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
