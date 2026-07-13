"""Cost-adjusted weekly read model for research paper portfolios."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app_module.paper_equal_weight_benchmark_ledger import EqualWeightBenchmarkEntry
from app_module.paper_portfolio_snapshot_repository import PaperPortfolioSnapshot


@dataclass(frozen=True)
class PaperTradeCostRecord:
    decision_date: str
    total_cost: Decimal
    turnover_bp: int

    def __post_init__(self) -> None:
        if not isinstance(self.total_cost, Decimal) or self.total_cost < 0:
            raise ValueError("total_cost must be a non-negative Decimal")
        if isinstance(self.turnover_bp, bool) or not isinstance(self.turnover_bp, int) or self.turnover_bp < 0:
            raise ValueError("turnover_bp must be a non-negative integer")


@dataclass(frozen=True)
class PaperPortfolioWeeklyReport:
    period_start: str
    period_end: str
    observed_trading_days: int
    gross_return_bp: int
    net_return_bp: int
    benchmark_return_bp: int
    net_excess_return_bp: int
    total_cost: Decimal
    turnover_bp: int
    data_quality: str
    warnings: tuple[str, ...]
    research_only: bool = True
    investment_effectiveness_claim: bool = False


class PaperPortfolioWeeklyReportService:
    def build(
        self,
        *,
        portfolio_snapshots: Iterable[PaperPortfolioSnapshot],
        benchmark_entries: Iterable[EqualWeightBenchmarkEntry],
        trade_costs: Iterable[PaperTradeCostRecord],
        expected_trading_days: int,
    ) -> PaperPortfolioWeeklyReport:
        snapshots = tuple(sorted(portfolio_snapshots, key=lambda item: item.decision_date))
        benchmarks = tuple(sorted(benchmark_entries, key=lambda item: item.decision_date))
        if len(snapshots) < 2 or len(benchmarks) < 2:
            raise ValueError("weekly report requires at least two portfolio and benchmark observations")
        if expected_trading_days <= 0:
            raise ValueError("expected_trading_days must be positive")
        if (snapshots[0].decision_date, snapshots[-1].decision_date) != (
            benchmarks[0].decision_date,
            benchmarks[-1].decision_date,
        ):
            raise ValueError("portfolio and benchmark require aligned boundary dates")
        costs = tuple(trade_costs)
        total_cost = sum((item.total_cost for item in costs), Decimal("0")).quantize(
            Decimal("0.01")
        )
        gross = _return_bp(snapshots[0].total_value, snapshots[-1].total_value)
        net_end = snapshots[-1].total_value - total_cost
        net = _return_bp(snapshots[0].total_value, net_end)
        benchmark = _return_bp(benchmarks[0].total_value, benchmarks[-1].total_value)
        observed_days = len({item.decision_date for item in snapshots})
        warnings = () if observed_days >= expected_trading_days else ("incomplete_trading_week",)
        return PaperPortfolioWeeklyReport(
            period_start=snapshots[0].decision_date,
            period_end=snapshots[-1].decision_date,
            observed_trading_days=observed_days,
            gross_return_bp=gross,
            net_return_bp=net,
            benchmark_return_bp=benchmark,
            net_excess_return_bp=net - benchmark,
            total_cost=total_cost,
            turnover_bp=sum(item.turnover_bp for item in costs),
            data_quality="OBSERVED" if not warnings else "DEGRADED",
            warnings=warnings,
        )


def _return_bp(start: Decimal, end: Decimal) -> int:
    if start <= 0:
        raise ValueError("return denominator must be positive")
    return int((end - start) * 10000 / start)
