from __future__ import annotations

from collections.abc import Iterable

from app_module.evidence_pipeline_runner_dtos import (
    STEP_DEGRADED,
    STEP_FAILED,
    STEP_READY,
    STEP_READY_WITH_ADVISORIES,
)


def derive_overall_status(step_statuses: Iterable[str], blocking_gaps: Iterable[str]) -> str:
    """依既有優先序推導 Evidence Pipeline 的整體狀態。"""
    statuses = tuple(step_statuses)
    if STEP_FAILED in statuses:
        return STEP_FAILED
    if tuple(blocking_gaps) or STEP_DEGRADED in statuses:
        return STEP_DEGRADED
    if STEP_READY_WITH_ADVISORIES in statuses:
        return STEP_READY_WITH_ADVISORIES
    return STEP_READY
