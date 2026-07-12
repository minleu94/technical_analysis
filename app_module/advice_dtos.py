from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class AdviceAction(str, Enum):
    RESEARCH = "RESEARCH"
    ADD_CANDIDATE = "ADD_CANDIDATE"
    HOLD = "HOLD"
    REDUCE_CANDIDATE = "REDUCE_CANDIDATE"
    EXIT_CANDIDATE = "EXIT_CANDIDATE"
    AVOID = "AVOID"
    NO_NEW_POSITION = "NO_NEW_POSITION"


class AdviceMode(str, Enum):
    GUIDED = "GUIDED"
    PROFESSIONAL = "PROFESSIONAL"


def _payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Advice JSON payload must be an object")
    return value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("Advice JSON collection must be an array")
    if not all(isinstance(item, str) for item in value):
        raise ValueError("Advice JSON collection items must be strings")
    return tuple(value)


@dataclass(frozen=True)
class AdvicePolicyConfig:
    mode: AdviceMode = AdviceMode.GUIDED
    min_cash_reserve_bp: int = 2000
    max_positions: int = 8
    max_single_position_bp: int = 1500

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "min_cash_reserve_bp": self.min_cash_reserve_bp,
            "max_positions": self.max_positions,
            "max_single_position_bp": self.max_single_position_bp,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AdvicePolicyConfig:
        payload = _payload(value)
        return cls(
            mode=AdviceMode(payload.get("mode", AdviceMode.GUIDED.value)),
            min_cash_reserve_bp=payload.get("min_cash_reserve_bp", 2000),
            max_positions=payload.get("max_positions", 8),
            max_single_position_bp=payload.get("max_single_position_bp", 1500),
        )


@dataclass(frozen=True)
class RecommendationAdviceDTO:
    stock_code: str
    advice_action: AdviceAction
    why_reasons: tuple[str, ...] = ()
    why_not_reasons: tuple[str, ...] = ()
    risk_reasons: tuple[str, ...] = ()
    confidence_tier: str = ""
    evidence_tier: str = ""
    data_quality: str = ""
    warnings: tuple[str, ...] = ()
    strategy_version: str = ""
    decision_date: str = ""
    data_as_of_date: str = ""
    holding_horizon: str = ""
    entry_thesis: str = ""
    invalidation_conditions: tuple[str, ...] = ()
    market_regime: str = ""
    liquidity_state: str = ""
    execution_feasibility: str = ""
    source_trace: tuple[str, ...] = ()
    refusal_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "advice_action": self.advice_action.value,
            "why_reasons": list(self.why_reasons),
            "why_not_reasons": list(self.why_not_reasons),
            "risk_reasons": list(self.risk_reasons),
            "confidence_tier": self.confidence_tier,
            "evidence_tier": self.evidence_tier,
            "data_quality": self.data_quality,
            "warnings": list(self.warnings),
            "strategy_version": self.strategy_version,
            "decision_date": self.decision_date,
            "data_as_of_date": self.data_as_of_date,
            "holding_horizon": self.holding_horizon,
            "entry_thesis": self.entry_thesis,
            "invalidation_conditions": list(self.invalidation_conditions),
            "market_regime": self.market_regime,
            "liquidity_state": self.liquidity_state,
            "execution_feasibility": self.execution_feasibility,
            "source_trace": list(self.source_trace),
            "refusal_reasons": list(self.refusal_reasons),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RecommendationAdviceDTO:
        payload = _payload(value)
        return cls(
            stock_code=payload["stock_code"],
            advice_action=AdviceAction(payload["advice_action"]),
            why_reasons=_string_tuple(payload.get("why_reasons")),
            why_not_reasons=_string_tuple(payload.get("why_not_reasons")),
            risk_reasons=_string_tuple(payload.get("risk_reasons")),
            confidence_tier=payload.get("confidence_tier", ""),
            evidence_tier=payload.get("evidence_tier", ""),
            data_quality=payload.get("data_quality", ""),
            warnings=_string_tuple(payload.get("warnings")),
            strategy_version=payload.get("strategy_version", ""),
            decision_date=payload.get("decision_date", ""),
            data_as_of_date=payload.get("data_as_of_date", ""),
            holding_horizon=payload.get("holding_horizon", ""),
            entry_thesis=payload.get("entry_thesis", ""),
            invalidation_conditions=_string_tuple(payload.get("invalidation_conditions")),
            market_regime=payload.get("market_regime", ""),
            liquidity_state=payload.get("liquidity_state", ""),
            execution_feasibility=payload.get("execution_feasibility", ""),
            source_trace=_string_tuple(payload.get("source_trace")),
            refusal_reasons=_string_tuple(payload.get("refusal_reasons")),
        )


