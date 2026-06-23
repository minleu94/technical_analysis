import os
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication

from ui_qt.views.backtest_view import BacktestView


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def qt_app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def _fake_recommendation_replay_result():
    return SimpleNamespace(
        summary={
            "total_return": 0.5372,
            "max_drawdown": -0.2137,
            "total_trades": 291,
            "avg_holding_days": 3.8,
            "capital_used": 488_333_333,
            "stop_loss_exits": 1,
            "take_profit_exits": 2,
            "holding_period_exits": 288,
            "loss_trade_ratio": 0.54,
            "worst_stock_code": "3580",
            "worst_stock_name": "友威科",
            "worst_stock_pnl": -12345,
            "sharpe_ratio": 1.66,
            "sortino_ratio": 1.73,
            "monte_carlo_p05_return": 7.9573,
            "monte_carlo_p50_return": 7.9573,
            "monte_carlo_p95_return": 7.9573,
        },
        trades=pd.DataFrame(
            [{"股票代號": "2330", "日期": "2026-06-01", "損益": 1200}]
        ),
        equity_curve=pd.DataFrame(),
        improvement_hints=["降低持有天數後再觀察"],
        period_holdings_dataframe=lambda: pd.DataFrame(
            [{"期間": "2026-W01", "持倉數": 5}]
        ),
        stock_contribution_dataframe=lambda: pd.DataFrame(
            [{"股票代號": "2330", "貢獻": 5000}]
        ),
    )


def test_recommendation_replay_summary_is_sectioned_and_not_duplicated(qt_app):
    view = BacktestView(backtest_service=None, config=None)

    view._show_recommendation_portfolio_result(_fake_recommendation_replay_result())

    summary = view.portfolio_summary_text.toPlainText()
    assert summary.count("總報酬率") == 1
    assert "【概況】" in summary
    assert "【交易假設與可信度】" in summary
    assert "【Monte Carlo 情境】" in summary
    assert "資金使用代表期間投入金額，不等同最終淨值" in summary


def test_recommendation_replay_details_are_available_in_inner_tabs(qt_app):
    view = BacktestView(backtest_service=None, config=None)

    view._show_recommendation_portfolio_result(_fake_recommendation_replay_result())

    detail_tabs = view.result_panel.portfolio_detail_tabs
    labels = [detail_tabs.tabText(index) for index in range(detail_tabs.count())]

    assert labels == ["圖表", "期間明細", "個股貢獻", "交易紀錄"]
    assert view.portfolio_period_table.model().rowCount() == 1
    assert view.portfolio_stock_table.model().rowCount() == 1
    assert view.portfolio_trades_table.model().rowCount() == 1
