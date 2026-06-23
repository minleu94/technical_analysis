import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# 設定為 offscreen 以免開啟實際 GUI 視窗
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidgetItem, QDialog, QComboBox
from PySide6.QtCore import Qt, QDate
import pytest
import pandas as pd

from ui_qt.views.backtest_view import BacktestView
from ui_qt.views.recommendation_view import RecommendationView
from ui_qt.views.watchlist_view import WatchlistView
from ui_qt.models.pandas_table_model import PandasTableModel
from app_module.dtos import BacktestReportDTO, RecommendationDTO, RecommendationResultDTO
from app_module.optimizer_service import ParamRange
from data_module.config import TWStockConfig


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


def test_backtest_view_zero_trade_diagnostics_modes(qt_app):
    """驗證無交易時，fixed 模式與 quantile 模式能給出正確的診斷建議文案"""
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)

    # 1. 測試 quantile 模式的診斷建議
    report_quantile = BacktestReportDTO(
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
            "score_diagnostics": {
                "threshold_mode": "quantile",
                "buy_quantile_bp": 8000,
                "sell_quantile_bp": 4000,
                "warmup_ready_days": 10,
                "total_days": 70,
                "buy_hit_days": 2,
                "sell_hit_days": 0,
                "quantile_warmup_observations": 60,
                "max_score": 75.0,
                "min_score": 30.0,
                "avg_score": 50.0
            }
        },
    )

    view._on_backtest_finished(report_quantile)
    summary_quantile = view.summary_text.toPlainText()
    assert "目前採用分位數門檻模式" in summary_quantile
    assert "暖機狀態：回測共 70 個交易日，其中 10 個交易日已完成暖機" in summary_quantile
    assert "動態買進門檻命中 2 天" in summary_quantile
    assert "降低「buy_quantile_bp」買入分位數基點" in summary_quantile
    assert "降低「buy_score」買入門檻" not in summary_quantile

    # 2. 測試 fixed 模式的診斷建議
    report_fixed = BacktestReportDTO(
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
            "score_diagnostics": {
                "threshold_mode": "fixed",
                "buy_score": 60.0,
                "max_score": 55.0,
                "min_score": 30.0,
                "avg_score": 45.0
            }
        },
    )

    view._on_backtest_finished(report_fixed)
    summary_fixed = view.summary_text.toPlainText()
    assert "本標的最高分未達買進門檻" in summary_fixed
    assert "降低「buy_score」買入門檻" in summary_fixed
    assert "目前採用分位數門檻模式" not in summary_fixed


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


def test_optimization_panel_exposes_worker_control_and_source_hint(qt_app):
    view = BacktestView(backtest_service=MagicMock(), config=None)

    assert hasattr(view.config_panel, "optimizer_worker_count")
    assert view.config_panel.optimizer_worker_count.minimum() == 1
    assert view.config_panel.optimizer_worker_count.maximum() == 8
    assert view.config_panel.optimizer_worker_count.value() == min(view.optimizer_service.max_workers, 8)

    hint_text = view.config_panel.optimizer_runtime_hint.text()
    assert "ThreadPool" in hint_text
    assert "SQLite" in hint_text
    assert "CSV" in hint_text


def test_optimization_preflight_message_explains_large_scan_boundary(qt_app):
    view = BacktestView(backtest_service=MagicMock(), config=None)
    view.config_panel.optimizer_worker_count.setValue(4)
    param_ranges = {
        "param": ParamRange("param", "int", [], min=1, max=80001, step=1),
    }

    message = view._build_optimization_preflight_message(param_ranges)

    assert "80,001" in message
    assert "4" in message
    assert "ThreadPool" in message
    assert "SQLite" in message
    assert "CSV" in message
    assert "取消" in message


def test_optimization_range_rows_have_stable_width_for_large_ranges(qt_app):
    view = BacktestView(backtest_service=MagicMock(), config=None)

    strategy_index = view.strategy_combo.findData("momentum_aggressive_v1")
    assert strategy_index >= 0
    view.strategy_combo.setCurrentIndex(strategy_index)
    view.optimization_group.setChecked(True)
    view._on_optimization_toggled(True)
    view._update_optimization_params_form()

    buy_score_widgets = view.optimization_param_widgets["buy_score"]
    buy_score_widgets["mode"].setCurrentText("範圍")

    assert buy_score_widgets["row_widget"].minimumWidth() >= 420
    assert buy_score_widgets["range"].minimumWidth() >= 300


