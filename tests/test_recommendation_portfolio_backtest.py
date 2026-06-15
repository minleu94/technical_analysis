import pandas as pd

from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationPortfolioBacktestResultDTO,
    RecommendationSnapshotDTO,
    StockContributionDTO,
)
from app_module.recommendation_portfolio_dates import parse_stock_dates
from app_module.recommendation_portfolio_metrics import calculate_robustness_metrics
from app_module.recommendation_portfolio_backtest_service import (
    RecommendationPortfolioBacktestService,
)
from app_module.recommendation_replay_service import RecommendationReplayService
from ui_qt.views.recommendation_view import build_recommendation_portfolio_backtest_config


def test_recommendation_portfolio_result_exposes_readable_tables():
    snapshot = RecommendationSnapshotDTO(
        as_of_date="2026-01-02",
        profile_id="momentum",
        strategy_config={"signals": {"weights": {"technical": 0.5}}},
        regime="Trend",
        recommendations=[
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 80.0,
                "factor_scores": {"technical": 82.0, "pattern": 50.0, "volume": 70.0},
                "selection_reason": "score_rank",
            }
        ],
        diagnostics=[],
    )
    holding = PeriodHoldingDTO(
        rebalance_date="2026-01-02",
        stock_code="2330",
        stock_name="台積電",
        rank=1,
        total_score=80.0,
        factor_scores={"technical": 82.0},
        allocation_amount=500000.0,
        allocation_weight=0.5,
        entry_date="2026-01-02",
        entry_price=100.0,
        planned_exit_date="2026-01-06",
        actual_exit_date="2026-01-06",
        actual_exit_price=110.0,
        exit_reason="holding_period",
        holding_days=4,
        return_pct=0.10,
    )
    contribution = StockContributionDTO(
        stock_code="2330",
        stock_name="台積電",
        selected_count=1,
        total_pnl=50000.0,
        avg_return_pct=0.10,
        win_rate=1.0,
        worst_return_pct=0.10,
    )
    result = RecommendationPortfolioBacktestResultDTO(
        summary={"total_return": 0.05, "max_drawdown": 0.0},
        equity_curve=pd.DataFrame([{"date": "2026-01-02", "equity": 1000000.0}]),
        trades=pd.DataFrame([{"stock_code": "2330", "side": "buy"}]),
        snapshots=[snapshot],
        period_holdings=[holding],
        stock_contribution=[contribution],
        selection_diagnostics=[],
    )

    assert result.summary["total_return"] == 0.05
    assert holding.pnl() == 50000.0
    assert result.period_holdings_dataframe().iloc[0]["股票代號"] == "2330"
    assert result.period_holdings_dataframe().iloc[0]["損益"] == 50000.0
    assert result.stock_contribution_dataframe().iloc[0]["股票代號"] == "2330"
    assert result.stock_contribution_dataframe().iloc[0]["總損益"] == 50000.0


def test_recommendation_portfolio_empty_tables_keep_readable_columns():
    result = RecommendationPortfolioBacktestResultDTO(
        summary={},
        equity_curve=pd.DataFrame(),
        trades=pd.DataFrame(),
        snapshots=[],
        period_holdings=[],
        stock_contribution=[],
        selection_diagnostics=[],
    )

    assert "股票代號" in result.period_holdings_dataframe().columns
    assert "損益" in result.period_holdings_dataframe().columns
    assert "股票代號" in result.stock_contribution_dataframe().columns
    assert "總損益" in result.stock_contribution_dataframe().columns


def test_replay_snapshot_filters_future_rows_before_recommending():
    calls = {}

    def provider(as_of_data, config, top_n):
        calls["max_date"] = as_of_data["日期"].max().strftime("%Y-%m-%d")
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 88.0,
                "factor_scores": {"technical": 88.0},
                "selection_reason": "score_rank",
            }
        ]

    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "收盤價": 100},
            {"日期": "2026-01-03", "證券代號": "2330", "收盤價": 200},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    service = RecommendationReplayService(provider=provider)
    snapshot = service.run_snapshot(
        as_of_date="2026-01-02",
        profile_id="momentum",
        config={"regime": "Trend"},
        history=history,
        universe=["2330"],
        top_n=5,
    )

    assert calls["max_date"] == "2026-01-02"
    assert snapshot.as_of_date == "2026-01-02"
    assert snapshot.recommendations[0]["stock_code"] == "2330"


