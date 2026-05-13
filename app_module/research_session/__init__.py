"""
Thin research-session state layer.

This package owns short-lived workflow context only. It intentionally avoids
Qt, pandas, persistence, and domain computation.
"""

from .session_dtos import ResearchSessionSnapshotDTO
from .session_events import (
    ActiveProfileChanged,
    ActiveRegimeChanged,
    ActiveSymbolChanged,
    CurrentRecommendationRunChanged,
    ResearchSessionEvent,
    SelectedWatchlistChanged,
)
from .session_store import ResearchSessionStore

__all__ = [
    "ActiveProfileChanged",
    "ActiveRegimeChanged",
    "ActiveSymbolChanged",
    "CurrentRecommendationRunChanged",
    "ResearchSessionEvent",
    "ResearchSessionSnapshotDTO",
    "ResearchSessionStore",
    "SelectedWatchlistChanged",
]