def test_research_lab_mode_hint_explains_use_case_and_input_source(qt_app):
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)

    for index in range(view.research_lab_mode_combo.count()):
        view.research_lab_mode_combo.setCurrentIndex(index)
        hint = view.config_panel.research_lab_mode_hint.text()
        assert "適合" in hint
        assert "輸入來源" in hint


def test_strategy_research_mode_hint_explains_validation_and_upgrade_evidence(qt_app):
    view = BacktestView(backtest_service=MagicMock(), config=None)

    strategy_research_index = view.research_lab_mode_combo.findData("strategy_research")
    assert strategy_research_index >= 0
    view.research_lab_mode_combo.setCurrentIndex(strategy_research_index)

    hint = view.config_panel.research_lab_mode_hint.text()
    assert "策略模板" in hint
    assert "參數最佳化" in hint
    assert "Walk-forward" in hint
    assert "升級證據" in hint


def test_recommendation_replay_group_has_stable_width(qt_app, tmp_path):
    config = TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
    )
    view = BacktestView(backtest_service=MagicMock(), config=config)

    assert view.config_panel.recommendation_portfolio_group.minimumWidth() >= 420
    assert view.config_panel.portfolio_history_combo is not None
    assert view.config_panel.portfolio_history_combo.minimumWidth() >= 240


def test_portfolio_promotion_success_message_points_to_follow_up_entrypoint(qt_app):
    view = BacktestView(backtest_service=MagicMock(), config=None)

    message = view._build_portfolio_promotion_success_message("version-001", "run-001")

    assert "version-001" in message
    assert "run-001" in message
    assert "推薦分析" in message
    assert "Profile" in message
    assert "策略版本" in message


def test_research_lab_date_edits_use_calendar_popup_and_expected_defaults(qt_app):
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)

    today = QDate.currentDate()

    assert view.start_date.calendarPopup()
    assert view.end_date.calendarPopup()
    assert view.end_date.date() == today
    assert 360 <= view.start_date.date().daysTo(today) <= 371


def test_research_registry_refreshes_after_save_delete_and_promote(qt_app):
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)
    view._refresh_research_registry = MagicMock()

    view._on_research_run_saved("run-test-001")
    assert view._refresh_research_registry.call_count == 1
    assert not view.progress_label.isHidden()
    assert "已保存" in view.progress_label.text()
    assert "run-test-001" in view.progress_label.text()

    view._on_research_run_deleted("run-test-001")
    assert view._refresh_research_registry.call_count == 2
    assert "已刪除" in view.progress_label.text()

    view._on_strategy_version_promoted("version-test-001")
    assert view._refresh_research_registry.call_count == 3
    assert "已升級" in view.progress_label.text()
    assert "version-test-001" in view.progress_label.text()