def test_parse_stock_dates_handles_numeric_yyyymmdd_values():
    parsed = parse_stock_dates(pd.Series([20260102, 20260103]))

    assert parsed.iloc[0].strftime("%Y-%m-%d") == "2026-01-02"
    assert parsed.iloc[1].strftime("%Y-%m-%d") == "2026-01-03"


def test_portfolio_backtest_records_period_holdings_and_contributions():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-02", "證券代號": "2317", "證券名稱": "鴻海", "收盤價": 50},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
            {"日期": "2026-01-06", "證券代號": "2317", "證券名稱": "鴻海", "收盤價": 45},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"technical": 90.0},
            },
            {
                "stock_code": "2317",
                "stock_name": "鴻海",
                "total_score": 80.0,
                "factor_scores": {"technical": 80.0},
            },
        ][:top_n]

    service = RecommendationPortfolioBacktestService(provider=provider)
    result = service.run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=2,
        allocation_method="equal_weight",
        holding_days=4,
    )

    holdings = result.period_holdings_dataframe()
    contribution = result.stock_contribution_dataframe()

    assert list(holdings["股票代號"]) == ["2330", "2317"]
    assert holdings["配置金額"].sum() == 1000000.0
    assert contribution.loc[contribution["股票代號"] == "2330", "總損益"].iloc[0] == 50000.0
    assert contribution.loc[contribution["股票代號"] == "2317", "總損益"].iloc[0] == -50000.0
    assert result.summary["total_return"] == 0.0


def test_portfolio_backtest_exposes_cash_ledger_for_successful_holding():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"technical": 80.0},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
    )

    cash_ledger = result.details["cash_ledger"]

    assert cash_ledger == [
        {
            "date": "2026-01-02",
            "stock_code": "2330",
            "event": "buy",
            "amount": -1000000.0,
            "cash_balance": 0.0,
        },
        {
            "date": "2026-01-06",
            "stock_code": "2330",
            "event": "sell",
            "amount": 1100000.0,
            "cash_balance": 1100000.0,
        },
    ]
    assert result.summary["ending_cash"] == 1100000.0
    assert result.details["portfolio_credibility"]["cash_account"]["supported"] == "order_sizing"


def test_portfolio_backtest_applies_optional_execution_costs_to_cash_ledger():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"technical": 80.0},
            },
            {
                "stock_code": "2317",
                "stock_name": "鴻海",
                "total_score": 80.0,
                "factor_scores": {"technical": 70.0},
            },
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=2,
        allocation_method="equal_weight",
        holding_days=4,
        fee_bps=10,
        slippage_bps=5,
        tax_bps=30,
    )

    cash_ledger = result.details["cash_ledger"]

    assert cash_ledger[0]["event"] == "buy"
    assert cash_ledger[0]["gross_amount"] == -500000.0
    assert cash_ledger[0]["costs"] == {"fee": 500.0, "tax": 0.0, "slippage": 250.0, "total": 750.0}
    assert cash_ledger[0]["amount"] == -500750.0
    assert cash_ledger[0]["cash_balance"] == 499250.0
    assert cash_ledger[1]["event"] == "sell"
    assert cash_ledger[1]["gross_amount"] == 550000.0
    assert cash_ledger[1]["costs"] == {"fee": 550.0, "tax": 1650.0, "slippage": 275.0, "total": 2475.0}
    assert cash_ledger[1]["amount"] == 547525.0
    assert result.summary["ending_cash"] == 1046775.0
    assert result.summary["total_transaction_cost"] == 3225.0
    assert result.details["unfilled_orders"][0]["reason"] == "cash_limited"
    assert result.details["portfolio_credibility"]["execution_costs"]["supported"] == "partial"


