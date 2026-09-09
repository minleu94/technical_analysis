"""Governed position thesis and structured invalidation contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping


VALID_OPERATORS = frozenset({"gt", "gte", "lt", "lte", "eq"})
VALID_INVALIDATION_ACTIONS = frozenset({"reduce", "exit"})
VALID_THESIS_SOURCE_TYPES = frozenset({"human_reviewed", "machine_policy"})


@dataclass(frozen=True)
class PositionInvalidationRule:
    metric_id: str
    operator: str
    threshold: Decimal
    action: str = "exit"

    def __post_init__(self) -> None:
        if not self.metric_id:
            raise ValueError("metric_id is required")
        if self.operator not in VALID_OPERATORS:
            raise ValueError("unsupported invalidation operator")
        if self.action not in VALID_INVALIDATION_ACTIONS:
            raise ValueError("action must be reduce or exit")
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, Decimal):
            raise ValueError("threshold must be Decimal")
        if not self.threshold.is_finite():
            raise ValueError("threshold must be finite")

    def to_dict(self) -> dict[str, str]:
        return {
            "metric_id": self.metric_id,
            "operator": self.operator,
            "threshold": str(self.threshold),
            "action": self.action,
        }


@dataclass(frozen=True)
class PositionThesisContract:
    position_id: str
    stock_code: str
    entry_date: str
    decision_date: str
    available_date: str
    entry_thesis: str
    holding_horizon_trading_days: int
    next_review_date: str
    source_trace: tuple[str, ...]
    invalidation_rules: tuple[PositionInvalidationRule, ...]
    schema_version: str = "position-thesis.v1"
    auto_exit_allowed: bool = False
    # ``human_reviewed`` preserves the historical registry semantics.  A
    # ``machine_policy`` contract is an explicit, source-bound observation
    # for proposal-only evaluation; it is never human approval or a broker
    # instruction.
    source_type: str = "human_reviewed"
    source_actor: str = "human_reviewer"

    def __post_init__(self) -> None:
        if not self.position_id or not self.stock_code or not self.entry_thesis.strip():
            raise ValueError("position_id, stock_code and entry_thesis are required")
        if _date(self.available_date) > _date(self.decision_date):
            raise ValueError("available_date cannot be after decision_date")
        if _date(self.entry_date) > _date(self.decision_date):
            raise ValueError("entry_date cannot be after decision_date")
        if _date(self.next_review_date) < _date(self.decision_date):
            raise ValueError("next_review_date cannot precede decision_date")
        if isinstance(self.holding_horizon_trading_days, bool) or not isinstance(
            self.holding_horizon_trading_days, int
        ) or self.holding_horizon_trading_days <= 0:
            raise ValueError("holding_horizon_trading_days must be positive")
        if not self.source_trace or not all(item.strip() for item in self.source_trace):
            raise ValueError("source_trace requires non-empty entries")
        if not self.invalidation_rules:
            raise ValueError("at least one invalidation rule is required")
        if self.auto_exit_allowed:
            raise ValueError("position thesis contract cannot enable auto exit")
        if self.source_type not in VALID_THESIS_SOURCE_TYPES:
            raise ValueError("unsupported thesis source type")
        if not self.source_actor.strip():
            raise ValueError("source_actor is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "position_id": self.position_id,
            "stock_code": self.stock_code,
            "entry_date": self.entry_date,
            "decision_date": self.decision_date,
            "available_date": self.available_date,
            "entry_thesis": self.entry_thesis,
            "holding_horizon_trading_days": self.holding_horizon_trading_days,
            "next_review_date": self.next_review_date,
            "source_trace": list(self.source_trace),
            "invalidation_rules": [item.to_dict() for item in self.invalidation_rules],
            "auto_exit_allowed": self.auto_exit_allowed,
            "source_type": self.source_type,
            "source_actor": self.source_actor,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PositionThesisContract":
        """Rebuild a contract from a governed, JSON-compatible record.

        The registry boundary uses this constructor instead of accepting a
        loosely shaped dictionary in the evaluator.  Decimal thresholds are
        parsed explicitly so a JSON number can never enter the core rule
        engine as a binary float.
        """

        if not isinstance(payload, Mapping):
            raise ValueError("position thesis payload must be an object")
        raw_rules = payload.get("invalidation_rules")
        if not isinstance(raw_rules, (list, tuple)):
            raise ValueError("invalidation_rules must be a list")
        rules: list[PositionInvalidationRule] = []
        for raw_rule in raw_rules:
            if not isinstance(raw_rule, Mapping):
                raise ValueError("invalidation rule must be an object")
            threshold = raw_rule.get("threshold")
            if isinstance(threshold, bool) or threshold is None:
                raise ValueError("invalidation threshold is required")
            if isinstance(threshold, float):
                raise ValueError("invalidation threshold must be Decimal text")
            try:
                decimal_threshold = Decimal(str(threshold))
            except Exception as exc:  # noqa: BLE001 - contract boundary
                raise ValueError("invalidation threshold must be Decimal text") from exc
            rules.append(
                PositionInvalidationRule(
                    metric_id=str(raw_rule.get("metric_id") or ""),
                    operator=str(raw_rule.get("operator") or ""),
                    threshold=decimal_threshold,
                    action=str(raw_rule.get("action") or "exit"),
                )
            )
        raw_trace = payload.get("source_trace")
        if not isinstance(raw_trace, (list, tuple)):
            raise ValueError("source_trace must be a list")
        horizon = payload.get("holding_horizon_trading_days")
        if isinstance(horizon, bool) or not isinstance(horizon, int):
            raise ValueError("holding_horizon_trading_days must be an integer")
        return cls(
            position_id=str(payload.get("position_id") or ""),
            stock_code=str(payload.get("stock_code") or ""),
            entry_date=str(payload.get("entry_date") or ""),
            decision_date=str(payload.get("decision_date") or ""),
            available_date=str(payload.get("available_date") or ""),
            entry_thesis=str(payload.get("entry_thesis") or ""),
            holding_horizon_trading_days=horizon,
            next_review_date=str(payload.get("next_review_date") or ""),
            source_trace=tuple(str(item) for item in raw_trace),
            invalidation_rules=tuple(rules),
            schema_version=str(payload.get("schema_version") or "position-thesis.v1"),
            auto_exit_allowed=bool(payload.get("auto_exit_allowed", False)),
            source_type=str(payload.get("source_type") or "human_reviewed"),
            source_actor=str(payload.get("source_actor") or "human_reviewer"),
        )


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
