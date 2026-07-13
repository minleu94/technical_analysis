"""Portfolio-level governed rebalance proposals for the paper ledger."""

from __future__ import annotations

from dataclasses import dataclass

from app_module.paper_portfolio_policy import (
    PaperPortfolioAction,
    PaperPortfolioPolicy,
    PaperPortfolioPolicyConfig,
    PaperPortfolioRebalanceInput,
)


@dataclass(frozen=True)
class PaperRebalanceCandidate:
    stock_code: str
    current_weight_bp: int
    target_weight_bp: int
    sector_weight_after_bp: int
    trading_days_since_last_trade: int


@dataclass(frozen=True)
class PaperRebalanceProposal:
    stock_code: str
    action: str
    weight_gap_bp: int
    estimated_round_trip_cost_bp: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PaperRebalanceEvaluation:
    portfolio_id: str
    decision_date: str
    proposals: tuple[PaperRebalanceProposal, ...]
    apply_rebalance: bool = False
    broker_order_allowed: bool = False
    research_only: bool = True


class PaperPortfolioRebalanceEvaluator:
    def __init__(self, config: PaperPortfolioPolicyConfig | None = None) -> None:
        self._config = config or PaperPortfolioPolicyConfig()
        self._policy = PaperPortfolioPolicy(self._config)

    def evaluate(
        self,
        *,
        portfolio_id: str,
        decision_date: str,
        current_cash_bp: int,
        weekly_turnover_used_bp: int,
        candidates: tuple[PaperRebalanceCandidate, ...],
    ) -> PaperRebalanceEvaluation:
        used = weekly_turnover_used_bp
        proposals: list[PaperRebalanceProposal] = []
        for item in candidates:
            decision = self._policy.evaluate(
                PaperPortfolioRebalanceInput(
                    stock_code=item.stock_code,
                    current_weight_bp=item.current_weight_bp,
                    target_weight_bp=item.target_weight_bp,
                    current_cash_bp=current_cash_bp,
                    sector_weight_after_bp=item.sector_weight_after_bp,
                    weekly_turnover_used_bp=used,
                    trading_days_since_last_trade=item.trading_days_since_last_trade,
                )
            )
            proposals.append(
                PaperRebalanceProposal(
                    stock_code=item.stock_code,
                    action=decision.action.value,
                    weight_gap_bp=decision.weight_gap_bp,
                    estimated_round_trip_cost_bp=decision.estimated_round_trip_cost_bp,
                    reasons=decision.reasons,
                )
            )
            if decision.action is PaperPortfolioAction.PAPER_TRADE_CANDIDATE:
                used += abs(decision.weight_gap_bp)
        return PaperRebalanceEvaluation(
            portfolio_id=portfolio_id,
            decision_date=decision_date,
            proposals=tuple(proposals),
        )
