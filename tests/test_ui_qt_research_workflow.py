import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# 設定為 offscreen 以免開啟實際 GUI 視窗
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidgetItem, QDialog
from PySide6.QtCore import Qt, QDate
import pytest
import pandas as pd

from ui_qt.views.backtest_view import BacktestView
from ui_qt.views.recommendation_view import RecommendationView
from ui_qt.views.watchlist_view import WatchlistView
from ui_qt.models.pandas_table_model import PandasTableModel
from app_module.dtos import BacktestReportDTO, RecommendationDTO, RecommendationResultDTO


def app():
    """獲取或建立 QApplication 實例"""
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


@pytest.fixture
def qt_app():
    return app()


def test_backtest_view_correct_history_run_binding(qt_app):
    """驗證歷史回測載入後，current_run_id 和 current_run_params 是否正確綁定"""
    # 建立 mock 服務與 repository
    mock_backtest_service = MagicMock()
    mock_run_repo = MagicMock()

    # 設定模擬歷史回測數據
    run_data = {
        "run_id": "run_test_123",
        "run_name": "TSMC Test Run",
        "stock_code": "2330",
        "start_date": "2026-01-01",
        "end_date": "2026-06-01",
        "strategy_id": "momentum_aggressive_v1",
        "strategy_params": {"atr_len": 14},
        "capital": 1000000.0,
        "fee_bps": 14.25,
        "slippage_bps": 5.0,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 15.0,
        "total_return": 0.25,
        "annual_return": 0.50,
        "sharpe_ratio": 1.8,
        "max_drawdown": 0.10,
        "win_rate": 0.60,
        "total_trades": 12,
        "trade_list": pd.DataFrame(columns=["股票代號", "交易日期", "買賣", "價格", "數量"])
    }
    mock_run_repo.load_run_data.return_value = run_data

    # 實例化 BacktestView
    view = BacktestView(backtest_service=mock_backtest_service, config=None)
    view.run_repository = mock_run_repo

    # 1. 測試 _load_run_and_switch_tab
    view._load_run_and_switch_tab("run_test_123")
    assert view.current_run_id == "run_test_123"
    assert view.current_run_params["stock_code"] == "2330"
    assert view.current_run_params["strategy_id"] == "momentum_aggressive_v1"
    assert view.current_run_params["capital"] == 1000000.0

    # 2. 測試 _load_history_run
    item = QListWidgetItem("TSMC Test Run")
    item.setData(Qt.UserRole, "run_test_456")
    
    run_data_2 = run_data.copy()
    run_data_2["run_id"] = "run_test_456"
    run_data_2["stock_code"] = "2454"  # 聯發科
    mock_run_repo.load_run_data.return_value = run_data_2

    view._load_history_run(item)
    assert view.current_run_id == "run_test_456"
    assert view.current_run_params["stock_code"] == "2454"


