import os
import sys
from unittest.mock import MagicMock

# 設定為 offscreen 以免開啟實際 GUI 視窗
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel
import pytest

from ui_qt.views.backtest_view import BacktestView, RESEARCH_LAB_MODES


def app():
    """獲取或建立 QApplication 實例"""
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


@pytest.fixture
def qt_app():
    return app()


def test_research_lab_mode_driven_ui_visibility(qt_app):
    """驗證選中不同實驗模式時，左側配置面板是否會動態顯示/隱藏/摺疊對應的 GroupBox"""
    mock_backtest_service = MagicMock()
    mock_preset_service = MagicMock()
    
    # 建立 view
    view = BacktestView(backtest_service=mock_backtest_service, config=None)
    
    # 手動模擬 preset_service、walkforward_service 等以啟用所有 GroupBox
    view.preset_service = mock_preset_service
    view.walkforward_service = MagicMock()
    view.optimizer_service = MagicMock()
    
    # 重新觸發一次 UI 初始化以反映 preset/wf 服務的啟用
    # 這裡我們手動重建或直接 Mock 屬性。在實際 `_setup_ui` 中，
    # 這些屬性如 strategy_preset_group, optimization_group, wf_group
    # 都已經在 setup_ui 時建立（因為 mock_preset_service 與 optimizer_service 是在 init 後才 assign，
    # 但在 test 環境下，如果 config=None，那 preset_service 就會是 None，
    # 所以在 view 實例化時 strategy_preset_group 會是 None。
    # 為了測試，我們可以直接手動將 Mock QGroupBox 塞入 view 以測試 _update_ui_state_by_mode）
    
    view.strategy_preset_group = MagicMock()
    view.input_source_group = MagicMock()
    view.stock_selection_container = MagicMock()
    view.risk_cost_group = MagicMock()
    view.sizing_group = MagicMock()
    view.position_mgmt_group = MagicMock()
    view.market_constraints_group = MagicMock()
    view.strategy_config_group = MagicMock()
    view.optimization_group = MagicMock()
    view.wf_group = MagicMock()
    view.recommendation_portfolio_group = MagicMock()
    view.stock_mode_combo = MagicMock()

    # 1. 測試單股回測 (single_stock)
    view._update_ui_state_by_mode("single_stock")
    view.strategy_preset_group.setVisible.assert_called_with(True)
    view.input_source_group.setVisible.assert_called_with(True)
    view.stock_selection_container.setVisible.assert_called_with(True)
    view.stock_mode_combo.setCurrentText.assert_called_with("單一股票")
    view.risk_cost_group.setVisible.assert_called_with(True)
    view.recommendation_portfolio_group.setVisible.assert_called_with(False)
    view.optimization_group.setVisible.assert_called_with(True)
    view.optimization_group.setChecked.assert_called_with(False)

    # 2. 測試批次股票回測 (batch_stock)
    view.stock_mode_combo.reset_mock()
    view.stock_selection_container.reset_mock()
    view._update_ui_state_by_mode("batch_stock")
    view.input_source_group.setVisible.assert_called_with(True)
    view.stock_selection_container.setVisible.assert_called_with(True)
    view.stock_mode_combo.setCurrentText.assert_called_with("選股清單")
    view.recommendation_portfolio_group.setVisible.assert_called_with(False)
    view.optimization_group.setVisible.assert_called_with(False)

    # 3. 測試推薦系統回放 (recommendation_replay)
    view.stock_selection_container.reset_mock()
    view._update_ui_state_by_mode("recommendation_replay")
    view.input_source_group.setVisible.assert_called_with(True)
    view.stock_selection_container.setVisible.assert_called_with(False)
    view.strategy_preset_group.setVisible.assert_called_with(False)
    view.risk_cost_group.setVisible.assert_called_with(False)
    view.recommendation_portfolio_group.setVisible.assert_called_with(True)
    view.recommendation_portfolio_group.setChecked.assert_called_with(True)
    view.optimization_group.setVisible.assert_called_with(False)

    # 4. 測試策略研究 (strategy_research)
    view._update_ui_state_by_mode("strategy_research")
    view.strategy_preset_group.setVisible.assert_called_with(True)
    view.input_source_group.setVisible.assert_called_with(True)
    view.stock_selection_container.setVisible.assert_called_with(True)
    view.optimization_group.setVisible.assert_called_with(True)
    view.optimization_group.setChecked.assert_called_with(True)
    view.wf_group.setVisible.assert_called_with(True)
    view.wf_group.setChecked.assert_called_with(True)


def test_research_lab_config_panel_default_width_prevents_horizontal_squeeze(qt_app):
    """策略回測左側控制面板預設寬度應足以容納長下拉欄位。"""
    view = BacktestView(backtest_service=MagicMock(), config=None)

    assert view.config_panel.minimumWidth() >= 520
    assert view.execution_price_combo.minimumWidth() >= 320


def test_research_lab_optimization_param_labels_are_compact(qt_app):
    """參數最佳化列的 label 不應把控制項往右推太遠。"""
    view = BacktestView(backtest_service=MagicMock(), config=None)
    view.optimization_group.setChecked(True)
    view._update_optimization_params_form()

    compact_labels = {
        "門檻模式:",
        "買入分數門檻:",
        "賣出分數門檻:",
        "買入確認天數:",
        "賣出確認天數:",
        "交易冷卻天數:",
    }
    labels = [
        label
        for label in view.optimization_params_widget.findChildren(QLabel)
        if label.text() in compact_labels
    ]

    assert labels
    assert all(label.minimumWidth() == 104 for label in labels)
    assert all(label.maximumWidth() == 104 for label in labels)
