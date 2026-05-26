import pandas as pd

from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationPortfolioBacktestResultDTO,
    RecommendationSnapshotDTO,
    StockContributionDTO,
)
from app_module.recommendation_portfolio_backtest_service import (
    RecommendationPortfolioBacktestService,
)
from app_module.recommendation_replay_service import RecommendationReplayService


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
