"""Fail-closed, proposal-only position health state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from app_module.position_health_service import PositionHealthState
from app_module.position_thesis_contract import PositionInvalidationRule, PositionThesisContract


@dataclass(frozen=True)
class PositionHealthMetric:
    metric_id: str
    value: Decimal
    available_date: str

    def __post_init__(self) -> None:
        if not self.metric_id:
            raise ValueError("metric_id is required")
        if isinstance(self.value, bool) or not isinstance(self.value, Decimal):
            raise ValueError("metric value must be Decimal")


@dataclass(frozen=True)
class PositionHealthTransitionProposal:
    position_id: str
    previous_state: PositionHealthState
    proposed_state: PositionHealthState
    decision_date: str
    reasons: tuple[str, ...]
    apply_transition: bool = False
    auto_exit_allowed: bool = False


class PositionHealthStateMachine:
    def evaluate(
        self,
        *,
        current_state: PositionHealthState,
        thesis: PositionThesisContract,
        decision_date: str,
        metrics: Iterable[PositionHealthMetric],
        trading_dates: Iterable[str] | None = None,
    ) -> PositionHealthTransitionProposal:
        if current_state is PositionHealthState.CLOSED:
            return self._proposal(
                thesis, current_state, current_state, decision_date, "closed_state_is_terminal"
            )
        visible: dict[str, PositionHealthMetric] = {}
        reasons: list[str] = []
        for metric in metrics:
            if _date(metric.available_date) > _date(decision_date):
                reasons.append(f"future_metric_blocked:{metric.metric_id}")
                continue
            visible[metric.metric_id] = metric
        triggered: list[str] = []
        reduce_triggered: list[str] = []
        for rule in thesis.invalidation_rules:
            observed_metric = visible.get(rule.metric_id)
            if observed_metric is None:
                reasons.append(f"missing_metric:{rule.metric_id}")
            elif _matches(rule, observed_metric.value):
                reason = f"invalidation_triggered:{rule.metric_id}"
                if rule.action == "reduce":
                    reduce_triggered.append(reason)
                else:
                    triggered.append(reason)
        if triggered:
            state = PositionHealthState.EXIT_CANDIDATE
            reasons.extend(triggered)
        elif reduce_triggered:
            state = PositionHealthState.REDUCE_CANDIDATE
            reasons.extend(reduce_triggered)
        elif reasons:
            state = PositionHealthState.WATCH
        elif _date(decision_date) > _date(thesis.next_review_date):
            state = PositionHealthState.WATCH
            reasons.append("review_overdue")
        else:
            state = PositionHealthState.HEALTHY
            reasons.append("invalidation_not_triggered")

        # A time stop is a proposal to review or reduce, never an automatic
        # exit.  Require an explicit caller-supplied trading-day calendar so
        # exchange holidays are not guessed from weekdays.
        if (
            state in {PositionHealthState.HEALTHY, PositionHealthState.WATCH}
            and trading_dates is not None
        ):
            elapsed = _elapsed_trading_days(
                thesis.entry_date,
                decision_date,
                trading_dates,
            )
            if elapsed is None:
                reasons.append("time_stop_calendar_incomplete")
            elif elapsed >= thesis.holding_horizon_trading_days:
                state = PositionHealthState.REDUCE_CANDIDATE
                reasons.append(
                    "holding_horizon_reached:"
                    f"{elapsed}/{thesis.holding_horizon_trading_days}"
                )
        return PositionHealthTransitionProposal(
            position_id=thesis.position_id,
            previous_state=current_state,
            proposed_state=state,
            decision_date=decision_date,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def _proposal(
        thesis: PositionThesisContract,
        previous: PositionHealthState,
        proposed: PositionHealthState,
        decision_date: str,
        reason: str,
    ) -> PositionHealthTransitionProposal:
        return PositionHealthTransitionProposal(
            position_id=thesis.position_id,
            previous_state=previous,
            proposed_state=proposed,
            decision_date=decision_date,
            reasons=(reason,),
        )


def _matches(rule: PositionInvalidationRule, value: Decimal) -> bool:
    if rule.operator == "gt":
        return value > rule.threshold
    if rule.operator == "gte":
        return value >= rule.threshold
    if rule.operator == "lt":
        return value < rule.threshold
    if rule.operator == "lte":
        return value <= rule.threshold
    return value == rule.threshold


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _elapsed_trading_days(
    entry_date: str,
    decision_date: str,
    trading_dates: Iterable[str],
) -> int | None:
    """Count observed exchange sessions from entry through decision.

    The calendar is an explicit input.  If it does not cover both endpoints,
    returning ``None`` is safer than treating a weekday as a Taiwan session.
    """

    entry = _date(entry_date)
    decision = _date(decision_date)
    if decision < entry:
        return None
    normalized = sorted({_date(value) for value in trading_dates})
    if not normalized or normalized[0] > entry or normalized[-1] < decision:
        return None
    return sum(entry <= current <= decision for current in normalized)
