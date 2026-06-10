import pandas as pd

from backtest_module.broker_simulator import Trade
from backtest_module.performance_metrics import PerformanceAnalyzer


def make_trade(
    side: str,
    value: float,
    fee: float = 0.0,
    slippage: float = 0.0,
) -> Trade:
    return Trade(
        date=pd.Timestamp("2026-01-02" if side == "buy" else "2026-01-05"),
        type=side,
        price=value,
        shares=1,
        value=value,
        fee=fee,
        slippage=slippage,
        reason_tags="numeric-governance",
        signal=1 if side == "buy" else -1,
    )


def test_trade_profit_statistics_are_quantized_to_cents() -> None:
    analyzer = PerformanceAnalyzer()
    trades = [
        make_trade("buy", value=1000.10, fee=0.10, slippage=0.20),
        make_trade("sell", value=1100.40, fee=0.10, slippage=0.20),
    ]

    stats = analyzer._analyze_trades(trades, initial_capital=10000.0)

    assert stats["trade_pairs"][0]["profit"] == 99.70
    assert stats["avg_win"] == 99.70
    assert stats["largest_win"] == 99.70


def test_trade_list_reports_quantized_profit_to_cents() -> None:
    analyzer = PerformanceAnalyzer()
    trades = [
        make_trade("buy", value=1000.10, fee=0.10, slippage=0.20),
        make_trade("sell", value=1100.40, fee=0.10, slippage=0.20),
    ]

    trade_list = analyzer.create_trade_list(trades, initial_capital=10000.0)

    assert trade_list.iloc[0]["報酬"] == 99.70
