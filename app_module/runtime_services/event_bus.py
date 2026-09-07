from threading import RLock
from typing import Callable, List, TypeVar
from app_module.dtos.runtime_dtos import (
    RuntimeEventDTO,
    RuntimeStateSnapshotDTO,
    RuntimeHealthSnapshotDTO,
    ScheduledOperationsSnapshotDTO,
    EnvironmentReadinessSnapshotDTO,
)

EventType = TypeVar("EventType")

class EventBus:
    """
    Pure Python Pub/Sub implementation for Runtime Subsystem.
    Decoupled from UI Frameworks. UI/Qt signals are NOT allowed here.
    """
    def __init__(self) -> None:
        self._subscription_lock = RLock()
        self._event_subscribers: List[Callable[[RuntimeEventDTO], None]] = []
        self._state_subscribers: List[Callable[[RuntimeStateSnapshotDTO], None]] = []
        self._health_subscribers: List[Callable[[RuntimeHealthSnapshotDTO], None]] = []
        self._scheduled_operations_subscribers: List[
            Callable[[ScheduledOperationsSnapshotDTO], None]
        ] = []
        self._environment_readiness_subscribers: List[
            Callable[[EnvironmentReadinessSnapshotDTO], None]
        ] = []

    def subscribe_events(self, callback: Callable[[RuntimeEventDTO], None]) -> Callable[[], None]:
        return self._subscribe(self._event_subscribers, callback)

    def subscribe_state(self, callback: Callable[[RuntimeStateSnapshotDTO], None]) -> Callable[[], None]:
        return self._subscribe(self._state_subscribers, callback)

    def subscribe_health(self, callback: Callable[[RuntimeHealthSnapshotDTO], None]) -> Callable[[], None]:
        return self._subscribe(self._health_subscribers, callback)

    def subscribe_scheduled_operations(
        self,
        callback: Callable[[ScheduledOperationsSnapshotDTO], None],
    ) -> Callable[[], None]:
        return self._subscribe(self._scheduled_operations_subscribers, callback)

    def subscribe_environment_readiness(
        self,
        callback: Callable[[EnvironmentReadinessSnapshotDTO], None],
    ) -> Callable[[], None]:
        return self._subscribe(self._environment_readiness_subscribers, callback)

    def _subscribe(
        self, subscribers: List[Callable[[EventType], None]], callback: Callable[[EventType], None]
    ) -> Callable[[], None]:
        # 每次訂閱使用獨立 wrapper，重複訂閱的取消句柄不互相影響。
        def subscription(value: EventType) -> None:
            callback(value)

        with self._subscription_lock:
            subscribers.append(subscription)

        def unsubscribe() -> None:
            with self._subscription_lock:
                if subscription in subscribers:
                    subscribers.remove(subscription)

        return unsubscribe

    def _publish(self, subscribers: List[Callable[[EventType], None]], value: EventType) -> None:
        with self._subscription_lock:
            current_subscribers = tuple(subscribers)
        # 回呼可取消訂閱；該次已取得的通知快照仍按原順序完成。
        for subscriber in current_subscribers:
            subscriber(value)

    def publish_event(self, event_dto: RuntimeEventDTO) -> None:
        self._publish(self._event_subscribers, event_dto)

    def publish_state(self, state_dto: RuntimeStateSnapshotDTO) -> None:
        self._publish(self._state_subscribers, state_dto)

    def publish_health(self, health_dto: RuntimeHealthSnapshotDTO) -> None:
        self._publish(self._health_subscribers, health_dto)

    def publish_scheduled_operations(
        self,
        scheduled_operations_dto: ScheduledOperationsSnapshotDTO,
    ) -> None:
        self._publish(self._scheduled_operations_subscribers, scheduled_operations_dto)

    def publish_environment_readiness(
        self,
        environment_readiness_dto: EnvironmentReadinessSnapshotDTO,
    ) -> None:
        self._publish(self._environment_readiness_subscribers, environment_readiness_dto)
