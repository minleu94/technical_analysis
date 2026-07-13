"""V2.5 持倉健康狀態的唯讀投影。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from app_module.portfolio_condition_monitor import PortfolioConditionResult
from app_module.strategy_lifecycle_service import GateStatus


class PositionHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    REDUCE_CANDIDATE = "REDUCE_CANDIDATE"
    EXIT_CANDIDATE = "EXIT_CANDIDATE"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class PositionHealthResult:
    stock_code: str
    state: PositionHealthState
    reasons: tuple[str, ...]
    source_trace: tuple[str, ...]
    auto_action_allowed: bool = False


class PositionHealthService:
    """將既有持倉 condition 與 feedback 轉為不可執行的狀態標籤。"""

    def evaluate(
        self,
        *,
        stock_code: str,
        condition_result: PortfolioConditionResult | None,
        feedback_status: GateStatus | None,
        source_trace: Sequence[str],
    ) -> PositionHealthResult:
        if not stock_code:
            raise ValueError("stock_code is required")
        trace = tuple(source_trace)
        if not all(isinstance(item, str) and item for item in trace):
            raise ValueError("source_trace must contain non-empty strings")

        reasons: list[str] = []
        if condition_result is None:
            reasons.append("condition_result_missing")
        else:
            reasons.extend(condition_result.reasons)
        if feedback_status is GateStatus.FAIL:
            reasons.append("feedback_failed")
        elif feedback_status is GateStatus.DEGRADED:
            reasons.append("feedback_degraded")
        if not trace:
            reasons.append("source_trace_missing")

        state = self._state(condition_result, feedback_status, has_trace=bool(trace))
        return PositionHealthResult(
            stock_code=stock_code,
            state=state,
            reasons=tuple(dict.fromkeys(reasons)),
            source_trace=trace,
        )

    @staticmethod
    def _state(
        condition_result: PortfolioConditionResult | None,
        feedback_status: GateStatus | None,
        *,
        has_trace: bool,
    ) -> PositionHealthState:
        if condition_result is None or not has_trace:
            return PositionHealthState.WATCH
        if condition_result.status == "invalid" or feedback_status is GateStatus.FAIL:
            return PositionHealthState.EXIT_CANDIDATE
        if condition_result.status == "warning" or feedback_status is GateStatus.DEGRADED:
            return PositionHealthState.WATCH
        return PositionHealthState.HEALTHY
