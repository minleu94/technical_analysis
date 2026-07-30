from __future__ import annotations

import pytest

from app_module.advice_dtos import (
    AdviceAction,
    AdviceClassification,
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


def test_portfolio_advice_round_trip_preserves_unknown_current_weight() -> None:
    row = PortfolioAdviceDTO(
        stock_code="2330",
        advice_action=AdviceAction.NO_NEW_POSITION,
        target_weight_bp=1500,
        current_weight_bp=None,
        weight_gap_bp=None,
        reasons=("current_weight_missing",),
    )

    assert PortfolioAdviceDTO.from_dict(row.to_dict()) == row


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


def test_professional_candidate_round_trip_and_action_guard() -> None:
    row = RecommendationAdviceDTO(
        stock_code="2330",
        advice_action=AdviceAction.RESEARCH,
        classification=AdviceClassification.PROFESSIONAL_CANDIDATE,
    )

    assert RecommendationAdviceDTO.from_dict(row.to_dict()) == row
    with pytest.raises(ValueError, match="RESEARCH"):
        RecommendationAdviceDTO(
            stock_code="2330",
            advice_action=AdviceAction.ADD_CANDIDATE,
            classification=AdviceClassification.PROFESSIONAL_CANDIDATE,
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("min_cash_reserve_bp", 1.5),
        ("min_cash_reserve_bp", True),
        ("min_cash_reserve_bp", 10001),
        ("max_single_position_bp", 1.5),
        ("max_single_position_bp", True),
        ("max_single_position_bp", 1501),
    ),
)
def test_policy_rejects_invalid_bp_direct_construction(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        AdvicePolicyConfig(**{field_name: invalid_value})


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("target_weight_bp", 1.5),
        ("target_weight_bp", True),
        ("target_weight_bp", 10001),
        ("current_weight_bp", 1.5),
        ("current_weight_bp", True),
        ("current_weight_bp", 10001),
        ("weight_gap_bp", 1.5),
        ("weight_gap_bp", True),
        ("weight_gap_bp", 10001),
    ),
)
def test_portfolio_advice_rejects_invalid_bp_direct_construction(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "stock_code": "2330",
        "advice_action": AdviceAction.ADD_CANDIDATE,
        "target_weight_bp": 1500,
        "current_weight_bp": 0,
        "weight_gap_bp": 1500,
    }
    values[field_name] = invalid_value

    with pytest.raises(ValueError, match=field_name):
        PortfolioAdviceDTO(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_value", (1.5, True))
def test_json_payload_rejects_non_integer_bp(invalid_value: object) -> None:
    with pytest.raises(ValueError, match="min_cash_reserve_bp"):
        AdvicePolicyConfig.from_dict({"min_cash_reserve_bp": invalid_value})

    with pytest.raises(ValueError, match="target_weight_bp"):
        PortfolioAdviceDTO.from_dict(
            {
                "stock_code": "2330",
                "advice_action": "ADD_CANDIDATE",
                "target_weight_bp": invalid_value,
                "current_weight_bp": 0,
                "weight_gap_bp": 0,
            }
        )
