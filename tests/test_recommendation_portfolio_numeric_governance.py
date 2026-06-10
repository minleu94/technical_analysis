import pandas as pd

from app_module.recommendation_portfolio_backtest_service import RecommendationPortfolioBacktestService
from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationPortfolioBacktestResultDTO,
)


def make_holding() -> PeriodHoldingDTO:
    return PeriodHoldingDTO(
        rebalance_date="2026-01-02",
        stock_code="2330",
        stock_name="台積電",
        rank=1,
        total_score=90.0,
        factor_scores={},
        allocation_amount=1000.10,
        allocation_weight=1.0,
        entry_date="2026-01-02",
        entry_price=10.0,
        planned_exit_date="2026-01-05",
        actual_exit_date="2026-01-05",
        actual_exit_price=10.70,
        exit_reason="holding_period",
        holding_days=3,
        return_pct=0.07,
    )


def test_period_holding_pnl_is_quantized_to_cents() -> None:
    holding = make_holding()

    assert holding.pnl() == 70.01


def test_period_holdings_dataframe_reports_quantized_pnl() -> None:
    result = RecommendationPortfolioBacktestResultDTO(
        summary={},
        equity_curve=pd.DataFrame(),
        trades=pd.DataFrame(),
        snapshots=[],
        period_holdings=[make_holding()],
        stock_contribution=[],
    )

    assert result.period_holdings_dataframe().iloc[0]["損益"] == 70.01


def test_mark_to_market_pnl_is_quantized_to_cents() -> None:
    service = RecommendationPortfolioBacktestService(provider=lambda *_args: [])
    data = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "收盤價": 10.0},
            {"日期": "2026-01-03", "證券代號": "2330", "收盤價": 10.70},
        ]
    )
    data["日期"] = pd.to_datetime(data["日期"])

    pnl = service._holding_pnl_at_date(
        holding=make_holding(),
        data=data,
        ts=pd.Timestamp("2026-01-03"),
    )

    assert pnl == 70.01
