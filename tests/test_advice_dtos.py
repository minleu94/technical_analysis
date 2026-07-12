from __future__ import annotations

from app_module.advice_dtos import (
    AdviceAction,
    AdviceDashboardDTO,
    AdviceMode,
    AdvicePolicyConfig,
    PortfolioAdviceDTO,
    RecommendationAdviceDTO,
)


def test_portfolio_advice_round_trip_preserves_integer_bp() -> None:
    row = PortfolioAdviceDTO(
        stock_code="2330",
        advice_action=AdviceAction.ADD_CANDIDATE,
        target_weight_bp=1500,
        current_weight_bp=0,
        weight_gap_bp=1500,
        reasons=("score_eligible",),
    )

    payload = row.to_dict()

    assert payload["target_weight_bp"] == 1500
    assert isinstance(payload["target_weight_bp"], int)
    assert PortfolioAdviceDTO.from_dict(payload) == row


def test_advice_dashboard_round_trip_preserves_nested_json_contract() -> None:
    recommendation = RecommendationAdviceDTO(
        stock_code="2330",
        advice_action=AdviceAction.RESEARCH,
        why_reasons=("score_eligible",),
        decision_date="2026-07-12",
        data_as_of_date="2026-07-11",
        source_trace=("recommendation:run-1",),
    )
    portfolio = PortfolioAdviceDTO(
        stock_code="2330",
        advice_action=AdviceAction.ADD_CANDIDATE,
        target_weight_bp=1500,
        current_weight_bp=0,
        weight_gap_bp=1500,
    )
    dashboard = AdviceDashboardDTO(
        decision_date="2026-07-12",
        data_as_of_date="2026-07-11",
        mode=AdviceMode.GUIDED,
        policy=AdvicePolicyConfig(),
        recommendations=(recommendation,),
        portfolio_rows=(portfolio,),
    )

    payload = dashboard.to_dict()

    assert payload["mode"] == "GUIDED"
    assert payload["policy"]["min_cash_reserve_bp"] == 2000
    assert AdviceDashboardDTO.from_dict(payload) == dashboard
