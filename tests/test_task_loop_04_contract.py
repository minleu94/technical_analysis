"""TASK-04 執行契約：時間因果、精確帳務與末端狀態。"""

from decimal import Decimal
import pandas as pd
import pytest

from app_module.recommendation_portfolio_backtest_service import RecommendationPortfolioBacktestService
from app_module.recommendation_portfolio_dtos import RecommendationPortfolioBacktestResultDTO
from backtest_module.broker_simulator import BrokerConfig, BrokerSimulator, NEXT_OPEN_CONTRACT


def _history():
    return pd.DataFrame([
        {"日期": "2026-06-05", "證券代號": "2330", "證券名稱": "台積電", "開盤價": "99", "收盤價": "100", "成交股數": 100000},
        {"日期": "2026-06-08", "證券代號": "2330", "證券名稱": "台積電", "開盤價": "110", "收盤價": "105", "成交股數": 100000},
        {"日期": "2026-06-09", "證券代號": "2330", "證券名稱": "台積電", "開盤價": "104", "收盤價": "90", "成交股數": 100000},
        {"日期": "2026-06-10", "證券代號": "2330", "證券名稱": "台積電", "開盤價": "80", "收盤價": "85", "成交股數": 100000},
    ])


def _run(history=None, provider=None, **kwargs):
    params = dict(start_date="2026-06-05", end_date="2026-06-10", profile_id="fixture", recommendation_config={},
                  history=_history() if history is None else history, initial_capital="10000", rebalance_frequency="once",
                  top_n=1, allocation_method="equal_weight", holding_days=30, fee_bps=0, slippage_bps=0, tax_bps=0)
    params.update(kwargs)
    service = RecommendationPortfolioBacktestService(provider or (lambda *_: [{"stock_code": "2330", "stock_name": "台積電", "total_score": 90, "factor_scores": {}}]))
    return service.run_portfolio_backtest(**params)


def test_next_session_open_keeps_signal_day_cash_and_gap_price():
    result = _run()
    holding = result.period_holdings[0]
    assert holding.rebalance_date == "2026-06-05"
    assert holding.entry_date == "2026-06-08"
    assert holding.entry_price == 110
    assert holding.shares == 90
    assert result.equity_curve.iloc[0]["cash"] == 10000
    assert result.equity_curve.iloc[1]["cash"] == 100
    assert result.summary["execution_contract"] == NEXT_OPEN_CONTRACT
    assert holding.position_status == "open"
    assert holding.actual_exit_date == ""
    assert list(result.trades["side"]) == ["buy"]
    assert result.summary["ending_equity"] == 7750


@pytest.mark.parametrize("change", ["missing_open", "zero_volume", "suspended"])
def test_missing_or_suspended_session_delays_fill_without_close_fallback(change):
    data = _history()
    if change == "missing_open":
        data.loc[1, "開盤價"] = None
    elif change == "zero_volume":
        data.loc[1, "成交股數"] = 0
    else:
        data.loc[1, "trading_status"] = "suspended"
    result = _run(data)
    assert result.period_holdings[0].entry_date == "2026-06-09"
    assert result.period_holdings[0].entry_price == 104


def test_no_open_data_remains_unfilled_and_no_terminal_forced_trade():
    result = _run(_history().drop(columns="開盤價"))
    assert result.period_holdings == []
    assert result.trades.empty
    assert result.summary["ending_cash"] == 10000
    assert result.details["unfilled_orders"][0]["reason"] == "missing_open_or_suspended"


def test_stop_confirmation_executes_at_next_open_with_gap_and_exact_costs():
    result = _run(stop_loss_pct="0.10", fee_bps="10", slippage_bps="20", tax_bps="30")
    holding = result.period_holdings[0]
    assert holding.exit_signal_date == "2026-06-09"
    assert holding.actual_exit_date == "2026-06-10"
    assert holding.actual_exit_price == 80
    assert holding.exit_reason == "stop_loss_close_confirmed"
    buy, sell = result.trades.to_dict("records")
    buy_cost = sum((Decimal(str(buy[k])) for k in ("fee", "tax", "slippage")), Decimal("0"))
    sell_cost = sum((Decimal(str(sell[k])) for k in ("fee", "tax", "slippage")), Decimal("0"))
    expected = Decimal("10000") - Decimal(str(buy["amount"])) - buy_cost + Decimal(str(sell["amount"])) - sell_cost
    assert Decimal(str(result.summary["ending_cash"])) == expected
    assert holding.pnl_cents == int((expected - Decimal("10000")) * 100)
    assert result.summary["open_position_count"] == 0


def test_future_append_does_not_change_signals_trades_or_equity():
    data = _history()
    future = data.iloc[[-1]].copy()
    future["日期"] = "2026-06-11"
    future["開盤價"], future["收盤價"] = "99999", "1"
    seen = []
    def provider(frame, *_):
        seen.append(frame["日期"].max())
        return [{"stock_code": "2330", "stock_name": "台積電", "total_score": 90}]
    first = _run(data, provider)
    second = _run(pd.concat([data, future], ignore_index=True), provider)
    assert seen == [pd.Timestamp("2026-06-05"), pd.Timestamp("2026-06-05")]
    pd.testing.assert_frame_equal(first.trades, second.trades)
    pd.testing.assert_frame_equal(first.equity_curve, second.equity_curve)


def test_cancel_preserves_partial_result_and_marks_pending_unfilled():
    count = 0
    def cancel():
        nonlocal count
        count += 1
        return count > 1
    result = _run(check_cancel=cancel)
    assert result.summary["status"] == "cancelled"
    assert result.trades.empty
    assert result.details["unfilled_orders"][0]["reason"] == "cancelled"


