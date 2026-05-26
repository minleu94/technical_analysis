from dataclasses import dataclass, field
from typing import Any, Dict, List

import pandas as pd


@dataclass
class RecommendationSnapshotDTO:
    as_of_date: str
    profile_id: str
    strategy_config: Dict[str, Any]
    regime: str
    recommendations: List[Dict[str, Any]]
    diagnostics: List[str] = field(default_factory=list)


@dataclass
class PeriodHoldingDTO:
    rebalance_date: str
    stock_code: str
    stock_name: str
    rank: int
    total_score: float
    factor_scores: Dict[str, float]
    allocation_amount: float
    allocation_weight: float
    entry_date: str
    entry_price: float
    planned_exit_date: str
    actual_exit_date: str
    actual_exit_price: float
    exit_reason: str
    holding_days: int
    return_pct: float

    def pnl(self) -> float:
        return self.allocation_amount * self.return_pct


@dataclass
class StockContributionDTO:
    stock_code: str
    stock_name: str
    selected_count: int
    total_pnl: float
    avg_return_pct: float
    win_rate: float
    worst_return_pct: float


@dataclass
class RecommendationPortfolioBacktestResultDTO:
    summary: Dict[str, Any]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    snapshots: List[RecommendationSnapshotDTO]
    period_holdings: List[PeriodHoldingDTO]
    stock_contribution: List[StockContributionDTO]
    selection_diagnostics: List[str] = field(default_factory=list)

    def period_holdings_dataframe(self) -> pd.DataFrame:
        columns = [
            "再平衡日",
            "股票代號",
            "股票名稱",
            "排名",
            "總分",
            "配置金額",
            "配置權重",
            "進場日",
            "進場價",
            "預計出場日",
            "實際出場日",
            "實際出場價",
            "出場原因",
            "持有天數",
            "報酬率",
            "損益",
        ]
        rows = []
        for holding in self.period_holdings:
            rows.append(
                {
                    "再平衡日": holding.rebalance_date,
                    "股票代號": holding.stock_code,
                    "股票名稱": holding.stock_name,
                    "排名": holding.rank,
                    "總分": holding.total_score,
                    "配置金額": holding.allocation_amount,
                    "配置權重": holding.allocation_weight,
                    "進場日": holding.entry_date,
                    "進場價": holding.entry_price,
                    "預計出場日": holding.planned_exit_date,
                    "實際出場日": holding.actual_exit_date,
                    "實際出場價": holding.actual_exit_price,
                    "出場原因": holding.exit_reason,
                    "持有天數": holding.holding_days,
                    "報酬率": holding.return_pct,
                    "損益": holding.pnl(),
                }
            )
        return pd.DataFrame(rows, columns=columns)

    def stock_contribution_dataframe(self) -> pd.DataFrame:
        columns = [
            "股票代號",
            "股票名稱",
            "被選次數",
            "總損益",
            "平均報酬率",
            "勝率",
            "最大單筆虧損",
        ]
        rows = []
        for item in self.stock_contribution:
            rows.append(
                {
                    "股票代號": item.stock_code,
                    "股票名稱": item.stock_name,
                    "被選次數": item.selected_count,
                    "總損益": item.total_pnl,
                    "平均報酬率": item.avg_return_pct,
                    "勝率": item.win_rate,
                    "最大單筆虧損": item.worst_return_pct,
                }
            )
        return pd.DataFrame(rows, columns=columns)
