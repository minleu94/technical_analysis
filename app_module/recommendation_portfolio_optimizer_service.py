import itertools
from typing import Any, Dict, List


class RecommendationPortfolioOptimizerService:
    def __init__(self, portfolio_backtest_service):
        self.portfolio_backtest_service = portfolio_backtest_service

    def grid_search(
        self,
        base_request: Dict[str, Any],
        param_grid: Dict[str, List[Any]],
        drawdown_penalty: float = 1.0,
        min_trades: int = 3,
    ) -> List[Dict[str, Any]]:
        param_names = list(param_grid.keys())
        results = []

        for values in itertools.product(*(param_grid[name] for name in param_names)):
            params = dict(zip(param_names, values))
            request = dict(base_request)
            request.update(params)

            result = self.portfolio_backtest_service.run_portfolio_backtest(**request)
            summary = result.summary
            invalid_sample_penalty = 1.0 if summary.get("total_trades", 0) < min_trades else 0.0
            score = (
                float(summary.get("total_return", 0.0))
                - abs(float(summary.get("max_drawdown", 0.0))) * drawdown_penalty
                - invalid_sample_penalty
            )
            results.append({"params": params, "summary": summary, "score": score})

        results.sort(key=lambda item: item["score"], reverse=True)
        return results
