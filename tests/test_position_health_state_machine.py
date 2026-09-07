from decimal import Decimal

from app_module.position_health_service import PositionHealthState
from app_module.position_health_state_machine import (
    PositionHealthMetric,
    PositionHealthStateMachine,
)
from app_module.position_thesis_contract import PositionInvalidationRule, PositionThesisContract


def _thesis() -> PositionThesisContract:
    return PositionThesisContract(
        position_id="paper-main:2330",
        stock_code="2330",
        entry_date="2026-07-01",
        decision_date="2026-07-01",
        available_date="2026-07-01",
        entry_thesis="stable regime",
        holding_horizon_trading_days=20,
        next_review_date="2026-07-17",
        source_trace=("rec-1",),
        invalidation_rules=(PositionInvalidationRule("drawdown_bp", "gte", Decimal("800")),),
    )


def test_triggered_invalidation_proposes_exit_candidate_without_auto_action() -> None:
    result = PositionHealthStateMachine().evaluate(
        current_state=PositionHealthState.HEALTHY,
        thesis=_thesis(),
        decision_date="2026-07-12",
        metrics=(PositionHealthMetric("drawdown_bp", Decimal("900"), "2026-07-12"),),
    )

    assert result.proposed_state is PositionHealthState.EXIT_CANDIDATE
    assert "invalidation_triggered:drawdown_bp" in result.reasons
    assert result.apply_transition is False
    assert result.auto_exit_allowed is False


def test_future_metric_is_blocked_and_proposes_watch() -> None:
    result = PositionHealthStateMachine().evaluate(
        current_state=PositionHealthState.HEALTHY,
        thesis=_thesis(),
        decision_date="2026-07-12",
        metrics=(PositionHealthMetric("drawdown_bp", Decimal("900"), "2026-07-13"),),
    )

    assert result.proposed_state is PositionHealthState.WATCH
    assert "future_metric_blocked:drawdown_bp" in result.reasons


def test_missing_required_metric_proposes_watch() -> None:
    result = PositionHealthStateMachine().evaluate(
        current_state=PositionHealthState.HEALTHY,
        thesis=_thesis(),
        decision_date="2026-07-12",
        metrics=(),
    )

    assert result.proposed_state is PositionHealthState.WATCH
    assert "missing_metric:drawdown_bp" in result.reasons


def test_closed_state_is_terminal() -> None:
    result = PositionHealthStateMachine().evaluate(
        current_state=PositionHealthState.CLOSED,
        thesis=_thesis(),
        decision_date="2026-07-12",
        metrics=(PositionHealthMetric("drawdown_bp", Decimal("0"), "2026-07-12"),),
    )

    assert result.proposed_state is PositionHealthState.CLOSED
    assert "closed_state_is_terminal" in result.reasons


def test_reduce_invalidation_is_distinct_from_hard_exit() -> None:
    thesis = PositionThesisContract(
        **{
            **_thesis().__dict__,
            "holding_horizon_trading_days": 4,
            "invalidation_rules": (
                PositionInvalidationRule(
                    "relative_strength_bp",
                    "lt",
                    Decimal("-300"),
                    action="reduce",
                ),
            ),
        }
    )
    result = PositionHealthStateMachine().evaluate(
        current_state=PositionHealthState.HEALTHY,
        thesis=thesis,
        decision_date="2026-07-12",
        metrics=(PositionHealthMetric("relative_strength_bp", Decimal("-400"), "2026-07-12"),),
    )

    assert result.proposed_state is PositionHealthState.REDUCE_CANDIDATE
    assert "invalidation_triggered:relative_strength_bp" in result.reasons
    assert result.auto_exit_allowed is False


def test_holding_horizon_uses_explicit_calendar_and_proposes_reduce() -> None:
    thesis = PositionThesisContract(
        **{**_thesis().__dict__, "holding_horizon_trading_days": 4}
    )
    result = PositionHealthStateMachine().evaluate(
        current_state=PositionHealthState.HEALTHY,
        thesis=thesis,
        decision_date="2026-07-06",
        metrics=(PositionHealthMetric("drawdown_bp", Decimal("0"), "2026-07-06"),),
        trading_dates=(
            "2026-07-01",
            "2026-07-02",
            "2026-07-03",
            "2026-07-06",
        ),
    )

    assert result.proposed_state is PositionHealthState.REDUCE_CANDIDATE
    assert "holding_horizon_reached:4/4" in result.reasons
    assert "time_stop_calendar_incomplete" not in result.reasons


def test_holding_horizon_does_not_guess_missing_exchange_sessions() -> None:
    result = PositionHealthStateMachine().evaluate(
        current_state=PositionHealthState.HEALTHY,
        thesis=_thesis(),
        decision_date="2026-07-06",
        metrics=(PositionHealthMetric("drawdown_bp", Decimal("0"), "2026-07-06"),),
        trading_dates=("2026-07-02", "2026-07-03", "2026-07-06"),
    )

    assert result.proposed_state is PositionHealthState.HEALTHY
    assert "time_stop_calendar_incomplete" in result.reasons