def test_result_tabs_first_entry_refreshes_history_and_chart_once(qt_app, tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    view = BacktestView(backtest_service=MagicMock(), config=config)
    view._refresh_history = MagicMock()
    view._update_chart_run_combo = MagicMock()

    history_idx = next(
        i for i in range(view.result_tabs.count())
        if "歷史" in view.result_tabs.tabText(i)
    )
    chart_idx = next(
        i for i in range(view.result_tabs.count())
        if "圖表" in view.result_tabs.tabText(i)
    )

    view._on_result_tab_changed(history_idx)
    view._on_result_tab_changed(history_idx)
    view._on_result_tab_changed(chart_idx)
    view._on_result_tab_changed(chart_idx)

    assert view._refresh_history.call_count == 1
    assert view._update_chart_run_combo.call_count == 1


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
    """驗證觀察清單可以直接送 Research Lab 批次回測，且空清單時保持 disabled。"""
    mock_watchlist_service = MagicMock()
    mock_watchlist_service.get_stocks.return_value = [
        {
            "stock_code": "2330",
            "stock_name": "台積電",
            "added_at": "2026-06-22 09:00:00",
            "source": "manual",
            "notes": "",
        }
    ]
    mock_watchlist_service.get_stock_codes.return_value = ["2330"]

    view = WatchlistView(watchlist_service=mock_watchlist_service, config=None)
    emitted_configs = []
    view.sendToBacktestRequested.connect(lambda config: emitted_configs.append(config))

    assert hasattr(view, "send_to_research_lab_btn")
    assert view.send_to_research_lab_btn.text() == "送 Research Lab 批次回測"
    assert view.send_to_research_lab_btn.isEnabled() is True
    assert "將目前候選池送到策略回測的批次模式" in view.send_to_research_lab_btn.toolTip()

    with patch("ui_qt.views.watchlist_view.QMessageBox.information"):
        view.send_to_research_lab_btn.click()

    assert emitted_configs
    assert emitted_configs[0]["stock_list"] == ["2330"]
    assert emitted_configs[0]["profile_name"] == "觀察清單"
    assert emitted_configs[0]["source"] == "watchlist"

    mock_watchlist_service.get_stocks.return_value = []
    mock_watchlist_service.get_stock_codes.return_value = []
    view._load_watchlist()

    assert view.send_to_research_lab_btn.isEnabled() is False
    assert "候選池目前沒有股票" in view.send_to_research_lab_btn.toolTip()


def test_watchlist_view_manual_add_resolves_stock_name_and_rejects_unknown(qt_app):
    """手動新增時，空白名稱會自動查正式股票名稱；查不到時阻擋加入。"""
    mock_watchlist_service = MagicMock()
    mock_watchlist_service.get_stocks.return_value = []
    view = WatchlistView(watchlist_service=mock_watchlist_service, config=None)
    view._query_stock_names = MagicMock(return_value={"2330": "台積電"})

    assert view._resolve_manual_stock("2330", "") == ("2330", "台積電")
    assert view._resolve_manual_stock("2330", "  台積電自訂  ") == ("2330", "台積電自訂")
    assert view._resolve_manual_stock("999999", "") is None


def test_backtest_view_max_positions_uses_zero_as_unlimited(qt_app):
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)

    assert view.max_positions_input.minimum() == 0
    assert view.max_positions_input.value() == 0
    assert view.max_positions_input.specialValueText() == "無限制"

    view.max_positions_input.setValue(1)
    assert view.max_positions_input.value() == 1


def test_backtest_view_recommendation_portfolio_summary_warns_about_same_day_close(qt_app):
    """推薦回放摘要需明確揭露同日收盤成交與可成交性假設。"""
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)

    result = SimpleNamespace(
        summary={
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "total_trades": 0,
            "avg_holding_days": 0.0,
            "capital_used": 0.0,
            "stop_loss_exits": 0,
            "take_profit_exits": 0,
            "holding_period_exits": 0,
            "loss_trade_ratio": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "monte_carlo_p05_return": 0.0,
            "monte_carlo_p50_return": 0.0,
            "monte_carlo_p95_return": 0.0,
        },
        trades=pd.DataFrame(),
        equity_curve=pd.DataFrame(),
        improvement_hints=[],
        period_holdings_dataframe=lambda: pd.DataFrame(),
        stock_contribution_dataframe=lambda: pd.DataFrame(),
    )

    view._show_recommendation_portfolio_result(result)

    summary_text = view.portfolio_summary_text.toPlainText()
    assert "交易假設提醒" in summary_text
    assert "同日收盤成交" in summary_text
    assert "gap_risk" in summary_text


def test_batch_result_tab_explains_comparison_purpose(qt_app):
    """批次結果頁需說明排行榜與整體統計的判讀目的。"""
    view = BacktestView(
        backtest_service=MagicMock(),
        batch_backtest_service=MagicMock(),
        config=None,
    )

    text = view.result_panel.batch_interpretation_label.text()

    assert "比較目的" in text
    assert "排行榜" in text
    assert "正式策略判斷" in text


