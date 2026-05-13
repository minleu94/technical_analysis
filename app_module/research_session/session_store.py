"""In-memory research-session store."""

from typing import Callable, List, Optional

from .session_dtos import ResearchSessionSnapshotDTO
from .session_events import ResearchSessionEvent
from .session_reducer import reduce_session_event

SessionSubscriber = Callable[[ResearchSessionSnapshotDTO], None]


class ResearchSessionStore:
    """Small UI-independent store for workflow continuity.

    The store owns only current session context. It does not persist state,
    hold DataFrames, run business logic, or know about Qt widgets.
    """

    def __init__(self, initial_snapshot: Optional[ResearchSessionSnapshotDTO] = None):
        self._snapshot = initial_snapshot or ResearchSessionSnapshotDTO()
        self._subscribers: List[SessionSubscriber] = []

    def get_snapshot(self) -> ResearchSessionSnapshotDTO:
        return self._snapshot

    def dispatch(self, event: ResearchSessionEvent) -> ResearchSessionSnapshotDTO:
        next_snapshot = reduce_session_event(self._snapshot, event)
        if next_snapshot == self._snapshot:
            return self._snapshot

        self._snapshot = next_snapshot
        self._notify(next_snapshot)
        return next_snapshot

    def subscribe(self, subscriber: SessionSubscriber) -> Callable[[], None]:
        self._subscribers.append(subscriber)
        subscriber(self._snapshot)

        def unsubscribe() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return unsubscribe

    def _notify(self, snapshot: ResearchSessionSnapshotDTO) -> None:
        for subscriber in list(self._subscribers):
            subscriber(snapshot)