def test_portfolio_backtest_releases_exit_cash_before_same_day_rebalance_buy():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
            {"日期": "2026-01-09", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 120},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"technical": 80.0},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-09",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="weekly",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
    )

    cash_ledger = result.details["cash_ledger"]

    assert [row["event"] for row in cash_ledger] == ["buy", "sell", "buy", "sell"]
    assert cash_ledger[1]["date"] == "2026-01-06"
    assert cash_ledger[1]["amount"] == 1100000.0
    assert cash_ledger[1]["cash_balance"] == 1100000.0
    assert cash_ledger[2]["date"] == "2026-01-06"
    assert cash_ledger[2]["amount"] == -1000000.0
    assert cash_ledger[2]["cash_balance"] == 100000.0
    assert result.summary["ending_cash"] == 1190909.09


def test_portfolio_backtest_records_cash_limited_when_rebalance_cash_is_unavailable():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 105},
            {"日期": "2026-01-09", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"technical": 80.0},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-09",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="weekly",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=10,
    )

    unfilled_orders = result.details["unfilled_orders"]

    assert len(result.period_holdings) == 1
    assert result.summary["total_trades"] == 1
    assert result.summary["unfilled_order_count"] == 1
    assert unfilled_orders[0]["reason"] == "cash_limited"
    assert unfilled_orders[0]["stock_code"] == "2330"
    assert unfilled_orders[0]["cash"] == {
        "available_cash": 0.0,
        "required_cash": 1000000.0,
        "cash_shortfall": 1000000.0,
    }
    assert "unfilled_order:2330:cash_limited" in result.selection_diagnostics
    assert result.summary["ending_cash"] == 1100000.0


def test_portfolio_backtest_marks_equity_to_market_each_trading_day():
    date_col = "\u65e5\u671f"
    code_col = "\u8b49\u5238\u4ee3\u865f"
    name_col = "\u8b49\u5238\u540d\u7a31"
    close_col = "\u6536\u76e4\u50f9"
    history = pd.DataFrame(
        [
            {"date": "2026-01-02", "code": "2330", "name": "TSMC", "close": 100},
            {"date": "2026-01-03", "code": "2330", "name": "TSMC", "close": 105},
            {"date": "2026-01-06", "code": "2330", "name": "TSMC", "close": 110},
        ]
    )
    history.columns = [date_col, code_col, name_col, close_col]

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "TSMC",
                "total_score": 90.0,
                "factor_scores": {},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
    )

    equity_by_date = result.equity_curve.set_index("date")["equity"].to_dict()

    assert equity_by_date == {
        "2026-01-02": 1000000.0,
        "2026-01-03": 1050000.0,
        "2026-01-06": 1100000.0,
    }


def test_portfolio_backtest_exits_early_on_stop_loss_and_summarizes_diagnostics():
    date_col = "\u65e5\u671f"
    code_col = "\u8b49\u5238\u4ee3\u865f"
    name_col = "\u8b49\u5238\u540d\u7a31"
    close_col = "\u6536\u76e4\u50f9"
    history = pd.DataFrame(
        [
            {"date": "2026-01-02", "code": "2330", "name": "TSMC", "close": 100},
            {"date": "2026-01-03", "code": "2330", "name": "TSMC", "close": 94},
            {"date": "2026-01-06", "code": "2330", "name": "TSMC", "close": 110},
        ]
    )
    history.columns = [date_col, code_col, name_col, close_col]

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "TSMC",
                "total_score": 90.0,
                "factor_scores": {},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
        stop_loss_pct=0.05,
        take_profit_pct=None,
    )

    holding = result.period_holdings[0]

    assert holding.actual_exit_date == "2026-01-03"
    assert holding.actual_exit_price == 94.0
    assert holding.exit_reason == "stop_loss"
    assert holding.return_pct == -0.06
    assert result.summary["stop_loss_exits"] == 1
    assert result.summary["take_profit_exits"] == 0
    assert result.summary["holding_period_exits"] == 0
    assert result.summary["loss_trade_ratio"] == 1.0
    assert result.summary["worst_stock_code"] == "2330"


