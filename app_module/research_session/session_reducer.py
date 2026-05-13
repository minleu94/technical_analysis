"""Pure reducer for research-session events."""

from dataclasses import replace

from .session_dtos import ResearchSessionSnapshotDTO
from .session_events import (
    ActiveProfileChanged,
    ActiveRegimeChanged,
    ActiveSymbolChanged,
    CurrentRecommendationRunChanged,
    ResearchSessionEvent,
    SelectedWatchlistChanged,
)


def reduce_session_event(
    snapshot: ResearchSessionSnapshotDTO,
    event: ResearchSessionEvent,
) -> ResearchSessionSnapshotDTO:
    """Return a new snapshot for a session event."""

    if isinstance(event, ActiveSymbolChanged):
        return replace(snapshot, active_symbol=_normalize(event.symbol))
    if isinstance(event, ActiveRegimeChanged):
        return replace(snapshot, active_regime=_normalize(event.regime))
    if isinstance(event, ActiveProfileChanged):
        return replace(snapshot, active_profile=_normalize(event.profile))
    if isinstance(event, SelectedWatchlistChanged):
        return replace(snapshot, selected_watchlist_id=_normalize(event.watchlist_id))
    if isinstance(event, CurrentRecommendationRunChanged):
        return replace(snapshot, current_recommendation_run_id=_normalize(event.run_id))

    return snapshot


def _normalize(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None