def test_train_test_summary_warns_when_oos_sample_is_low(qt_app):
    """Train-Test 結果需揭露 OOS 交易數不足時的可靠度限制。"""
    view = BacktestView(backtest_service=MagicMock(), config=None)
    result_data = {
        "mode": "split",
        "train_report": SimpleNamespace(
            total_return=0.12,
            annual_return=0.18,
            sharpe_ratio=1.4,
            max_drawdown=-0.16,
            win_rate=0.58,
            total_trades=18,
        ),
        "test_report": SimpleNamespace(
            total_return=0.08,
            annual_return=0.16,
            sharpe_ratio=1.1,
            max_drawdown=-0.7729,
            win_rate=1.0,
            total_trades=3,
        ),
    }

    with patch("ui_qt.views.backtest_view.QMessageBox.information"):
        view._on_walkforward_finished(result_data)

    summary_text = view.summary_text.toPlainText()
    assert "【樣本可靠度】" in summary_text
    assert "OOS 交易數: 3" in summary_text
    assert "樣本不足" in summary_text
    assert "100.00%" in summary_text


def test_walkforward_summary_warns_when_fold_sample_is_low(qt_app):
    """Walk-forward 結果需揭露 fold 與 OOS 樣本不足。"""
    view = BacktestView(backtest_service=MagicMock(), config=None)
    fold = SimpleNamespace(
        train_period=("2026-01-02", "2026-03-31"),
        test_period=("2026-04-01", "2026-04-30"),
        train_metrics={"sharpe_ratio": 1.5},
        test_metrics={"sharpe_ratio": 1.2, "total_return": 0.04, "total_trades": 4},
        degradation=0.2,
    )
    result_data = {
        "mode": "walkforward",
        "results": [fold, fold],
        "summary": {
            "total_folds": 2,
            "avg_train_sharpe": 1.5,
            "avg_test_sharpe": 1.2,
            "avg_degradation": 0.2,
            "consistency": 1.0,
        },
    }

    with patch("ui_qt.views.backtest_view.QMessageBox.information"):
        view._on_walkforward_finished(result_data)

    summary_text = view.summary_text.toPlainText()
    assert "【Walk-forward 樣本可靠度】" in summary_text
    assert "Fold 數: 2" in summary_text
    assert "OOS 交易數: 8" in summary_text
    assert "樣本不足" in summary_text


