"""Append-only Runtime 事件流的 application service。"""

from __future__ import annotations

from dataclasses import dataclass

from app_module.dtos.runtime_dtos import GovernanceSeverity, RuntimeEventDTO
from app_module.runtime_services.event_time import parse_runtime_event_timestamp
from runtime.interfaces.store_interface import IRuntimeStore, RuntimeEventCursor


@dataclass(frozen=True)
class RuntimeEventStreamUpdate:
    """一批可安全交給 UI 的新事件與 cursor 結果。"""

    events: tuple[RuntimeEventDTO, ...]
    next_cursor: RuntimeEventCursor
    cursor_reset: bool
    invalid_line_count: int
    read_state: str = "observed"
    diagnostic: str = ""


class RuntimeEventStreamService:
    """唯一將 Runtime JSONL 增量記錄轉為 Runtime DTO 的 service。"""

    def __init__(self, store: IRuntimeStore) -> None:
        self._store = store

    def read_new_events(
        self,
        cursor: RuntimeEventCursor,
        *,
        limit: int = 50,
    ) -> RuntimeEventStreamUpdate:
        batch = self._store.read_events_after(cursor, limit=limit)
        return RuntimeEventStreamUpdate(
            events=tuple(_to_runtime_event_dto(payload) for payload in batch.events),
            next_cursor=batch.next_cursor,
            cursor_reset=batch.cursor_reset,
            invalid_line_count=batch.invalid_line_count,
            read_state=batch.read_state,
            diagnostic=batch.diagnostic,
        )


def _to_runtime_event_dto(payload: dict[str, object]) -> RuntimeEventDTO:
    raw_timestamp = payload.get("timestamp")
    timestamp_raw = str(raw_timestamp) if raw_timestamp is not None else None
    timestamp = parse_runtime_event_timestamp(raw_timestamp)
    severity_text = str(payload.get("severity", "INFO")).upper()
    try:
        severity = GovernanceSeverity[severity_text]
    except KeyError:
        severity = GovernanceSeverity.INFO

    raw_payload = payload.get("payload", {})
    payload_preview = (
        raw_payload if isinstance(raw_payload, dict) else {"raw_payload": raw_payload}
    )
    message = str(payload_preview.get("reason", payload.get("event_type", "")))
    return RuntimeEventDTO(
        event_id=str(payload.get("event_id", "")),
        timestamp=timestamp,
        actor=str(payload.get("actor", "system")),
        event_type=str(payload.get("event_type", "")),
        severity=severity,
        human_readable_message=message,
        payload_preview=payload_preview,
        timestamp_raw=timestamp_raw,
    )
