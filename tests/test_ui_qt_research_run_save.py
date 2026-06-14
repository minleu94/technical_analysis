import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication

from app_module.dtos import BacktestReportDTO
from data_module.config import TWStockConfig
from ui_qt.views.backtest_view import BacktestView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


@pytest.fixture
def qt_app():
    return app()


@pytest.fixture
def backtest_view(qt_app, tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    view = BacktestView(backtest_service=MagicMock(), config=config)
    view.research_run_service = MagicMock()
    view.run_repository = MagicMock()
    view.portfolio_run_repository = MagicMock()
    return view


def _backtest_report():
    return BacktestReportDTO(
        total_return=0.12,
        annual_return=0.18,
        sharpe_ratio=1.25,
        max_drawdown=-0.08,
        win_rate=0.55,
        total_trades=3,
        expectancy=0.04,
        details={
            "data_version": "sha256:data",
            "data_as_of_date": "2026-06-13",
            "strategy_version": "baseline_score@1.0",
            "execution_price": "next_open",
            "trade_list": pd.DataFrame([{"日期": "2026-01-05", "stock_code": "2330"}]),
            "equity_curve": pd.DataFrame([{"日期": "2026-01-02", "equity": 1000000}]),
        },
    )


class _FakePortfolioResult:
    summary = {"total_return": 0.15, "max_drawdown": -0.05, "total_trades": 4}
    equity_curve = pd.DataFrame([{"日期": "2026-01-02", "equity": 1000000}])
    trades = pd.DataFrame([{"日期": "2026-01-05", "stock_code": "2330"}])
    details = {
        "data_version": "sha256:data",
        "data_as_of_date": "2026-06-13",
        "strategy_version": "recommendation_replay@1.0",
        "execution_price": "next_open",
    }


def test_single_backtest_save_uses_research_run_service_not_legacy_repo(backtest_view):
    report = _backtest_report()
    backtest_view.current_report = report
    backtest_view.current_run_params = {
        "stock_code": "2330",
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
        "strategy_id": "baseline_score",
        "strategy_params": {"buy_score": 55},
        "capital": 1000000,
        "fee_bps": 14.25,
        "slippage_bps": 5.0,
        "execution_price": "next_open",
        "sizing_mode": "all_in",
    }
    backtest_view._execution_generation = 1
    backtest_view._single_backtest_result_generation = 1

    run_id = backtest_view._save_single_backtest_to_research_registry("Run Name", "notes")

    backtest_view.research_run_service.save_run.assert_called_once()
    backtest_view.run_repository.save_run.assert_not_called()
    metadata, equity, trades = backtest_view.research_run_service.save_run.call_args.args
    assert run_id == metadata.run_id
    assert backtest_view.current_run_id == metadata.run_id
    assert metadata.run_type == "single_backtest"
    assert metadata.run_name == "Run Name"
    assert metadata.original_input["notes"] == "notes"
    assert metadata.normalized_params["buy_score"] == 55
    assert metadata.capital_cents == 100000000
    assert metadata.fee_bp_x100 == 1425
    assert metadata.slippage_bp_x100 == 500
    assert equity.equals(report.details["equity_curve"])
    assert trades.equals(report.details["trade_list"])


def test_single_backtest_save_rejects_stale_result(backtest_view):
    backtest_view.current_report = _backtest_report()
    backtest_view.current_run_params = {"stock_code": "2330"}
    backtest_view._execution_generation = 2
    backtest_view._single_backtest_result_generation = 1

    with pytest.raises(ValueError, match="stale"):
        backtest_view._save_single_backtest_to_research_registry("Run Name", "")

    backtest_view.research_run_service.save_run.assert_not_called()


def test_recommendation_replay_save_uses_research_run_service(backtest_view):
    result = _FakePortfolioResult()
    backtest_view.current_recommendation_portfolio_result = result
    backtest_view.current_recommendation_portfolio_config = {
        "profile_id": "advanced",
        "strategy_config": {"strategy_id": "recommendation_replay"},
    }
    backtest_view.current_recommendation_portfolio_run_params = {
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
        "initial_capital": 1000000,
        "top_n": 5,
        "rebalance_frequency": "weekly",
        "allocation_method": "equal_weight",
        "holding_days": 5,
    }
    backtest_view._execution_generation = 3
    backtest_view._recommendation_portfolio_result_generation = 3

    run_id = backtest_view._save_recommendation_portfolio_to_research_registry(
        "Replay Run",
        "notes",
    )

    backtest_view.research_run_service.save_run.assert_called_once()
    backtest_view.portfolio_run_repository.save_run.assert_not_called()
    metadata, equity, trades = backtest_view.research_run_service.save_run.call_args.args
    assert run_id == metadata.run_id
    assert backtest_view.current_portfolio_run_id == metadata.run_id
    assert metadata.run_type == "recommendation_portfolio"
    assert metadata.strategy_id == "recommendation_replay"
    assert metadata.normalized_params["top_n"] == 5
    assert metadata.capital_cents == 100000000
    assert equity.equals(result.equity_curve)
    assert trades.equals(result.trades)