def test_backtest_view_threshold_mode_combobox_loading_and_toggling(qt_app):
    """驗證門檻模式下拉選單的載入、正常參數面板與最佳化面板的動態顯示/隱藏"""
    mock_backtest_service = MagicMock()
    view = BacktestView(backtest_service=mock_backtest_service, config=None)

    # 1. 切換策略至 momentum_aggressive_v1
    strategy_index = view.strategy_combo.findData("momentum_aggressive_v1")
    assert strategy_index >= 0
    view.strategy_combo.setCurrentIndex(strategy_index)
    view._on_strategy_changed()

    # 2. 驗證正常面板中 threshold_mode 控制元件是 QComboBox
    assert "threshold_mode" in view.param_widgets
    threshold_mode_widget = view.param_widgets["threshold_mode"]
    assert isinstance(threshold_mode_widget, QComboBox)
    assert threshold_mode_widget.currentText() == "固定門檻"
    assert threshold_mode_widget.currentData() == "fixed"
    assert "百分位排名會用決策日前可見的歷史分數分布" in threshold_mode_widget.toolTip()

    # 3. 驗證 fixed 模式下，分數門檻顯示，分位數門檻隱藏
    assert view.param_widgets["buy_score"].isHidden() is False
    assert view.param_widgets["sell_score"].isHidden() is False
    assert view.param_widgets["buy_quantile_bp"].isHidden() is True
    assert view.param_widgets["sell_quantile_bp"].isHidden() is True

    # 4. 切換為 quantile 模式，驗證顯示狀態反轉
    threshold_mode_widget.setCurrentText("百分位排名")
    assert view.param_widgets["buy_score"].isHidden() is True
    assert view.param_widgets["sell_score"].isHidden() is True
    assert view.param_widgets["buy_quantile_bp"].isHidden() is False
    assert view.param_widgets["sell_quantile_bp"].isHidden() is False
    assert view.param_widgets["buy_quantile_bp"].maximum() == 10000
    assert view.param_widgets["sell_quantile_bp"].maximum() == 10000
    assert view.param_widgets["quantile_warmup_observations"].minimum() == 60
    assert view.param_widgets["quantile_warmup_observations"].maximum() == 60
    assert "60 個交易日" in view.param_widgets["quantile_warmup_observations"].toolTip()

    # 5. 驗證最佳化面板
    view.optimization_group.setChecked(True)
    view._on_optimization_toggled(True)
    view._update_optimization_params_form()

    # 驗證最佳化面板中 threshold_mode 控制元件
    assert "threshold_mode" in view.optimization_param_widgets
    opt_widgets = view.optimization_param_widgets["threshold_mode"]
    assert opt_widgets["mode"].currentText() == "固定值"
    assert opt_widgets["mode"].isEnabled() is False  # Choice 不支援範圍最佳化
    assert isinstance(opt_widgets["fixed"], QComboBox)
    assert opt_widgets["fixed"].currentText() == "固定門檻"  # 預設為 fixed
    assert opt_widgets["fixed"].currentData() == "fixed"

    # 驗證最佳化面板的行隱藏顯示
    assert view.optimization_param_widgets["buy_score"]["row_widget"].isHidden() is False
    assert view.optimization_param_widgets["buy_quantile_bp"]["row_widget"].isHidden() is True

    # 切換最佳化面板的 threshold_mode 固定值至 quantile
    opt_widgets["fixed"].setCurrentText("百分位排名")
    assert view.optimization_param_widgets["buy_score"]["row_widget"].isHidden() is True
    assert view.optimization_param_widgets["buy_quantile_bp"]["row_widget"].isHidden() is False
    assert view.optimization_param_widgets["buy_quantile_bp"]["fixed"].maximum() == 10000
    warmup_widgets = view.optimization_param_widgets["quantile_warmup_observations"]
    assert warmup_widgets["mode"].isEnabled() is False
    assert warmup_widgets["fixed"].minimum() == 60
    assert warmup_widgets["fixed"].maximum() == 60


def test_recommendation_view_threshold_mode_combobox_loading_and_toggling(qt_app):
    """驗證推薦分析視圖門檻模式選單的載入與進階面板顯示聯動"""
    mock_rec_service = MagicMock()
    mock_regime_service = MagicMock()
    
    view = RecommendationView(
        recommendation_service=mock_rec_service,
        regime_service=mock_regime_service
    )
    
    # 預設為新手模式，切換為進階模式以顯示排名門檻控制項
    view.is_beginner_mode = False
    view._update_mode_ui()
    
    # 1. 驗證控制項存在
    assert hasattr(view, "threshold_mode_combo")
    assert hasattr(view, "min_percentile_bp_spin")
    assert hasattr(view, "min_universe_size_spin")
    assert hasattr(view, "ranking_method_combo")
    assert view.ranking_method_combo.currentText() == "最近名次法"
    
    # 2. 預設 fixed 模式下，百分位、母體與排名方法隱藏
    assert view.threshold_mode_combo.currentText() == "固定門檻"
    assert view.percentile_container.isHidden() is True
    assert view.universe_container.isHidden() is True
    assert view.method_container.isHidden() is True
    
    # 3. 切換為 quantile 百分位排名模式，驗證顯示狀態
    view.threshold_mode_combo.setCurrentText("百分位排名")
    assert view.percentile_container.isHidden() is False
    assert view.universe_container.isHidden() is False
    assert view.method_container.isHidden() is False
    
    # 4. 驗證配置收集
    view.min_percentile_bp_spin.setValue(85.5)
    view.min_universe_size_spin.setValue(30)
    
    config = view._collect_config()
    ranking = config.get("recommendation_ranking", {})
    assert ranking.get("threshold_mode") == "quantile"
    assert ranking.get("recommendation_min_percentile_bp") == 8550
    assert ranking.get("recommendation_min_universe_size") == 30
    assert ranking.get("recommendation_ranking_method") == "nearest_rank"
