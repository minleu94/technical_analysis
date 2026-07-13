from app_module.portfolio_condition_monitor import PortfolioConditionResult
from app_module.strategy_lifecycle_service import GateStatus


def _condition(*, status: str, reasons: list[str] | None = None) -> PortfolioConditionResult:
    return PortfolioConditionResult(
        stock_code="2330",
        status=status,
        label=status,
        source_label="recommendation",
        reasons=reasons or [],
    )


def test_position_health_maps_valid_condition_to_healthy() -> None:
    from app_module.position_health_service import PositionHealthService, PositionHealthState

    result = PositionHealthService().evaluate(
        stock_code="2330",
        condition_result=_condition(status="valid", reasons=["regime_unchanged"]),
        feedback_status=GateStatus.PASS,
        source_trace=("rec-001",),
    )

    assert result.state is PositionHealthState.HEALTHY
    assert result.auto_action_allowed is False
    assert result.source_trace == ("rec-001",)


def test_position_health_maps_invalid_condition_to_exit_candidate_without_auto_exit() -> None:
    from app_module.position_health_service import PositionHealthService, PositionHealthState

    result = PositionHealthService().evaluate(
        stock_code="2330",
        condition_result=_condition(status="invalid", reasons=["thesis_invalid"]),
        feedback_status=GateStatus.FAIL,
        source_trace=("rec-001",),
    )

    assert result.state is PositionHealthState.EXIT_CANDIDATE
    assert result.reasons == ("thesis_invalid", "feedback_failed")
    assert result.auto_action_allowed is False


def test_position_health_fails_closed_to_watch_when_condition_or_trace_is_missing() -> None:
    from app_module.position_health_service import PositionHealthService, PositionHealthState

    result = PositionHealthService().evaluate(
        stock_code="2330",
        condition_result=None,
        feedback_status=None,
        source_trace=(),
    )

    assert result.state is PositionHealthState.WATCH
    assert result.reasons == ("condition_result_missing", "source_trace_missing")

