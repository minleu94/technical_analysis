"""Event contracts for the thin research-session store."""

from dataclasses import dataclass
from typing import Optional, Union


@dataclass(frozen=True)
class ActiveSymbolChanged:
    symbol: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class ActiveRegimeChanged:
    regime: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class ActiveProfileChanged:
    profile: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class SelectedWatchlistChanged:
    watchlist_id: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class CurrentRecommendationRunChanged:
    run_id: Optional[str]
    source: str = "unknown"


ResearchSessionEvent = Union[
    ActiveSymbolChanged,
    ActiveRegimeChanged,
    ActiveProfileChanged,
    SelectedWatchlistChanged,
    CurrentRecommendationRunChanged,
]