@dataclass(frozen=True)
class PortfolioAdviceDTO:
    stock_code: str
    advice_action: AdviceAction
    target_weight_bp: int
    current_weight_bp: int
    weight_gap_bp: int
    reasons: tuple[str, ...] = ()
    risk_reasons: tuple[str, ...] = ()
    confidence_tier: str = ""
    evidence_tier: str = ""
    data_quality: str = ""
    warnings: tuple[str, ...] = ()
    holding_horizon: str = ""
    entry_thesis: str = ""
    invalidation_conditions: tuple[str, ...] = ()
    market_regime: str = ""
    strategy_version: str = ""
    liquidity_state: str = ""
    execution_feasibility: str = ""
    source_trace: tuple[str, ...] = ()
    review_date: str = ""
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "advice_action": self.advice_action.value,
            "target_weight_bp": self.target_weight_bp,
            "current_weight_bp": self.current_weight_bp,
            "weight_gap_bp": self.weight_gap_bp,
            "reasons": list(self.reasons),
            "risk_reasons": list(self.risk_reasons),
            "confidence_tier": self.confidence_tier,
            "evidence_tier": self.evidence_tier,
            "data_quality": self.data_quality,
            "warnings": list(self.warnings),
            "holding_horizon": self.holding_horizon,
            "entry_thesis": self.entry_thesis,
            "invalidation_conditions": list(self.invalidation_conditions),
            "market_regime": self.market_regime,
            "strategy_version": self.strategy_version,
            "liquidity_state": self.liquidity_state,
            "execution_feasibility": self.execution_feasibility,
            "source_trace": list(self.source_trace),
            "review_date": self.review_date,
            "diagnostics": list(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PortfolioAdviceDTO:
        payload = _payload(value)
        return cls(
            stock_code=payload["stock_code"],
            advice_action=AdviceAction(payload["advice_action"]),
            target_weight_bp=payload["target_weight_bp"],
            current_weight_bp=payload["current_weight_bp"],
            weight_gap_bp=payload["weight_gap_bp"],
            reasons=_string_tuple(payload.get("reasons")),
            risk_reasons=_string_tuple(payload.get("risk_reasons")),
            confidence_tier=payload.get("confidence_tier", ""),
            evidence_tier=payload.get("evidence_tier", ""),
            data_quality=payload.get("data_quality", ""),
            warnings=_string_tuple(payload.get("warnings")),
            holding_horizon=payload.get("holding_horizon", ""),
            entry_thesis=payload.get("entry_thesis", ""),
            invalidation_conditions=_string_tuple(payload.get("invalidation_conditions")),
            market_regime=payload.get("market_regime", ""),
            strategy_version=payload.get("strategy_version", ""),
            liquidity_state=payload.get("liquidity_state", ""),
            execution_feasibility=payload.get("execution_feasibility", ""),
            source_trace=_string_tuple(payload.get("source_trace")),
            review_date=payload.get("review_date", ""),
            diagnostics=_string_tuple(payload.get("diagnostics")),
        )


@dataclass(frozen=True)
class AdviceDashboardDTO:
    decision_date: str
    data_as_of_date: str
    mode: AdviceMode
    policy: AdvicePolicyConfig
    recommendations: tuple[RecommendationAdviceDTO, ...] = ()
    portfolio_rows: tuple[PortfolioAdviceDTO, ...] = ()
    diagnostics: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date,
            "data_as_of_date": self.data_as_of_date,
            "mode": self.mode.value,
            "policy": self.policy.to_dict(),
            "recommendations": [row.to_dict() for row in self.recommendations],
            "portfolio_rows": [row.to_dict() for row in self.portfolio_rows],
            "diagnostics": list(self.diagnostics),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AdviceDashboardDTO:
        payload = _payload(value)
        recommendations = payload.get("recommendations", ())
        portfolio_rows = payload.get("portfolio_rows", ())
        if not isinstance(recommendations, (list, tuple)):
            raise ValueError("Advice dashboard recommendations must be an array")
        if not isinstance(portfolio_rows, (list, tuple)):
            raise ValueError("Advice dashboard portfolio_rows must be an array")
        return cls(
            decision_date=payload["decision_date"],
            data_as_of_date=payload["data_as_of_date"],
            mode=AdviceMode(payload["mode"]),
            policy=AdvicePolicyConfig.from_dict(payload.get("policy", {})),
            recommendations=tuple(RecommendationAdviceDTO.from_dict(row) for row in recommendations),
            portfolio_rows=tuple(PortfolioAdviceDTO.from_dict(row) for row in portfolio_rows),
            diagnostics=_string_tuple(payload.get("diagnostics")),
            warnings=_string_tuple(payload.get("warnings")),
        )
