from pathlib import Path

import pytest

from app_module.position_health_service import PositionHealthState
from app_module.position_health_transition_repository import (
    PositionHealthTransitionRecord,
    PositionHealthTransitionRepository,
)


def test_proposal_event_does_not_change_recorded_state(tmp_path: Path) -> None:
    repository = PositionHealthTransitionRepository(tmp_path / "health.sqlite")
    record = PositionHealthTransitionRecord.proposal(
        event_id="evt-1",
        position_id="paper-main:2330",
        decision_date="2026-07-12",
        previous_state=PositionHealthState.HEALTHY,
        proposed_state=PositionHealthState.EXIT_CANDIDATE,
        reasons=("invalidation_triggered:drawdown_bp",),
    )
    repository.append(record)

    loaded = repository.list_for_position("paper-main:2330")[0]
    assert loaded.recorded_state is PositionHealthState.HEALTHY
    assert loaded.decision_kind == "proposal"
    assert loaded.auto_action_allowed is False


def test_human_approved_event_requires_reviewer_and_records_transition(tmp_path: Path) -> None:
    repository = PositionHealthTransitionRepository(tmp_path / "health.sqlite")
    record = PositionHealthTransitionRecord.human_approved(
        event_id="evt-2",
        position_id="paper-main:2330",
        decision_date="2026-07-13",
        previous_state=PositionHealthState.HEALTHY,
        approved_state=PositionHealthState.EXIT_CANDIDATE,
        reasons=("reviewed_invalidation",),
        reviewer="release-owner",
    )
    repository.append(record)

    assert repository.list_for_position("paper-main:2330")[0].recorded_state is PositionHealthState.EXIT_CANDIDATE


def test_duplicate_transition_event_cannot_overwrite(tmp_path: Path) -> None:
    repository = PositionHealthTransitionRepository(tmp_path / "health.sqlite")
    record = PositionHealthTransitionRecord.proposal(
        event_id="evt-1",
        position_id="p",
        decision_date="2026-07-12",
        previous_state=PositionHealthState.WATCH,
        proposed_state=PositionHealthState.HEALTHY,
        reasons=("metrics_recovered",),
    )
    repository.append(record)
    with pytest.raises(ValueError, match="already exists"):
        repository.append(record)


def test_human_approved_event_rejects_missing_reviewer() -> None:
    with pytest.raises(ValueError, match="reviewer"):
        PositionHealthTransitionRecord.human_approved(
            event_id="evt",
            position_id="p",
            decision_date="2026-07-12",
            previous_state=PositionHealthState.WATCH,
            approved_state=PositionHealthState.HEALTHY,
            reasons=("reviewed",),
            reviewer="",
        )
