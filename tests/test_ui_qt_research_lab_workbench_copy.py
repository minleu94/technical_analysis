from pathlib import Path


BACKTEST_VIEW_TEXT = Path("ui_qt/views/backtest_view.py").read_text(encoding="utf-8")


def test_backtest_view_names_left_side_as_research_lab_workbench():
    assert "實驗模式" in BACKTEST_VIEW_TEXT
    assert "輸入來源" in BACKTEST_VIEW_TEXT
    assert "策略與風控" in BACKTEST_VIEW_TEXT
    assert "執行實驗" in BACKTEST_VIEW_TEXT
    assert "主要輸入" in BACKTEST_VIEW_TEXT


def test_backtest_view_names_result_tabs_as_experiment_outputs():
    assert "實驗摘要" in BACKTEST_VIEW_TEXT
    assert "交易明細" in BACKTEST_VIEW_TEXT
    assert "批次結果" in BACKTEST_VIEW_TEXT
    assert "推薦回放" in BACKTEST_VIEW_TEXT
    assert "歷史與比較" in BACKTEST_VIEW_TEXT


def test_backtest_view_preserves_existing_advanced_capabilities():
    assert "參數最佳化" in BACKTEST_VIEW_TEXT
    assert "Walk-forward 驗證" in BACKTEST_VIEW_TEXT
    assert "升級為策略版本" in BACKTEST_VIEW_TEXT