def test_backtest_view_preserves_provenance_on_portfolio_recording(qt_app):
    """驗證從回測交易記錄到 Portfolio 時，會保留正確的來源與 metadata"""
    mock_backtest_service = MagicMock()
    mock_run_repo = MagicMock()
    mock_portfolio_service = MagicMock()
    
    # 建立 mock main_window
    mock_main_window = MagicMock()
    mock_main_window.portfolio_service = mock_portfolio_service

    view = BacktestView(backtest_service=mock_backtest_service, config=None)
    view.run_repository = mock_run_repo
    # 讓 self.window() 回傳 mock_main_window
    view.window = MagicMock(return_value=mock_main_window)

    # 模擬當前回測 run 參數
    view.current_run_id = "run_test_888"
    view.current_run_params = {
        "stock_code": "2330",
        "strategy_id": "momentum_aggressive_v1",
        "run_name": "TSMC Momentum Run"
    }
    mock_report = MagicMock()
    mock_report.validation_status.value = "PASS"
    view.current_report = mock_report

    # 設定模擬交易明細表格數據（使用真實的 PandasTableModel 以符合 PySide6 型態要求）
    trade_df = pd.DataFrame([
        {"stock_code": "2330", "stock_name": "台積電", "side": "buy", "date": "2026-06-04", "price": 900.0, "quantity": 1000}
    ])
    view.trades_model = PandasTableModel(trade_df)
    view.trades_table.setModel(view.trades_model)
    
    # 選中第一列
    mock_index = MagicMock()
    mock_index.isValid.return_value = True
    mock_index.row.return_value = 0
    view.trades_table.currentIndex = MagicMock(return_value=mock_index)

    # Mock dialog 和 QMenu
    trade_dialog_data = {
        "stock_code": "2330",
        "stock_name": "台積電",
        "side": "buy",
        "quantity": 1000,
        "price": 900.0,
        "trade_date": "2026-06-04",
        "fees": 120.0,
        "taxes": 0.0,
        "notes": "來自回測"
    }

    # 我們直接 patch ui_qt.views.backtest_view 中的 QMenu
    with patch("ui_qt.views.backtest_view.QMenu") as MockQMenu, \
         patch("ui_qt.views.portfolio_view.AddTradeDialog") as MockDialog, \
         patch("ui_qt.views.backtest_view.QMessageBox") as MockMessageBox:
        
        # 模擬實例化的 QMenu
        mock_menu = MagicMock()
        MockQMenu.return_value = mock_menu
        
        mock_action = MagicMock()
        mock_menu.addAction.return_value = mock_action
        
        # 讓 exec 回傳對應的 action，這樣會通過 if action == action_add_portfolio:
        mock_menu.exec.return_value = mock_action
        
        # 模擬對話框確認並回傳數據
        mock_dialog_inst = MagicMock()
        mock_dialog_inst.exec.return_value = QDialog.Accepted
        mock_dialog_inst.get_trade_data.return_value = trade_dialog_data
        MockDialog.return_value = mock_dialog_inst

        # 觸發右鍵選單 callback
        view._show_trades_table_context_menu(None)

        # 驗證 record_trade 被正確呼叫，並檢查 provenance metadata
        mock_portfolio_service.record_trade.assert_called_once()
        args, kwargs = mock_portfolio_service.record_trade.call_args
        
        assert kwargs["stock_code"] == "2330"
        assert kwargs["source_type"] == "backtest_run"
        assert kwargs["source_id"] == "run_test_888"
        assert kwargs["source_summary"]["strategy_id"] == "momentum_aggressive_v1"
        assert kwargs["source_summary"]["validation_status"] == "PASS"
        assert kwargs["source_summary"]["run_name"] == "TSMC Momentum Run"
        assert kwargs["notes"] == "來自回測"


def test_backtest_view_explains_empty_trade_list(qt_app):
    """回測沒有完成交易時，摘要要明確告知交易明細不可記錄到 Portfolio。"""
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)

    report = BacktestReportDTO(
        total_return=0.0,
        annual_return=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        win_rate=0.0,
        total_trades=0,
        expectancy=0.0,
        details={
            "stock_code": "2330",
            "start_date": "2025-01-02",
            "end_date": "2026-06-01",
            "strategy_id": "momentum_aggressive_v1",
            "trade_list": pd.DataFrame(),
            "equity_curve": pd.DataFrame(),
        },
    )

    view._on_backtest_finished(report)

    assert "單股回測交易次數為 0，無法記錄交易" in view.summary_text.toPlainText()
    assert view.trades_table.model() is None


def test_backtest_view_uses_optimization_fixed_values_when_enabled(qt_app):
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)

    strategy_index = view.strategy_combo.findData("momentum_aggressive_v1")
    assert strategy_index >= 0
    view.strategy_combo.setCurrentIndex(strategy_index)
    view._on_strategy_changed()

    assert view._get_strategy_params()["buy_score"] == 70

    view.optimization_group.setChecked(True)
    view._on_optimization_toggled(True)
    view.optimization_param_widgets["buy_score"]["fixed"].setValue(50)
    view.optimization_param_widgets["sell_score"]["fixed"].setValue(40)

    params = view._get_strategy_params()

    assert params["buy_score"] == 50
    assert params["sell_score"] == 40