def test_dto_round_trip_preserves_version_status_and_exact_pnl():
    result = _run(stop_loss_pct="0.10")
    loaded = RecommendationPortfolioBacktestResultDTO.from_dict(result.to_dict())
    assert loaded.period_holdings[0].execution_contract == NEXT_OPEN_CONTRACT
    assert loaded.period_holdings[0].pnl_cents == result.period_holdings[0].pnl_cents
    assert loaded.summary["benchmark_excess_return_bp"] == 0
    assert loaded.details["relative_attribution"]["status"] == "comparable"


def test_single_stock_last_signal_never_fills_at_same_close():
    frame = _history().set_index("日期")
    frame.index = pd.to_datetime(frame.index)
    frame["signal"] = [0, 0, 0, 1]
    simulator = BrokerSimulator(BrokerConfig(execution_price="next_open", enable_limit_up_down=False, enable_volume_constraint=False))
    trades, equity = simulator.run(frame, 1000000)
    assert trades == []
    assert equity.iloc[-1]["cash"] == 1000000
    assert simulator.execution_diagnostics[-1]["reason"] == "end_of_data"


def test_single_stock_pyramid_quantity_and_cash_are_conserved():
    frame = _history().set_index("日期")
    frame.index = pd.to_datetime(frame.index)
    frame["signal"] = [1, 1, 0, 0]
    simulator = BrokerSimulator(BrokerConfig(execution_price="next_open", enable_limit_up_down=False, enable_volume_constraint=False,
        sizing_mode="fixed_amount", fixed_amount=250000, allow_pyramid=True, fee_bps=0, slippage_bps=0))
    trades, equity = simulator.run(frame, 1000000)
    assert len(trades) == 2
    assert equity.iloc[-1]["position"] == sum(t.shares for t in trades)
    expected_cash = Decimal("1000000") - sum((Decimal(str(t.value)) + Decimal(str(t.fee)) + Decimal(str(t.slippage)) for t in trades), Decimal("0"))
    assert Decimal(str(equity.iloc[-1]["cash"])) == expected_cash
    assert all(t.type == "buy" for t in trades)


def test_available_date_and_nested_config_are_frozen_before_provider():
    from app_module.recommendation_replay_service import RecommendationReplayService
    config = {"weights": {"technical": 1}}
    observed = []
    def provider(frame, received, *_):
        observed.append(len(frame))
        received["weights"]["technical"] = 999
        return []
    data = _history().iloc[:2].copy()
    data["available_date"] = ["2026-06-05", "2026-06-09"]
    snapshot = RecommendationReplayService(provider).run_snapshot("2026-06-08", "fixture", config, data, None, 1)
    assert observed == [1]
    assert config["weights"]["technical"] == snapshot.strategy_config["weights"]["technical"] == 1
    config["weights"]["technical"] = 2
    assert snapshot.strategy_config["weights"]["technical"] == 1


def test_equal_weight_benchmark_uses_frozen_selection_and_same_costs():
    first = _history()
    second = first.copy()
    second["證券代號"] = "2317"
    second["開盤價"] = ["50", "50", "50", "50"]
    second["收盤價"] = ["50", "50", "60", "70"]
    calls = []
    def provider(frame, *_):
        calls.append(frame["日期"].max())
        return [{"stock_code": "2330", "total_score": 90}, {"stock_code": "2317", "total_score": 10}]
    result = _run(pd.concat([first, second]), provider, top_n=2, allocation_method="score_weight", fee_bps=10, slippage_bps=20, tax_bps=30)
    benchmark = result.details["benchmark_results"]
    assert len(calls) == 1
    assert benchmark["execution_contract"] == result.summary["execution_contract"]
    assert benchmark["status"] == "comparable"
    assert benchmark["equity_curve"][0]["cash"] == result.equity_curve.iloc[0]["cash"] == 10000
    assert result.summary["benchmark_excess_return_bp"] < 0


def test_research_history_app_read_is_query_only_and_preserves_open(tmp_path):
    import hashlib
    import sqlite3
    from types import SimpleNamespace
    from app_module.backtest_service import BacktestService
    path = tmp_path / "market.sqlite"
    with sqlite3.connect(path) as connection:
        _history().to_sql("daily_prices", connection, index=False)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    service = BacktestService(SimpleNamespace(use_sqlite=True, db_file=path))
    frame = service.load_recommendation_portfolio_history("2026-06-05", "2026-06-09")
    assert frame["開盤價"].tolist() == ["99", "110", "104"]
    assert frame["日期"].max() == pd.Timestamp("2026-06-09")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_fifo_pyramid_partial_exit_conserves_realized_cost_basis():
    from backtest_module.broker_simulator import Trade
    from backtest_module.performance_metrics import PerformanceAnalyzer
    def trade(side, shares, value, fee, day):
        return Trade(pd.Timestamp(day), side, value / shares, shares, value, fee, 0, "fixture", 1 if side == "buy" else -1)
    trades = [trade("buy", 1000, 100000, 20, "2026-06-05"), trade("buy", 1000, 110000, 20, "2026-06-08"),
              trade("sell", 1500, 180000, 30, "2026-06-09"), trade("sell", 500, 65000, 20, "2026-06-10")]
    pairs = PerformanceAnalyzer()._closed_trade_pairs(trades)
    assert [pair["shares"] for pair in pairs] == [1500, 500]
    assert sum(Decimal(str(pair["profit"])) for pair in pairs) == Decimal("34910")