def test_portfolio_backtest_exits_early_on_take_profit():
    date_col = "\u65e5\u671f"
    code_col = "\u8b49\u5238\u4ee3\u865f"
    name_col = "\u8b49\u5238\u540d\u7a31"
    close_col = "\u6536\u76e4\u50f9"
    history = pd.DataFrame(
        [
            {"date": "2026-01-02", "code": "2330", "name": "TSMC", "close": 100},
            {"date": "2026-01-03", "code": "2330", "name": "TSMC", "close": 108},
            {"date": "2026-01-06", "code": "2330", "name": "TSMC", "close": 95},
        ]
    )
    history.columns = [date_col, code_col, name_col, close_col]

    def provider(as_of_data, config, top_n):
        return [{"stock_code": "2330", "stock_name": "TSMC", "total_score": 90.0, "factor_scores": {}}]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
        stop_loss_pct=None,
        take_profit_pct=0.05,
    )

    holding = result.period_holdings[0]

    assert holding.actual_exit_date == "2026-01-03"
    assert holding.exit_reason == "take_profit"
    assert holding.return_pct == 0.08
    assert result.summary["take_profit_exits"] == 1


def test_recommendation_portfolio_robustness_metrics_are_deterministic():
    equity_curve = pd.DataFrame(
        [
            {"date": "2026-01-02", "equity": 1000000.0},
            {"date": "2026-01-03", "equity": 1010000.0},
            {"date": "2026-01-04", "equity": 1000000.0},
            {"date": "2026-01-05", "equity": 1020000.0},
        ]
    )
    trade_returns = [0.10, -0.05, 0.02]

    metrics = calculate_robustness_metrics(
        equity_curve=equity_curve,
        trade_returns=trade_returns,
        monte_carlo_runs=25,
        random_seed=7,
    )

    assert set(
        [
            "sharpe_ratio",
            "sortino_ratio",
            "monte_carlo_p05_return",
            "monte_carlo_p50_return",
            "monte_carlo_p95_return",
        ]
    ).issubset(metrics)
    assert metrics["sharpe_ratio"] > 0
    assert metrics["sortino_ratio"] > metrics["sharpe_ratio"]
    assert abs(metrics["monte_carlo_p05_return"] - metrics["monte_carlo_p95_return"]) < 1e-12


def test_portfolio_backtest_summary_includes_robustness_metrics():
    date_col = "\u65e5\u671f"
    code_col = "\u8b49\u5238\u4ee3\u865f"
    name_col = "\u8b49\u5238\u540d\u7a31"
    close_col = "\u6536\u76e4\u50f9"
    history = pd.DataFrame(
        [
            {"æ—¥æœŸ": "2026-01-02", "è­‰åˆ¸ä»£è™Ÿ": "2330", "è­‰åˆ¸åç¨±": "å°ç©é›»", "æ”¶ç›¤åƒ¹": 100},
            {"æ—¥æœŸ": "2026-01-06", "è­‰åˆ¸ä»£è™Ÿ": "2330", "è­‰åˆ¸åç¨±": "å°ç©é›»", "æ”¶ç›¤åƒ¹": 110},
            {"æ—¥æœŸ": "2026-01-02", "è­‰åˆ¸ä»£è™Ÿ": "2317", "è­‰åˆ¸åç¨±": "é´»æµ·", "æ”¶ç›¤åƒ¹": 50},
            {"æ—¥æœŸ": "2026-01-06", "è­‰åˆ¸ä»£è™Ÿ": "2317", "è­‰åˆ¸åç¨±": "é´»æµ·", "æ”¶ç›¤åƒ¹": 45},
        ]
    )
    history.columns = [date_col, code_col, name_col, close_col]

    def provider(as_of_data, config, top_n):
        return [
            {"stock_code": "2330", "stock_name": "å°ç©é›»", "total_score": 90.0, "factor_scores": {}},
            {"stock_code": "2317", "stock_name": "é´»æµ·", "total_score": 80.0, "factor_scores": {}},
        ][:top_n]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=2,
        allocation_method="equal_weight",
        holding_days=4,
    )

    assert "sharpe_ratio" in result.summary
    assert "sortino_ratio" in result.summary
    assert "monte_carlo_p50_return" in result.summary


