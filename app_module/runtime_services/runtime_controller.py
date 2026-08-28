"""Runtime Observatory 的唯讀輪詢協調器。"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Callable

from app_module.runtime_services.event_bus import EventBus
from app_module.runtime_services.event_stream_service import RuntimeEventStreamService
from app_module.runtime_services.health_service import RuntimeHealthService
from app_module.runtime_services.scheduled_operations_service import (
    ScheduledOperationsStatusService,
)
from app_module.runtime_services.snapshot_service import RuntimeSnapshotService
from app_module.runtime_services.environment_readiness_service import (
    EnvironmentReadinessService,
)
from app_module.dtos.runtime_dtos import EnvironmentReadinessSnapshotDTO
from runtime.interfaces.store_interface import RuntimeEventCursor
from runtime.store.local_file_store import LocalFileStore


class RuntimeController:
    """只讀發布治理 Runtime 與日常排程兩條獨立觀測流。"""

    def __init__(
        self,
        base_dir: str,
        *,
        scheduled_output_root: str | Path | None = None,
        environment_readiness_service: EnvironmentReadinessService | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.store = LocalFileStore(base_dir)
        self.event_bus = EventBus()
        self.snapshot_service = RuntimeSnapshotService(self.store)
        self.health_service = RuntimeHealthService(self.store)
        self.event_stream_service = RuntimeEventStreamService(self.store)
        self.scheduled_operations_service = (
            ScheduledOperationsStatusService(Path(scheduled_output_root))
            if scheduled_output_root is not None
            else None
        )
        self.environment_readiness_service = environment_readiness_service
        self._event_cursor = RuntimeEventCursor(-1)
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._last_scheduled_poll_at: float | None = None
        self._scheduled_poll_interval_seconds = 30.0
        self._last_environment_poll_at: float | None = None
        self._environment_poll_interval_seconds = 30.0
        self.runtime_event_diagnostics: list[str] = []

    def poll_updates(self) -> None:
        """由 Qt timer 觸發；不寫入 Runtime、排程、DB 或任何資料來源。"""
        self.event_bus.publish_state(self.snapshot_service.get_snapshot())
        self.event_bus.publish_health(self.health_service.get_health_snapshot())
        self._publish_new_runtime_events()
        self._publish_scheduled_operations_if_due()
        self._publish_environment_readiness_if_due()

    def _publish_new_runtime_events(self) -> None:
        update = self.event_stream_service.read_new_events(self._event_cursor, limit=50)
        if update.cursor_reset:
            self._record_diagnostic("runtime_event_cursor_reset")
        if update.invalid_line_count:
            self._record_diagnostic(
                f"runtime_event_invalid_lines:{update.invalid_line_count}"
            )
        if update.read_state == "unavailable":
            self._record_diagnostic(
                update.diagnostic or "runtime_event_read_unavailable"
            )

        for event in update.events:
            self.event_bus.publish_event(event)
        self._event_cursor = update.next_cursor

    def _publish_scheduled_operations_if_due(self) -> None:
        if self.scheduled_operations_service is None:
            return
        current_time = self._monotonic_clock()
        if (
            self._last_scheduled_poll_at is not None
            and current_time - self._last_scheduled_poll_at < self._scheduled_poll_interval_seconds
        ):
            return
        self._last_scheduled_poll_at = current_time
        try:
            snapshot = self.scheduled_operations_service.get_snapshot()
        except Exception as exc:  # UI observability must not halt the owner App.
            diagnostic = f"scheduled_operations_read_failed:{type(exc).__name__}"
            self._record_diagnostic(diagnostic)
            snapshot = self.scheduled_operations_service.build_unavailable_snapshot(diagnostic)
        self.event_bus.publish_scheduled_operations(snapshot)

    def _publish_environment_readiness_if_due(self) -> None:
        service = self.environment_readiness_service
        if service is None:
            return
        current_time = self._monotonic_clock()
        if (
            self._last_environment_poll_at is not None
            and current_time - self._last_environment_poll_at < self._environment_poll_interval_seconds
        ):
            return
        self._last_environment_poll_at = current_time
        try:
            snapshot = service.get_snapshot()
        except Exception as exc:  # UI observability must not halt the owner App.
            diagnostic = f"environment_readiness_read_failed:{type(exc).__name__}"
            self._record_diagnostic(diagnostic)
            snapshot = _unavailable_environment_snapshot(service, diagnostic)
        self.event_bus.publish_environment_readiness(snapshot)

    def _record_diagnostic(self, value: str) -> None:
        self.runtime_event_diagnostics.append(value)
        if len(self.runtime_event_diagnostics) > 100:
            del self.runtime_event_diagnostics[:-100]


def _unavailable_environment_snapshot(
    service: EnvironmentReadinessService,
    diagnostic: str,
) -> EnvironmentReadinessSnapshotDTO:
    """讀取 service 例外時仍發布可見的 fail-closed 投影。"""
    from datetime import datetime, timezone

    data_root = _path_from_service(service, "_data_root")
    output_root = _path_from_service(service, "_output_root")

    return EnvironmentReadinessSnapshotDTO(
        overall_state="unavailable",
        observed_at=datetime.now(timezone.utc),
        data_root=str(data_root),
        output_root=str(output_root),
        log_root=str(data_root / "logs"),
        research_registry=str(output_root / "research_runs" / "research_runs.db"),
        paths=(),
        diagnostics=(diagnostic,),
    )


def _path_from_service(service: EnvironmentReadinessService, attr_name: str) -> Path:
    value = getattr(service, attr_name, Path())
    return value if isinstance(value, Path) else Path(str(value))
