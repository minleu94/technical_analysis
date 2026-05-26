from app_module.recommendation_portfolio_optimizer_service import (
    RecommendationPortfolioOptimizerService,
)


class FakeBacktestService:
    def run_portfolio_backtest(self, **kwargs):
        top_n = kwargs["top_n"]
        total_return = 0.10 if top_n == 2 else 0.03
        max_drawdown = -0.02 if top_n == 2 else -0.01
        return type(
            "Result",
            (),
            {
                "summary": {
                    "total_return": total_return,
                    "max_drawdown": max_drawdown,
                    "total_trades": top_n,
                }
            },
        )()


def test_optimizer_ranks_parameter_sets_by_objective_score():
    optimizer = RecommendationPortfolioOptimizerService(FakeBacktestService())
    results = optimizer.grid_search(
        base_request={
            "start_date": "2026-01-02",
            "end_date": "2026-01-06",
            "profile_id": "momentum",
            "recommendation_config": {},
            "history": None,
            "initial_capital": 1000000.0,
            "rebalance_frequency": "once",
            "allocation_method": "equal_weight",
            "holding_days": 4,
        },
        param_grid={"top_n": [1, 2]},
        drawdown_penalty=1.0,
        min_trades=1,
    )

    assert results[0]["params"]["top_n"] == 2
    assert results[0]["score"] == 0.08
