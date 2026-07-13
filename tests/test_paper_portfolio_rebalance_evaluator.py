from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig
from app_module.paper_portfolio_rebalance_evaluator import (
    PaperRebalanceCandidate,
    PaperPortfolioRebalanceEvaluator,
)


def test_evaluator_emits_non_applying_candidate() -> None:
    result = PaperPortfolioRebalanceEvaluator(PaperPortfolioPolicyConfig()).evaluate(
        portfolio_id="paper-main",
        decision_date="2026-07-12",
        current_cash_bp=3000,
        weekly_turnover_used_bp=0,
        candidates=(
            PaperRebalanceCandidate(
                stock_code="2330",
                current_weight_bp=500,
                target_weight_bp=1000,
                sector_weight_after_bp=2000,
                trading_days_since_last_trade=10,
            ),
        ),
    )

    assert result.proposals[0].action == "PAPER_TRADE_CANDIDATE"
    assert result.proposals[0].weight_gap_bp == 500
    assert result.apply_rebalance is False
    assert result.broker_order_allowed is False


def test_turnover_is_reserved_across_batch_in_order() -> None:
    result = PaperPortfolioRebalanceEvaluator(
        PaperPortfolioPolicyConfig(weekly_turnover_cap_bp=700)
    ).evaluate(
        portfolio_id="paper-main",
        decision_date="2026-07-12",
        current_cash_bp=3000,
        weekly_turnover_used_bp=0,
        candidates=(
            PaperRebalanceCandidate("2330", 500, 1000, 2000, 10),
            PaperRebalanceCandidate("2317", 500, 1000, 2000, 10),
        ),
    )

    assert result.proposals[0].action == "PAPER_TRADE_CANDIDATE"
    assert result.proposals[1].action == "NO_PAPER_TRADE"
    assert "weekly_turnover_cap_exceeded" in result.proposals[1].reasons


def test_target_weight_above_cap_is_rejected() -> None:
    result = PaperPortfolioRebalanceEvaluator().evaluate(
        portfolio_id="paper-main",
        decision_date="2026-07-12",
        current_cash_bp=3000,
        weekly_turnover_used_bp=0,
        candidates=(PaperRebalanceCandidate("2330", 500, 1600, 2000, 10),),
    )

    assert result.proposals[0].action == "NO_PAPER_TRADE"
    assert "single_position_cap_exceeded" in result.proposals[0].reasons
