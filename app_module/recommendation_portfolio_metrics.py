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


def generate_improvement_hints(summary: Dict[str, Any]) -> List[str]:
    """根據回測總覽指標與診斷數據，產生具體的 rule-based 改善建議。"""
    hints = []
    
    total_trades = summary.get("total_trades", 0)
    if total_trades == 0:
        return ["💡 提示：回測期間沒有任何推薦交易。建議檢查推薦 Profile 篩選條件是否過於嚴格，或歷史資料庫中該段期間是否有完整的個股資料。"]

    # 1. 停損太頻繁
    stop_loss_exits = summary.get("stop_loss_exits", 0)
    if total_trades > 0 and stop_loss_exits > 0:
        stop_loss_ratio = stop_loss_exits / total_trades
        if stop_loss_ratio > 0.3:
            hints.append(
                f"💡 停損出場次數過高（佔比 {stop_loss_ratio * 100:.1f}%）。"
                "這顯示停損百分比（stop_loss_pct）設得太窄，或推薦的股票在進場後波動較大。建議適度放寬停損空間，或檢查推薦 Profile/Config 是否在市場回撤期仍過於積極進場。"
            )

    # 2. 持有到期績效差
    holding_period_exits = summary.get("holding_period_exits", 0)
    total_return = summary.get("total_return", 0.0)
    if total_trades > 0 and holding_period_exits > 0 and total_return < 0:
        holding_ratio = holding_period_exits / total_trades
        if holding_ratio > 0.5:
            hints.append(
                f"💡 大部分持倉均持有至期滿出場（佔比 {holding_ratio * 100:.1f}%），但整體為虧損。"
                "這代表預設的持有天數（holding_days）可能過長，無法在推薦股票衝高時及時鎖利，或者推薦的股票缺乏持續的動能。建議縮短持有天數，或適度加入停利機制（take_profit_pct）。"
            )

    # 3. 單一股票曝險過高
    worst_stock_pnl = summary.get("worst_stock_pnl", 0.0)
    worst_stock_code = summary.get("worst_stock_code", "")
    worst_stock_name = summary.get("worst_stock_name", "")
    capital_used = summary.get("capital_used", 1000000.0) or 1000000.0
    
    if worst_stock_pnl < 0 and (abs(worst_stock_pnl) / capital_used) > 0.05:
        stock_display = f"{worst_stock_code} {worst_stock_name}" if worst_stock_name else worst_stock_code
        hints.append(
            f"💡 單一最差個股（{stock_display}）的虧損金額達 {abs(worst_stock_pnl):,.0f}，佔整體資金比例較高。"
            "這顯示個股曝險過大，或缺乏有效的停損控制。建議調降單檔個股的配置權重（可調整增加 top_n），或引入/收緊停損機制（stop_loss_pct）以限制單筆極端損失。"
        )

    # 4. 交易次數過少
    if total_trades < 3:
        hints.append(
            f"💡 回測期間交易次數過少（僅 {total_trades} 次）。"
            "這通常是因為 rebalance_frequency (重播頻率) 限制過嚴，或 prefilter 的候選上限太窄，導致多數日期因條件不符而未產生推薦。建議放寬 prefilter 限制或調整 rebalance_frequency。"
        )

    # 5. 未能擊敗大盤/表現欠佳
    if total_return < 0:
        hints.append(
            "💡 整體報酬率為負值，未能達到穩定獲利目標。"
            "建議重新檢視推薦 Profile 的篩選指標（例如調整 technical 或 pattern 因子權重），或在 Regime Service 顯示空頭（Bearish）時降低交易比重。"
        )

    return hints
