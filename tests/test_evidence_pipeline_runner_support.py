from app_module.evidence_pipeline_runner_dtos import (
    STEP_DEGRADED,
    STEP_FAILED,
    STEP_READY,
    STEP_READY_WITH_ADVISORIES,
)
from app_module.evidence_pipeline_runner_support import derive_overall_status


def test_derive_overall_status_prioritizes_failed_over_every_other_condition() -> None:
    assert derive_overall_status(
        (STEP_READY, STEP_DEGRADED, STEP_READY_WITH_ADVISORIES, STEP_FAILED),
        ("missing_source",),
    ) == STEP_FAILED


def test_derive_overall_status_returns_degraded_for_blocking_gap_or_degraded_step() -> None:
    assert derive_overall_status((STEP_READY,), ("missing_source",)) == STEP_DEGRADED
    assert derive_overall_status((STEP_READY, STEP_DEGRADED), ()) == STEP_DEGRADED


def test_derive_overall_status_preserves_ready_with_advisories_without_higher_condition() -> None:
    assert derive_overall_status((STEP_READY, STEP_READY_WITH_ADVISORIES), ()) == STEP_READY_WITH_ADVISORIES


def test_derive_overall_status_returns_ready_for_ready_or_empty_statuses() -> None:
    assert derive_overall_status((STEP_READY,), ()) == STEP_READY
    assert derive_overall_status((), ()) == STEP_READY
