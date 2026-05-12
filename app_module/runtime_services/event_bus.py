from typing import Callable, List
from app_module.dtos.runtime_dtos import RuntimeEventDTO, RuntimeStateSnapshotDTO, RuntimeHealthSnapshotDTO

class EventBus:
    """
    Pure Python Pub/Sub implementation for Runtime Subsystem.
    Decoupled from UI Frameworks. UI/Qt signals are NOT allowed here.
    """
    def __init__(self):
        self._event_subscribers: List[Callable[[RuntimeEventDTO], None]] = []
        self._state_subscribers: List[Callable[[RuntimeStateSnapshotDTO], None]] = []
        self._health_subscribers: List[Callable[[RuntimeHealthSnapshotDTO], None]] = []

    def subscribe_events(self, callback: Callable[[RuntimeEventDTO], None]) -> None:
        self._event_subscribers.append(callback)

    def subscribe_state(self, callback: Callable[[RuntimeStateSnapshotDTO], None]) -> None:
        self._state_subscribers.append(callback)

    def subscribe_health(self, callback: Callable[[RuntimeHealthSnapshotDTO], None]) -> None:
        self._health_subscribers.append(callback)

    def publish_event(self, event_dto: RuntimeEventDTO) -> None:
        for sub in self._event_subscribers:
            sub(event_dto)

    def publish_state(self, state_dto: RuntimeStateSnapshotDTO) -> None:
        for sub in self._state_subscribers:
            sub(state_dto)

    def publish_health(self, health_dto: RuntimeHealthSnapshotDTO) -> None:
        for sub in self._health_subscribers:
            sub(health_dto)
