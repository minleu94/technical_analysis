from decimal import Decimal

import pytest


def test_balanced_paper_policy_returns_candidate_for_valid_rebalance() -> None:
    from app_module.paper_portfolio_policy import (
        PaperPortfolioPolicy,
        PaperPortfolioPolicyConfig,
        PaperPortfolioRebalanceInput,
        PaperPortfolioAction,
    )

    decision = PaperPortfolioPolicy(PaperPortfolioPolicyConfig()).evaluate(
        PaperPortfolioRebalanceInput(
            stock_code="2330",
            current_weight_bp=500,
            target_weight_bp=1500,
            current_cash_bp=3000,
            sector_weight_after_bp=2500,
            weekly_turnover_used_bp=500,
            trading_days_since_last_trade=5,
        )
    )

    assert decision.action is PaperPortfolioAction.PAPER_TRADE_CANDIDATE
    assert decision.weight_gap_bp == 1000
    assert decision.estimated_round_trip_cost_bp == 80
    assert decision.research_only is True


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"current_cash_bp": 1999}, "minimum_cash_reserve_not_met"),
        ({"sector_weight_after_bp": 3001}, "sector_cap_exceeded"),
        ({"weekly_turnover_used_bp": 1501}, "weekly_turnover_cap_exceeded"),
        ({"trading_days_since_last_trade": 4}, "same_symbol_cooldown_active"),
    ],
)
def test_balanced_paper_policy_fails_closed_when_a_risk_limit_is_breached(
    changes: dict[str, int],
    reason: str,
) -> None:
    from app_module.paper_portfolio_policy import (
        PaperPortfolioAction,
        PaperPortfolioPolicy,
        PaperPortfolioPolicyConfig,
        PaperPortfolioRebalanceInput,
    )

    values = {
        "stock_code": "2330",
        "current_weight_bp": 500,
        "target_weight_bp": 1500,
        "current_cash_bp": 3000,
        "sector_weight_after_bp": 2500,
        "weekly_turnover_used_bp": 500,
        "trading_days_since_last_trade": 5,
    }
    values.update(changes)
    decision = PaperPortfolioPolicy(PaperPortfolioPolicyConfig()).evaluate(
        PaperPortfolioRebalanceInput(**values)
    )

    assert decision.action is PaperPortfolioAction.NO_PAPER_TRADE
    assert decision.reasons == (reason,)


def test_policy_rejects_float_money_and_invalid_bp_configuration() -> None:
    from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig

    with pytest.raises(ValueError, match="initial_capital"):
        PaperPortfolioPolicyConfig(initial_capital=500000.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_positions"):
        PaperPortfolioPolicyConfig(max_positions=9)

