from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceEventType(str, Enum):
    WATCHLIST_TRIGGER = "watchlist_trigger"
    WATCHLIST_TRIGGER_ADDED = "watchlist_trigger_added"
    WATCHLIST_TRIGGER_REMOVED = "watchlist_trigger_removed"
    WATCHLIST_TRIGGER_STRENGTH_UP = "watchlist_trigger_strength_up"
    WATCHLIST_TRIGGER_STRENGTH_DOWN = "watchlist_trigger_strength_down"
    WATCHLIST_TRIGGER_RISK_ALERT = "watchlist_trigger_risk_alert"
    RECOMMENDATION_INCLUDED = "recommendation_included"
    WHY_NOT_EXCLUDED = "why_not_excluded"
    LIQUIDITY_GATE_EXCLUDED = "liquidity_gate_excluded"
    PORTFOLIO_ALERT = "portfolio_alert"
    PORTFOLIO_ALERT_CONDITION_WARNING = "portfolio_alert_condition_warning"
    PORTFOLIO_ALERT_CONDITION_INVALID = "portfolio_alert_condition_invalid"
    PORTFOLIO_ALERT_CHIP_RISK = "portfolio_alert_chip_risk"
    PORTFOLIO_ALERT_DATA_QUALITY = "portfolio_alert_data_quality"
    RISK_PROMPT_LOW_LIQUIDITY = "risk_prompt_low_liquidity"
    RISK_PROMPT_RELATIVE_WEAKNESS = "risk_prompt_relative_weakness"
    RISK_PROMPT_FUNDAMENTAL_DIAGNOSTIC = "risk_prompt_fundamental_diagnostic"
    RISK_PROMPT_DATA_QUALITY = "risk_prompt_data_quality"
    STRATEGY_LIFECYCLE = "strategy_lifecycle"


class EvidenceOutcomeStatus(str, Enum):
    READY = "ready"
    PENDING = "pending"
    MISSING_PRICE = "missing_price"
    INSUFFICIENT_FUTURE_DATA = "insufficient_future_data"


class EvidenceDataQuality(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    DEGRADED = "degraded"
    MISSING = "missing"


def normalize_event_type(value: EvidenceEventType | str) -> EvidenceEventType:
    if isinstance(value, EvidenceEventType):
        return value
    return EvidenceEventType(str(value))


def normalize_outcome_status(value: EvidenceOutcomeStatus | str) -> EvidenceOutcomeStatus:
    if isinstance(value, EvidenceOutcomeStatus):
        return value
    return EvidenceOutcomeStatus(str(value))


def normalize_data_quality(value: EvidenceDataQuality | str) -> EvidenceDataQuality:
    if isinstance(value, EvidenceDataQuality):
        return value
    return EvidenceDataQuality(str(value))


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("metadata JSON field must be an object")
    return dict(value)


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: str
    event_hash: str
    event_date: str
    decision_date: str
    symbol: str | None
    event_type: EvidenceEventType | str
    event_family: str
    source_type: str
    source_id: str = ""
    source_snapshot_id: str = ""
    strategy_version_id: str = ""
    profile_id: str = ""
    run_id: str = ""
    reason_codes: tuple[str, ...] = ()
    why_not_codes: tuple[str, ...] = ()
    risk_codes: tuple[str, ...] = ()
    score_bp: int | None = None
    score_percentile_bp: int | None = None
    regime: str | None = None
    sector: str | None = None
    concept_basket: str | None = None
    liquidity_state: str | None = None
    data_quality: EvidenceDataQuality | str = EvidenceDataQuality.MISSING
    warnings: tuple[str, ...] = ()
    as_of_date: str = ""
    available_date: str = ""
    source_version: str = ""
    cost_model_id: str = ""
    benchmark_id: str | None = None
    industry_benchmark_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", normalize_event_type(self.event_type))
        object.__setattr__(self, "data_quality", normalize_data_quality(self.data_quality))
        object.__setattr__(self, "reason_codes", _tuple_of_str(self.reason_codes))
        object.__setattr__(self, "why_not_codes", _tuple_of_str(self.why_not_codes))
        object.__setattr__(self, "risk_codes", _tuple_of_str(self.risk_codes))
        object.__setattr__(self, "warnings", _tuple_of_str(self.warnings))
        object.__setattr__(self, "metadata", _dict(self.metadata))


@dataclass(frozen=True)
class EvidenceOutcome:
    outcome_id: str
    event_id: str
    window_days: int
    window_type: str = "trading_days"
    return_basis: str = "close_to_close_event_date"
    event_price_date: str | None = None
    event_close: str | None = None
    outcome_price_date: str | None = None
    outcome_close: str | None = None
    forward_return_bp: int | None = None
    benchmark_return_bp: int | None = None
    benchmark_excess_bp: int | None = None
    industry_return_bp: int | None = None
    industry_excess_bp: int | None = None
    max_adverse_excursion_bp: int | None = None
    max_favorable_excursion_bp: int | None = None
    tradable_flag: bool | None = None
    limit_up_down_flag: bool | None = None
    suspended_flag: bool | None = None
    liquidity_cost_bp: int | None = None
    outcome_status: EvidenceOutcomeStatus | str = EvidenceOutcomeStatus.PENDING
    data_quality: EvidenceDataQuality | str = EvidenceDataQuality.MISSING
    warnings: tuple[str, ...] = ()
    calculated_at: str = ""
    data_as_of_date: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_days", int(self.window_days))
        object.__setattr__(self, "outcome_status", normalize_outcome_status(self.outcome_status))
        object.__setattr__(self, "data_quality", normalize_data_quality(self.data_quality))
        object.__setattr__(self, "warnings", _tuple_of_str(self.warnings))
        object.__setattr__(self, "metadata", _dict(self.metadata))
