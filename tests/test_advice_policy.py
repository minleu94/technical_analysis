from __future__ import annotations

import pytest

from app_module.advice_dtos import AdviceAction, AdviceMode, AdvicePolicyConfig
from app_module.advice_policy import AdvicePolicy


def test_guided_mode_rejects_candidate_strategy() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED,
        strategy_status="candidate",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
    )

    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert "guided_mode_strategy_not_promoted" in decision.reasons


def test_guided_mode_rejects_shadow_strategy() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED,
        strategy_status="shadow",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
    )

    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert decision.reasons == ("guided_mode_strategy_not_promoted",)


def test_guided_mode_requires_promoted_locked_and_disclosed_strategy() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
        current_position_count=0,
        cash_reserve_bp=2000,
        target_weight_bp=1500,
    )

    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert decision.reasons == ("guided_mode_strategy_parameters_not_locked",)


def test_advice_policy_config_rejects_position_cap_above_eight() -> None:
    with pytest.raises(ValueError, match="max_positions"):
        AdvicePolicyConfig(max_positions=9)


def test_policy_rejects_a_runtime_mutated_position_cap() -> None:
    config = AdvicePolicyConfig()
    object.__setattr__(config, "max_positions", 9)

    decision = AdvicePolicy(config).decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        parameters_locked=True,
        disclosure_complete=True,
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
        current_position_count=0,
        cash_reserve_bp=2000,
        target_weight_bp=1500,
    )

    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert decision.reasons == ("invalid_policy_max_positions",)


def test_guided_mode_rejects_incomplete_disclosure_even_when_parameters_are_locked() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        parameters_locked=True,
        disclosure_complete=False,
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
        current_position_count=0,
        cash_reserve_bp=2000,
        target_weight_bp=1500,
    )

    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert decision.reasons == ("guided_mode_strategy_disclosure_incomplete",)


def test_invalid_or_missing_mode_fails_closed() -> None:
    invalid_mode = AdvicePolicy().decide(
        mode="GUIDED",  # type: ignore[arg-type]
        strategy_status="candidate",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
    )
    missing_mode = AdvicePolicy().decide(
        mode=None,  # type: ignore[arg-type]
        strategy_status="candidate",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
    )

    assert invalid_mode.action is AdviceAction.NO_NEW_POSITION
    assert invalid_mode.reasons == ("invalid_mode",)
    assert missing_mode.action is AdviceAction.NO_NEW_POSITION
    assert missing_mode.reasons == ("invalid_mode",)


def test_call_mode_mismatch_with_policy_config_fails_closed() -> None:
    policy = AdvicePolicy(AdvicePolicyConfig(mode=AdviceMode.GUIDED))

    decision = policy.decide(
        mode=AdviceMode.PROFESSIONAL,
        strategy_status="candidate",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
    )

    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert decision.reasons == ("mode_config_mismatch",)


def test_exact_risk_boundaries_allow_add_candidate() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
        current_position_count=7,
        cash_reserve_bp=2000,
        target_weight_bp=1500,
        parameters_locked=True,
        disclosure_complete=True,
    )

    assert decision.action is AdviceAction.ADD_CANDIDATE
    assert decision.reasons == ()


def test_position_limit_returns_no_new_position() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
        current_position_count=8,
        cash_reserve_bp=2000,
        target_weight_bp=1500,
        parameters_locked=True,
        disclosure_complete=True,
    )

    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert decision.reasons == ("max_positions_reached",)


def test_missing_or_degraded_data_returns_research() -> None:
    policy = AdvicePolicy()

    missing = policy.decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality=None,
        execution_feasible=True,
        risk_budget_available=True,
        parameters_locked=True,
        disclosure_complete=True,
    )
    degraded = policy.decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality="DEGRADED",
        execution_feasible=True,
        risk_budget_available=True,
        parameters_locked=True,
        disclosure_complete=True,
    )

    assert missing.action is AdviceAction.RESEARCH
    assert missing.reasons == ("data_quality_missing",)
    assert degraded.action is AdviceAction.RESEARCH
    assert degraded.reasons == ("data_quality_degraded",)


def test_execution_infeasible_returns_avoid() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality="OBSERVED",
        execution_feasible=False,
        risk_budget_available=True,
        parameters_locked=True,
        disclosure_complete=True,
    )

    assert decision.action is AdviceAction.AVOID
    assert decision.reasons == ("execution_not_feasible",)


def test_unavailable_risk_budget_returns_no_new_position() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=False,
        parameters_locked=True,
        disclosure_complete=True,
    )

    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert decision.reasons == ("risk_budget_unavailable",)


def test_professional_candidate_is_research_only() -> None:
    decision = AdvicePolicy(AdvicePolicyConfig(mode=AdviceMode.PROFESSIONAL)).decide(
        mode=AdviceMode.PROFESSIONAL,
        strategy_status="candidate",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
    )

    assert decision.action is AdviceAction.RESEARCH
    assert decision.reasons == ("professional_candidate_research_only",)


def test_cash_and_single_position_limits_fail_closed() -> None:
    policy = AdvicePolicy(AdvicePolicyConfig())

    low_cash = policy.decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
        current_position_count=0,
        cash_reserve_bp=1999,
        target_weight_bp=1500,
        parameters_locked=True,
        disclosure_complete=True,
    )
    oversized = policy.decide(
        mode=AdviceMode.GUIDED,
        strategy_status="promoted",
        data_quality="OBSERVED",
        execution_feasible=True,
        risk_budget_available=True,
        current_position_count=0,
        cash_reserve_bp=2000,
        target_weight_bp=1501,
        parameters_locked=True,
        disclosure_complete=True,
    )

    assert low_cash.action is AdviceAction.NO_NEW_POSITION
    assert low_cash.reasons == ("min_cash_reserve_not_met",)
    assert oversized.action is AdviceAction.NO_NEW_POSITION
    assert oversized.reasons == ("max_single_position_exceeded",)
