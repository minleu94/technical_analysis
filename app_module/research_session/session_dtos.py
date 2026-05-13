"""Immutable DTOs for research-session context."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ResearchSessionSnapshotDTO:
    """Current lightweight research workflow context.

    This snapshot is intentionally small. It should describe what the user is
    currently researching, not own market data, DataFrames, widget state, or
    computed business results.
    """

    active_symbol: Optional[str] = None
    active_regime: Optional[str] = None
    active_profile: Optional[str] = None
    selected_watchlist_id: Optional[str] = None
    current_recommendation_run_id: Optional[str] = None
