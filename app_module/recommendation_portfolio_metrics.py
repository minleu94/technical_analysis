"""Robustness metrics for recommendation portfolio backtests."""

from __future__ import annotations

from typing import Iterable, Dict

import numpy as np
import pandas as pd


def calculate_robustness_metrics(
    equity_curve: pd.DataFrame,
    trade_returns: Iterable[float],
    monte_carlo_runs: int = 500,
    random_seed: int = 42,
) -> Dict[str, float]:
    """Calculate risk-adjusted and trade-sequence robustness metrics."""
    returns = _equity_returns(equity_curve)
    trade_returns_array = np.array([float(value) for value in trade_returns], dtype=float)

    return {
        "sharpe_ratio": _calculate_sharpe_ratio(returns),
        "sortino_ratio": _calculate_sortino_ratio(returns),
        **_calculate_monte_carlo_returns(
            trade_returns=trade_returns_array,
            monte_carlo_runs=monte_carlo_runs,
            random_seed=random_seed,
        ),
    }


def _equity_returns(equity_curve: pd.DataFrame) -> pd.Series:
    if equity_curve is None or equity_curve.empty or "equity" not in equity_curve.columns:
        return pd.Series(dtype=float)
    equity = pd.to_numeric(equity_curve["equity"], errors="coerce").dropna()
    return equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()


def _calculate_sharpe_ratio(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    volatility = float(returns.std(ddof=0))
    if volatility == 0:
        return 0.0
    return float((returns.mean() / volatility) * np.sqrt(252))


def _calculate_sortino_ratio(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    downside = returns[returns < 0]
    if downside.empty:
        return 0.0
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))) * np.sqrt(252))
    if downside_deviation == 0:
        return 0.0
    annualized_return = float(returns.mean() * 252)
    return annualized_return / downside_deviation


def _calculate_monte_carlo_returns(
    trade_returns: np.ndarray,
    monte_carlo_runs: int,
    random_seed: int,
) -> Dict[str, float]:
    if trade_returns.size == 0 or monte_carlo_runs <= 0:
        return {
            "monte_carlo_p05_return": 0.0,
            "monte_carlo_p50_return": 0.0,
            "monte_carlo_p95_return": 0.0,
        }

    rng = np.random.default_rng(random_seed)
    simulated_returns = []
    for _ in range(monte_carlo_runs):
        shuffled = rng.permutation(trade_returns)
        total_return = float(np.prod(1.0 + shuffled) - 1.0)
        simulated_returns.append(total_return)

    percentiles = np.percentile(simulated_returns, [5, 50, 95])
    return {
        "monte_carlo_p05_return": float(percentiles[0]),
        "monte_carlo_p50_return": float(percentiles[1]),
        "monte_carlo_p95_return": float(percentiles[2]),
    }