def test_portfolio_backtest_can_replay_weekly_recommendations():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
            {"日期": "2026-01-09", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 120},
            {"日期": "2026-01-13", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 126},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])
    called_dates = []

    def provider(as_of_data, config, top_n):
        called_dates.append(as_of_data["日期"].max().strftime("%Y-%m-%d"))
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"technical": 90.0},
            }
        ]

    service = RecommendationPortfolioBacktestService(provider=provider)
    result = service.run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-13",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="weekly",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
    )

    assert called_dates == ["2026-01-02", "2026-01-06", "2026-01-13"]
    assert len(result.snapshots) == 3
    assert len(result.period_holdings) == 3


def test_result_dto_supports_backtest_tab_readability_layers():
    result = RecommendationPortfolioBacktestResultDTO(
        summary={"total_return": 0.02, "max_drawdown": -0.01, "total_trades": 1},
        equity_curve=pd.DataFrame([{"date": "2026-01-02", "equity": 1000000.0}]),
        trades=pd.DataFrame([{"date": "2026-01-02", "stock_code": "2330", "side": "buy"}]),
        snapshots=[],
        period_holdings=[
            PeriodHoldingDTO(
                rebalance_date="2026-01-02",
                stock_code="2330",
                stock_name="台積電",
                rank=1,
                total_score=80.0,
                factor_scores={},
                allocation_amount=1000000.0,
                allocation_weight=1.0,
                entry_date="2026-01-02",
                entry_price=100.0,
                planned_exit_date="2026-01-06",
                actual_exit_date="2026-01-06",
                actual_exit_price=102.0,
                exit_reason="holding_period",
                holding_days=4,
                return_pct=0.02,
            )
        ],
        stock_contribution=[],
        selection_diagnostics=["missing_future_factor:broker_flow"],
    )

    assert "股票代號" in result.period_holdings_dataframe().columns
    assert "missing_future_factor:broker_flow" in result.selection_diagnostics


def test_recommendation_portfolio_payload_preserves_profile_config():
    config = build_recommendation_portfolio_backtest_config(
        profile_id="momentum",
        profile_name="暴衝策略",
        strategy_config={"filters": {"price_change_min": 2}},
        regime="Trend",
        top_n=5,
        holding_days=5,
        allocation_method="score_weight",
    )

    assert config["mode"] == "recommendation_portfolio"
    assert config["strategy_config"]["filters"]["price_change_min"] == 2
    assert config["allocation_method"] == "score_weight"


def test_portfolio_backtest_with_percentile_ranking():
    configs_received = []
    
    def provider(as_of_data, config, top_n):
        configs_received.append(config)
        return [
            {"stock_code": "2330", "stock_name": "台積電", "total_score": 90.0, "factor_scores": {}}
        ]
        
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])
    
    service = RecommendationPortfolioBacktestService(provider=provider)
    result = service.run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={
            "regime": "Trend",
            "recommendation_ranking": {
                "threshold_mode": "quantile",
                "recommendation_min_percentile_bp": 8000,
                "recommendation_min_universe_size": 20
            }
        },
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
    )
    
    assert len(configs_received) > 0
    assert configs_received[0]["recommendation_ranking"]["threshold_mode"] == "quantile"
    assert configs_received[0]["recommendation_ranking"]["recommendation_min_percentile_bp"] == 8000