def test_recommendation_view_preserves_provenance_on_portfolio_recording(qt_app):
    """驗證推薦結果記錄到 Portfolio 時，會保留推薦來源、分數、理由、Profile 等 metadata"""
    mock_rec_service = MagicMock()
    mock_regime_service = MagicMock()
    mock_portfolio_service = MagicMock()
    
    mock_main_window = MagicMock()
    mock_main_window.portfolio_service = mock_portfolio_service

    # 實例化 RecommendationView，傳入 regime_service 避免 TypeError
    view = RecommendationView(
        recommendation_service=mock_rec_service,
        regime_service=mock_regime_service
    )
    view.window = MagicMock(return_value=mock_main_window)

    # 模擬當前推薦狀態
    view.current_result_id = "rec_test_777"
    view.current_result_name = "短線暴衝推薦"
    view.current_result_created_at = "2026-06-04T12:00:00"
    view.current_config = {
        "profile_id": "aggressive_short",
        "profile_version": "1.2",
        "regime_snapshot": {"regime": "trend", "confidence": 0.85}
    }
    view.current_profile = "aggressive_short"

    # 設定模擬推薦資料 DTO（使用正確的 RecommendationDTO 屬性）
    rec_dto = RecommendationDTO(
        stock_code="2330",
        stock_name="台積電",
        close_price=900.0,
        price_change=15.0,
        total_score=85.0,
        indicator_score=80.0,
        pattern_score=90.0,
        volume_score=85.0,
        recommendation_reasons="量能放大；均線多頭",
        industry="半導體",
        regime_match=True
    )
    view.current_recommendations = [rec_dto]

    # 設定結果表格數據（使用真實的 PandasTableModel 以符合 PySide6 型態要求）
    rec_df = pd.DataFrame([
        {"證券代號": "2330", "證券名稱": "台積電", "總分": 85.0}
    ])
    view.recommendations_model = PandasTableModel(rec_df)
    view.results_table.setModel(view.recommendations_model)

    # 選中第一列
    mock_index = MagicMock()
    mock_index.isValid.return_value = True
    mock_index.row.return_value = 0
    view.results_table.currentIndex = MagicMock(return_value=mock_index)

    # Mock dialog 和 QMenu
    trade_dialog_data = {
        "stock_code": "2330",
        "stock_name": "台積電",
        "side": "buy",
        "quantity": 500,
        "price": 905.0,
        "trade_date": "2026-06-04",
        "fees": 150.0,
        "taxes": 0.0,
        "notes": "來自推薦"
    }

    # 我們直接 patch ui_qt.views.recommendation_view 中的 QMenu
    with patch("ui_qt.views.recommendation_view.QMenu") as MockQMenu, \
         patch("ui_qt.views.portfolio_view.AddTradeDialog") as MockDialog, \
         patch("ui_qt.views.recommendation_view.QMessageBox") as MockMessageBox:
        
        mock_menu = MagicMock()
        MockQMenu.return_value = mock_menu
        
        mock_action = MagicMock()
        mock_menu.addAction.return_value = mock_action
        mock_menu.exec.return_value = mock_action
        
        mock_dialog_inst = MagicMock()
        mock_dialog_inst.exec.return_value = QDialog.Accepted
        mock_dialog_inst.get_trade_data.return_value = trade_dialog_data
        MockDialog.return_value = mock_dialog_inst

        # 觸發右鍵選單 callback
        view._show_results_table_context_menu(None)

        # 驗證 record_trade 被呼叫
        mock_portfolio_service.record_trade.assert_called_once()
        args, kwargs = mock_portfolio_service.record_trade.call_args
        
        assert kwargs["stock_code"] == "2330"
        assert kwargs["source_type"] == "recommendation_result"
        assert kwargs["source_id"] == "rec_test_777"
        assert kwargs["source_summary"]["profile_id"] == "aggressive_short"
        assert kwargs["source_summary"]["regime"] == "trend"
        assert kwargs["source_summary"]["total_score"] == 85.0
        assert "量能放大" in kwargs["source_summary"]["reasons"]
        assert kwargs["notes"] == "來自推薦"


def test_watchlist_view_batch_backtest_button_state(qt_app):
    """驗證候選池（Watchlist）之「送 Research Lab 批次回測」按鈕存在且預設為 disabled 提示"""
    mock_watchlist_service = MagicMock()
    mock_watchlist_service.get_watchlist.return_value = pd.DataFrame(columns=['證券代號', '證券名稱', '加入時間', '來源', '備註'])
    
    view = WatchlistView(watchlist_service=mock_watchlist_service, config=None)
    
    assert hasattr(view, "send_to_research_lab_btn")
    assert view.send_to_research_lab_btn.text() == "送 Research Lab 批次回測"
    assert view.send_to_research_lab_btn.isEnabled() is False
    assert "此入口將在 Research Lab 批次回測整合時啟用。" in view.send_to_research_lab_btn.toolTip()
