"""將已注入的研究輸入組合為唯讀 Advice dashboard。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from app_module.advice_dtos import (
    AdviceAction,
    AdviceClassification,
    AdviceDashboardDTO,
    AdviceMode,
    PortfolioAdviceDTO,
    RecommendationAdviceDTO,
)
from app_module.advice_policy import AdvicePolicy
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.portfolio_construction_dtos import PortfolioAllocationRow, PortfolioConstructionResult
from app_module.portfolio_allocation_dtos import (
    PortfolioAllocationResultV2,
    PortfolioAllocationRowV2,
)


class AdviceComposer:
    """僅依呼叫端注入的 payload 組裝可追溯 Advice，不讀取任何外部狀態。"""

    def __init__(self, policy: AdvicePolicy) -> None:
        self._policy = policy

    def compose(
        self,
        *,
        recommendations: RecommendationResultDTO | Sequence[RecommendationDTO],
        portfolio_result: PortfolioConstructionResult | PortfolioAllocationResultV2 | None,
        evidence_quality: str | None,
        decision_date: date | str,
        data_as_of_date: date | str,
        mode: AdviceMode,
        evidence_warnings: Sequence[str] = (),
        current_weights_bp: Mapping[str, int] | None = None,
    ) -> AdviceDashboardDTO:
        decision_date_text = self._date_text(decision_date, "decision_date")
        data_as_of_date_text = self._date_text(data_as_of_date, "data_as_of_date")
        if data_as_of_date_text > decision_date_text:
            raise ValueError("data_as_of_date must not be later than decision_date")
        if portfolio_result is not None:
            portfolio_decision_date = self._date_text(
                portfolio_result.decision_date,
                "portfolio_result.decision_date",
            )
            if portfolio_decision_date > decision_date_text:
                raise ValueError(
                    "portfolio_result.decision_date must not be later than decision_date"
                )

        warning_values = self._strings(evidence_warnings, "evidence_warnings")
        current_weights_known = current_weights_bp is not None
        current_weights = self._weights(current_weights_bp or {})
        result_id, config, recommendation_rows = self._recommendation_payload(recommendations)
        legacy_allocations = (
            portfolio_result.allocations
            if isinstance(portfolio_result, PortfolioConstructionResult)
            else ()
        )
        allocation_v2_rows = (
            portfolio_result.rows
            if isinstance(portfolio_result, PortfolioAllocationResultV2)
            else ()
        )
        targets = {
            row.stock_code: self._bp(row.constrained_weight_bp, "target_weight_bp")
            for row in legacy_allocations
        }
        targets.update(
            {
                row.stock_code: self._bp(row.target_weight_bp, "target_weight_bp")
                for row in allocation_v2_rows
            }
        )
        cash_reserve_bp = self._cash_reserve_bp(portfolio_result)
        current_position_count = (
            sum(1 for weight in current_weights.values() if weight > 0)
            if current_weights_known
            else None
        )
        strategy_status = self._string_or_none(config.get("strategy_status"))
        parameters_locked = self._bool_or_none(config.get("parameters_locked"))
        disclosure_complete = self._bool_or_none(config.get("disclosure_complete"))
        execution_feasible = config.get("execution_feasible")
        risk_budget_available = config.get("risk_budget_available")

        recommendation_advice: tuple[RecommendationAdviceDTO, ...]
        if evidence_quality == "MISSING":
            recommendation_advice = (
                self._refusal_recommendation(
                    decision_date_text,
                    data_as_of_date_text,
                    warning_values,
                ),
            )
        else:
            recommendation_advice = tuple(
                self._recommendation_advice(
                    recommendation,
                    result_id=result_id,
                    strategy_status=strategy_status,
                    parameters_locked=parameters_locked,
                    disclosure_complete=disclosure_complete,
                    mode=mode,
                    evidence_quality=evidence_quality,
                    execution_feasible=execution_feasible,
                    risk_budget_available=risk_budget_available,
                    current_position_count=current_position_count,
                    cash_reserve_bp=cash_reserve_bp,
                    target_weight_bp=targets.get(recommendation.stock_code),
                    decision_date=decision_date_text,
                    data_as_of_date=data_as_of_date_text,
                    warnings=warning_values,
                    strategy_version=self._string_or_empty(config.get("strategy_version")),
                    market_regime=self._string_or_empty(config.get("market_regime") or config.get("regime")),
                )
                for recommendation in recommendation_rows
            )

        legacy_portfolio_advice = tuple(
            self._portfolio_advice(
                allocation,
                current_weights=current_weights,
                result_id=result_id,
                data_as_of_date=data_as_of_date_text,
                evidence_quality=evidence_quality or "",
                warnings=warning_values,
            )
            for allocation in legacy_allocations
        )
        v2_portfolio_advice: tuple[PortfolioAdviceDTO, ...] = ()
        if isinstance(portfolio_result, PortfolioAllocationResultV2):
            v2_portfolio_advice = tuple(
                self._portfolio_advice_v2(
                    allocation,
                    result=portfolio_result,
                    data_as_of_date=data_as_of_date_text,
                    evidence_quality=evidence_quality or "",
                    warnings=warning_values,
                )
                for allocation in allocation_v2_rows
            )
        portfolio_advice = (*legacy_portfolio_advice, *v2_portfolio_advice)
        diagnostics = (
            tuple(portfolio_result.diagnostics)
            if isinstance(portfolio_result, PortfolioConstructionResult)
            else tuple(portfolio_result.reasons)
            if isinstance(portfolio_result, PortfolioAllocationResultV2)
            else ("portfolio_result_missing",)
        )
        return AdviceDashboardDTO(
            decision_date=decision_date_text,
            data_as_of_date=data_as_of_date_text,
            mode=mode,
            policy=self._policy._config,
            recommendations=recommendation_advice,
            portfolio_rows=portfolio_advice,
            diagnostics=diagnostics,
            warnings=warning_values,
        )

    def _recommendation_advice(
        self,
        recommendation: RecommendationDTO,
        *,
        result_id: str,
        strategy_status: str | None,
        parameters_locked: bool | None,
        disclosure_complete: bool | None,
        mode: AdviceMode,
        evidence_quality: str | None,
        execution_feasible: object,
        risk_budget_available: object,
        current_position_count: int | None,
        cash_reserve_bp: int | None,
        target_weight_bp: int | None,
        decision_date: str,
        data_as_of_date: str,
        warnings: tuple[str, ...],
        strategy_version: str,
        market_regime: str,
    ) -> RecommendationAdviceDTO:
        decision = self._policy.decide(
            mode=mode,
            strategy_status=strategy_status,
            parameters_locked=parameters_locked,
            disclosure_complete=disclosure_complete,
            data_quality=evidence_quality,
            execution_feasible=self._bool_or_none(execution_feasible),
            risk_budget_available=self._bool_or_none(risk_budget_available),
            current_position_count=current_position_count,
            cash_reserve_bp=cash_reserve_bp,
            target_weight_bp=target_weight_bp,
        )
        source_trace = ("RecommendationResultDTO",) + ((str(result_id),) if result_id else ())
        risk_reasons = self._recommendation_risk_reasons(
            decision_reasons=decision.reasons,
            evidence_quality=evidence_quality,
            execution_feasible=self._bool_or_none(execution_feasible),
            risk_budget_available=self._bool_or_none(risk_budget_available),
            warnings=warnings,
        )
        return RecommendationAdviceDTO(
            stock_code=recommendation.stock_code,
            advice_action=decision.action,
            classification=self._classification(mode, decision.reasons),
            why_reasons=tuple(self._split_reasons(recommendation.recommendation_reasons)),
            why_not_reasons=decision.reasons,
            risk_reasons=risk_reasons,
            data_quality=evidence_quality or "",
            warnings=warnings,
            strategy_version=strategy_version,
            decision_date=decision_date,
            data_as_of_date=data_as_of_date,
            market_regime=market_regime,
            execution_feasibility=self._feasibility_text(execution_feasible),
            source_trace=source_trace,
            refusal_reasons=decision.reasons,
        )

    @staticmethod
    def _refusal_recommendation(decision_date: str, data_as_of_date: str, warnings: tuple[str, ...]) -> RecommendationAdviceDTO:
        return RecommendationAdviceDTO(
            stock_code="",
            advice_action=AdviceAction.NO_NEW_POSITION,
            data_quality="MISSING",
            warnings=warnings,
            decision_date=decision_date,
            data_as_of_date=data_as_of_date,
            source_trace=("RecommendationResultDTO",),
            why_not_reasons=("evidence_quality_missing",),
            risk_reasons=("evidence_quality_missing", *warnings),
            refusal_reasons=("evidence_quality_missing",),
        )

    def _portfolio_advice(
        self,
        allocation: PortfolioAllocationRow,
        *,
        current_weights: Mapping[str, int],
        result_id: str,
        data_as_of_date: str,
        evidence_quality: str,
        warnings: tuple[str, ...],
    ) -> PortfolioAdviceDTO:
        stock_code = allocation.stock_code
        target_weight_bp = self._bp(allocation.constrained_weight_bp, "target_weight_bp")
        missing_current_weight = stock_code not in current_weights
        current_weight_bp = current_weights.get(stock_code)
        weight_gap_bp = (
            None if current_weight_bp is None else target_weight_bp - current_weight_bp
        )
        diagnostics = tuple(allocation.diagnostics) + (("current_weight_missing",) if missing_current_weight else ())
        source_trace = ("PortfolioConstructionResult",) + ((str(result_id),) if result_id else ())
        action, reasons = self._allocation_action(
            target_weight_bp=target_weight_bp,
            current_weight_bp=current_weight_bp,
            weight_gap_bp=weight_gap_bp,
        )
        return PortfolioAdviceDTO(
            stock_code=stock_code,
            advice_action=action,
            target_weight_bp=target_weight_bp,
            current_weight_bp=current_weight_bp,
            weight_gap_bp=weight_gap_bp,
            executable_weight_bp=None,
            reasons=reasons,
            risk_reasons=tuple(
                diagnostic
                for diagnostic in diagnostics
                if any(
                    token in diagnostic.lower()
                    for token in ("risk", "health", "watch", "exit", "liquidity", "cash", "cap")
                )
            ),
            data_quality=evidence_quality,
            warnings=warnings,
            execution_feasibility=(
                "UNKNOWN" if missing_current_weight else "FEASIBLE"
            ),
            source_trace=source_trace,
            review_date=data_as_of_date,
            diagnostics=diagnostics,
        )

    def _portfolio_advice_v2(
        self,
        allocation: PortfolioAllocationRowV2,
        *,
        result: PortfolioAllocationResultV2,
        data_as_of_date: str,
        evidence_quality: str,
        warnings: tuple[str, ...],
    ) -> PortfolioAdviceDTO:
        current_weight_bp = allocation.current_weight_bp
        executable_weight_bp = allocation.executable_weight_bp
        diagnostics = tuple(allocation.diagnostics)
        action, action_reasons = self._allocation_action_v2(
            target_weight_bp=allocation.target_weight_bp,
            current_weight_bp=current_weight_bp,
            weight_gap_bp=allocation.gap_weight_bp,
            executable_weight_bp=executable_weight_bp,
            diagnostics=diagnostics,
        )
        source_trace = (
            "PortfolioAllocationResultV2",
            result.dataset_identity_hash,
            result.dataset_manifest_file_hash,
            result.model_hash,
            result.policy_hash,
        )
        risk_reasons = tuple(
            diagnostic
            for diagnostic in diagnostics
            if any(
                token in diagnostic.lower()
                for token in (
                    "risk",
                    "health",
                    "watch",
                    "exit",
                    "liquidity",
                    "cash",
                    "cap",
                    "cooldown",
                )
            )
        )
        return PortfolioAdviceDTO(
            stock_code=allocation.stock_code,
            advice_action=action,
            target_weight_bp=allocation.target_weight_bp,
            current_weight_bp=current_weight_bp,
            weight_gap_bp=allocation.gap_weight_bp,
            executable_weight_bp=executable_weight_bp,
            reasons=tuple(dict.fromkeys((*action_reasons, *result.reasons))),
            risk_reasons=risk_reasons,
            data_quality=evidence_quality,
            warnings=warnings,
            execution_feasibility=(
                "UNKNOWN"
                if current_weight_bp is None or executable_weight_bp is None
                else "FEASIBLE"
            ),
            source_trace=source_trace,
            review_date=data_as_of_date,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _allocation_action(
        *,
        target_weight_bp: int,
        current_weight_bp: int | None,
        weight_gap_bp: int | None,
    ) -> tuple[AdviceAction, tuple[str, ...]]:
        if current_weight_bp is None or weight_gap_bp is None:
            return AdviceAction.NO_NEW_POSITION, ("current_weight_missing",)
        if target_weight_bp == 0 and current_weight_bp > 0:
            return AdviceAction.EXIT_CANDIDATE, ("target_weight_zero",)
        if weight_gap_bp <= -300:
            return AdviceAction.REDUCE_CANDIDATE, ("allocation_gap_reduce",)
        if weight_gap_bp >= 300:
            return AdviceAction.ADD_CANDIDATE, ("allocation_gap_add",)
        return AdviceAction.HOLD, ("within_rebalance_band",)

    @classmethod
    def _allocation_action_v2(
        cls,
        *,
        target_weight_bp: int,
        current_weight_bp: int | None,
        weight_gap_bp: int | None,
        executable_weight_bp: int | None,
        diagnostics: tuple[str, ...],
    ) -> tuple[AdviceAction, tuple[str, ...]]:
        if (
            current_weight_bp is None
            or weight_gap_bp is None
            or executable_weight_bp is None
        ):
            return AdviceAction.NO_NEW_POSITION, ("current_portfolio_state_incomplete",)
        diagnostic_text = "|".join(diagnostics).lower()
        hard_exit = any(
            token in diagnostic_text
            for token in ("hard_risk:", "exit_candidate", "closed_target_zero")
        )
        if target_weight_bp == 0 and current_weight_bp > 0 and hard_exit:
            return AdviceAction.EXIT_CANDIDATE, ("hard_exit_target_zero",)
        executable_gap = executable_weight_bp - current_weight_bp
        if executable_gap < 0:
            return AdviceAction.REDUCE_CANDIDATE, ("executable_weight_reduction",)
        if executable_gap > 0:
            return AdviceAction.ADD_CANDIDATE, ("executable_weight_increase",)
        return cls._allocation_action(
            target_weight_bp=target_weight_bp,
            current_weight_bp=current_weight_bp,
            weight_gap_bp=weight_gap_bp,
        )

    @staticmethod
    def _recommendation_payload(
        recommendations: RecommendationResultDTO | Sequence[RecommendationDTO],
    ) -> tuple[str, Mapping[str, object], tuple[RecommendationDTO, ...]]:
        if isinstance(recommendations, RecommendationResultDTO):
            return recommendations.result_id, recommendations.config, tuple(recommendations.recommendations)
        return "", {}, tuple(recommendations)

    @classmethod
    def _weights(cls, values: Mapping[str, int]) -> dict[str, int]:
        return {str(stock_code): cls._bp(weight, "current_weight_bp") for stock_code, weight in values.items()}

    @classmethod
    def _cash_reserve_bp(
        cls,
        result: PortfolioConstructionResult | PortfolioAllocationResultV2 | None,
    ) -> int | None:
        if isinstance(result, PortfolioAllocationResultV2):
            return result.target_weights.cash_weight_bp
        if result is None or result.capital_amount <= Decimal(0):
            return None
        try:
            return int((result.residual_cash * Decimal(10000)) // result.capital_amount)
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _bp(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10000:
            raise ValueError(f"{field_name} must be an integer bp value between 0 and 10000")
        return value

    @staticmethod
    def _date_text(value: date | str, field_name: str) -> str:
        if isinstance(value, date):
            return value.isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field_name} must be an ISO date") from error

    @staticmethod
    def _strings(values: Sequence[str], field_name: str) -> tuple[str, ...]:
        if not all(isinstance(value, str) for value in values):
            raise ValueError(f"{field_name} must contain strings")
        return tuple(values)

    @staticmethod
    def _string_or_none(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _string_or_empty(value: object) -> str:
        return value if isinstance(value, str) else ""

    @staticmethod
    def _bool_or_none(value: object) -> bool | None:
        return value if isinstance(value, bool) else None

    @staticmethod
    def _split_reasons(value: object) -> tuple[str, ...]:
        return tuple(part.strip() for part in str(value).replace("；", ";").split(";") if part.strip())

    @staticmethod
    def _recommendation_risk_reasons(
        *,
        decision_reasons: tuple[str, ...],
        evidence_quality: str | None,
        execution_feasible: bool | None,
        risk_budget_available: bool | None,
        warnings: tuple[str, ...],
    ) -> tuple[str, ...]:
        reasons: list[str] = list(warnings)
        if evidence_quality != "OBSERVED":
            reasons.append(
                "data_quality_missing"
                if evidence_quality is None
                else f"data_quality:{evidence_quality.lower()}"
            )
        if execution_feasible is not True:
            reasons.append("execution_feasibility_not_confirmed")
        if risk_budget_available is not True:
            reasons.append("risk_budget_not_confirmed")
        risk_tokens = (
            "risk",
            "cash",
            "position",
            "weight",
            "execution",
            "quality",
            "strategy",
            "disclosure",
        )
        reasons.extend(
            reason
            for reason in decision_reasons
            if any(token in reason.lower() for token in risk_tokens)
        )
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _feasibility_text(value: object) -> str:
        return "FEASIBLE" if value is True else "NOT_FEASIBLE"

    @staticmethod
    def _classification(mode: AdviceMode, reasons: tuple[str, ...]) -> AdviceClassification:
        if mode is AdviceMode.PROFESSIONAL and "professional_candidate_research_only" in reasons:
            return AdviceClassification.PROFESSIONAL_CANDIDATE
        return AdviceClassification.FORMAL_ADVICE