def test_portfolio_backtest_result_includes_factor_manifest_from_replay_snapshots():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 82.35,
                "factor_scores": {"volume": 70.0},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
    )

    manifest = result.details["data_manifest"]
    snapshot = manifest["factor_snapshot"]
    contributions = manifest["factor_contributions"]

    assert snapshot["records"][0]["factor_name"] == "technical.total_score"
    assert snapshot["records"][0]["score_bp"] == 8235
    assert snapshot["records"][1]["factor_name"] == "volume.volume_ratio"
    assert snapshot["records"][1]["metadata"]["source_field"] == "factor_scores.volume"
    assert contributions["by_stock"]["2330"][0]["state"] == "accepted"
    assert contributions["summary_by_factor"]["volume.volume_ratio"]["accepted_count"] == 1


def test_portfolio_backtest_result_includes_credibility_manifest():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 82.35,
                "factor_scores": {"volume": 70.0},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
    )

    credibility = result.details["portfolio_credibility"]

    assert credibility["schema_version"] == 1
    assert credibility["status"] == "limited"
    assert credibility["cash_account"]["supported"] == "order_sizing"
    assert credibility["cash_account"]["policy"] == "available_cash_checked_before_holding_creation"
    assert credibility["rebalance"]["supported"] is False
    assert credibility["unfilled_orders"]["supported"] is True
    assert credibility["liquidity_gap"]["supported"] is False
    assert credibility["execution_assumption"] == "idealized_same_day_close"
    assert "rebalance_cash_reuse_partial" in credibility["warnings"]
    assert "unfilled_orders_not_modeled" not in credibility["warnings"]
    assert result.summary["credibility_status"] == "limited"
    assert result.summary["credibility_warning_count"] == len(credibility["warnings"])


def test_portfolio_backtest_records_unfilled_order_when_recommended_stock_has_no_price_rows():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"volume": 70.0},
            },
            {
                "stock_code": "9999",
                "stock_name": "缺價股",
                "total_score": 80.0,
                "factor_scores": {"volume": 60.0},
            },
        ][:top_n]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=2,
        allocation_method="equal_weight",
        holding_days=4,
    )

    unfilled_orders = result.details["unfilled_orders"]

    assert len(result.period_holdings) == 1
    assert result.summary["total_trades"] == 1
    assert result.summary["unfilled_order_count"] == 1
    assert unfilled_orders == [
        {
            "rebalance_date": "2026-01-02",
            "stock_code": "9999",
            "stock_name": "缺價股",
            "rank": 2,
            "reason": "missing_price_rows",
            "planned_exit_date": "2026-01-06",
            "allocation_amount": 500000.0,
            "allocation_weight": 0.5,
            "total_score": 80.0,
        }
    ]
    assert "unfilled_order:9999:missing_price_rows" in result.selection_diagnostics
    assert result.details["portfolio_credibility"]["unfilled_orders"]["supported"] is True


def test_portfolio_backtest_records_unfilled_order_when_liquidity_is_insufficient():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100, "成交股數": 1000},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110, "成交股數": 1000},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"volume": 70.0},
            }
        ]

    result = RecommendationPortfolioBacktestService(provider=provider).run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
        max_participation_rate=0.05,
    )

    unfilled_orders = result.details["unfilled_orders"]

    assert result.period_holdings == []
    assert result.summary["total_trades"] == 0
    assert result.summary["unfilled_order_count"] == 1
    assert unfilled_orders[0]["reason"] == "liquidity_limited"
    assert unfilled_orders[0]["stock_code"] == "2330"
    assert unfilled_orders[0]["allocation_amount"] == 1000000.0
    assert unfilled_orders[0]["liquidity"]["volume_shares"] == 1000
    assert unfilled_orders[0]["liquidity"]["max_participation_rate"] == 0.05
    assert unfilled_orders[0]["liquidity"]["max_participation_amount"] == 5000.0
    assert "unfilled_order:2330:liquidity_limited" in result.selection_diagnostics
    assert result.details["portfolio_credibility"]["liquidity_gap"]["supported"] == "partial"
