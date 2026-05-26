import pandas as pd

from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationPortfolioBacktestResultDTO,
    RecommendationSnapshotDTO,
    StockContributionDTO,
)


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
