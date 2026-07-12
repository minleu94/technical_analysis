from __future__ import annotations

from dataclasses import dataclass

from app_module.advice_dtos import AdviceAction, AdviceMode, AdvicePolicyConfig


@dataclass(frozen=True)
class AdvicePolicyDecision:
    action: AdviceAction
    reasons: tuple[str, ...] = ()


class AdvicePolicy:
    """以明確輸入產生可拒絕的新增持倉政策決策。"""

    def __init__(self, config: AdvicePolicyConfig | None = None) -> None:
        self._config = config or AdvicePolicyConfig()

    def decide(
        self,
        *,
        mode: AdviceMode,
        strategy_status: str | None,
        data_quality: str | None,
        execution_feasible: bool | None,
        risk_budget_available: bool | None,
        current_position_count: int | None = None,
        cash_reserve_bp: int | None = None,
        target_weight_bp: int | None = None,
    ) -> AdvicePolicyDecision:
        strategy_decision = self._strategy_decision(mode, strategy_status)
        if strategy_decision is not None:
            return strategy_decision

        quality_decision = self._quality_decision(data_quality)
        if quality_decision is not None:
            return quality_decision

        if execution_feasible is not True:
            return AdvicePolicyDecision(AdviceAction.AVOID, ("execution_not_feasible",))

        if risk_budget_available is not True:
            return AdvicePolicyDecision(AdviceAction.NO_NEW_POSITION, ("risk_budget_unavailable",))

        if not self._is_non_negative_integer(current_position_count):
            return AdvicePolicyDecision(AdviceAction.RESEARCH, ("position_count_missing_or_invalid",))
        if current_position_count >= self._config.max_positions:
            return AdvicePolicyDecision(AdviceAction.NO_NEW_POSITION, ("max_positions_reached",))

        if not self._is_bp(cash_reserve_bp):
            return AdvicePolicyDecision(AdviceAction.RESEARCH, ("cash_reserve_missing_or_invalid",))
        if cash_reserve_bp < self._config.min_cash_reserve_bp:
            return AdvicePolicyDecision(AdviceAction.NO_NEW_POSITION, ("min_cash_reserve_not_met",))

        if not self._is_bp(target_weight_bp):
            return AdvicePolicyDecision(AdviceAction.RESEARCH, ("target_weight_missing_or_invalid",))
        if target_weight_bp > self._config.max_single_position_bp:
            return AdvicePolicyDecision(AdviceAction.NO_NEW_POSITION, ("max_single_position_exceeded",))

        return AdvicePolicyDecision(AdviceAction.ADD_CANDIDATE)

    @staticmethod
    def _strategy_decision(
        mode: AdviceMode,
        strategy_status: str | None,
    ) -> AdvicePolicyDecision | None:
        if strategy_status == "promoted":
            return None
        if mode is AdviceMode.GUIDED:
            return AdvicePolicyDecision(
                AdviceAction.NO_NEW_POSITION,
                ("guided_mode_strategy_not_promoted",),
            )
        if strategy_status == "candidate":
            return AdvicePolicyDecision(
                AdviceAction.RESEARCH,
                ("professional_candidate_research_only",),
            )
        return AdvicePolicyDecision(AdviceAction.RESEARCH, ("strategy_status_not_promoted",))

    @staticmethod
    def _quality_decision(data_quality: str | None) -> AdvicePolicyDecision | None:
        if data_quality is None:
            return AdvicePolicyDecision(AdviceAction.RESEARCH, ("data_quality_missing",))
        if data_quality == "OBSERVED":
            return None
        if data_quality == "DEGRADED":
            return AdvicePolicyDecision(AdviceAction.RESEARCH, ("data_quality_degraded",))
        return AdvicePolicyDecision(AdviceAction.RESEARCH, ("data_quality_not_observed",))

    @staticmethod
    def _is_non_negative_integer(value: int | None) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    @classmethod
    def _is_bp(cls, value: int | None) -> bool:
        return cls._is_non_negative_integer(value) and value <= 10000
