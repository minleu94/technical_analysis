"""Governed position thesis and structured invalidation contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


VALID_OPERATORS = frozenset({"gt", "gte", "lt", "lte", "eq"})


@dataclass(frozen=True)
class PositionInvalidationRule:
    metric_id: str
    operator: str
    threshold: Decimal

    def __post_init__(self) -> None:
        if not self.metric_id:
            raise ValueError("metric_id is required")
        if self.operator not in VALID_OPERATORS:
            raise ValueError("unsupported invalidation operator")
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, Decimal):
            raise ValueError("threshold must be Decimal")

    def to_dict(self) -> dict[str, str]:
        return {
            "metric_id": self.metric_id,
            "operator": self.operator,
            "threshold": str(self.threshold),
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
        }


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
