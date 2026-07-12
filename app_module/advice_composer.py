"""將已注入的研究輸入組合為唯讀 Advice dashboard。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from app_module.advice_dtos import (
    AdviceAction,
    AdviceDashboardDTO,
    AdviceMode,
    PortfolioAdviceDTO,
    RecommendationAdviceDTO,
)
from app_module.advice_policy import AdvicePolicy
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.portfolio_construction_dtos import PortfolioConstructionResult


class AdviceComposer:
    """僅依呼叫端注入的 payload 組裝可追溯 Advice，不讀取任何外部狀態。"""

    def __init__(self, policy: AdvicePolicy) -> None:
        self._policy = policy

    def compose(
        self,
        *,
        recommendations: RecommendationResultDTO | Sequence[RecommendationDTO],
        portfolio_result: PortfolioConstructionResult | None,
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

        warning_values = self._strings(evidence_warnings, "evidence_warnings")
        current_weights = self._weights(current_weights_bp or {})
        result_id, config, recommendation_rows = self._recommendation_payload(recommendations)
        allocations = portfolio_result.allocations if portfolio_result is not None else ()
        targets = {row.stock_code: self._bp(row.constrained_weight_bp, "target_weight_bp") for row in allocations}
        cash_reserve_bp = self._cash_reserve_bp(portfolio_result)
        current_position_count = sum(1 for weight in current_weights.values() if weight > 0)
        strategy_status = self._string_or_none(config.get("strategy_status"))
        execution_feasible = config.get("execution_feasible")
        risk_budget_available = config.get("risk_budget_available")

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

        portfolio_advice = tuple(
            self._portfolio_advice(
                allocation,
                current_weights=current_weights,
                result_id=result_id,
                decision_date=decision_date_text,
                data_as_of_date=data_as_of_date_text,
                evidence_quality=evidence_quality or "",
                warnings=warning_values,
            )
            for allocation in allocations
        )
        diagnostics = tuple(portfolio_result.diagnostics) if portfolio_result is not None else ("portfolio_result_missing",)
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

    def _recommendation_advice(self, recommendation: RecommendationDTO, **values: object) -> RecommendationAdviceDTO:
        decision = self._policy.decide(
            mode=values["mode"],
            strategy_status=values["strategy_status"],
            data_quality=values["evidence_quality"],
            execution_feasible=values["execution_feasible"],
            risk_budget_available=values["risk_budget_available"],
            current_position_count=values["current_position_count"],
            cash_reserve_bp=values["cash_reserve_bp"],
            target_weight_bp=values["target_weight_bp"],
        )
        result_id = values["result_id"]
        source_trace = ("RecommendationResultDTO",) + ((str(result_id),) if result_id else ())
        return RecommendationAdviceDTO(
            stock_code=recommendation.stock_code,
            advice_action=decision.action,
            why_reasons=tuple(self._split_reasons(recommendation.recommendation_reasons)),
            data_quality=str(values["evidence_quality"] or ""),
            warnings=values["warnings"],
            strategy_version=values["strategy_version"],
            decision_date=values["decision_date"],
            data_as_of_date=values["data_as_of_date"],
            market_regime=values["market_regime"],
            execution_feasibility=self._feasibility_text(values["execution_feasible"]),
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
            refusal_reasons=("evidence_quality_missing",),
        )

    def _portfolio_advice(self, allocation: object, **values: object) -> PortfolioAdviceDTO:
        stock_code = allocation.stock_code
        target_weight_bp = self._bp(allocation.constrained_weight_bp, "target_weight_bp")
        current_weights = values["current_weights"]
        missing_current_weight = stock_code not in current_weights
        current_weight_bp = current_weights.get(stock_code, 0)
        diagnostics = tuple(allocation.diagnostics) + (("current_weight_missing",) if missing_current_weight else ())
        result_id = values["result_id"]
        source_trace = ("PortfolioConstructionResult",) + ((str(result_id),) if result_id else ())
        return PortfolioAdviceDTO(
            stock_code=stock_code,
            advice_action=AdviceAction.RESEARCH,
            target_weight_bp=target_weight_bp,
            current_weight_bp=current_weight_bp,
            weight_gap_bp=target_weight_bp - current_weight_bp,
            data_quality=values["evidence_quality"],
            warnings=values["warnings"],
            source_trace=source_trace,
            review_date=values["data_as_of_date"],
            diagnostics=diagnostics,
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
    def _cash_reserve_bp(cls, result: PortfolioConstructionResult | None) -> int | None:
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
    def _split_reasons(value: object) -> tuple[str, ...]:
        return tuple(part.strip() for part in str(value).replace("；", ";").split(";") if part.strip())

    @staticmethod
    def _feasibility_text(value: object) -> str:
        return "FEASIBLE" if value is True else "NOT_FEASIBLE"
