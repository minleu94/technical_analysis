from datetime import datetime, timezone

from app_module.dtos.runtime_dtos import RuntimeState
from app_module.runtime_services.health_service import RuntimeHealthService
from runtime.interfaces.store_interface import RuntimeEventReadResult


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


class _Store:
    def __init__(self, events, *, read_state="observed", diagnostic=""):
        self._events = events
        self._read_state = read_state
        self._diagnostic = diagnostic

    def read_latest_events_result(self, _limit):
        return RuntimeEventReadResult(
            tuple(self._events),
            self._read_state,
            diagnostic=self._diagnostic,
        )


def test_historical_critical_event_is_visible_but_does_not_halt_current_runtime():
    service = RuntimeHealthService(
        _Store(
            [
                {
                    "timestamp": "2026-08-01T09:00:00+00:00",
                    "event_type": "validation_rejected",
                    "severity": "CRITICAL",
                    "payload": {"reason": "GovernanceViolation"},
                }
            ]
        ),
        now_provider=lambda: NOW,
    )

    snapshot = service.get_health_snapshot()

    assert snapshot.observation_scope == "historical_only"
    assert snapshot.current_state is RuntimeState.IDLE
    assert snapshot.is_healthy is True
    assert snapshot.historical_event_count == 1
    assert snapshot.last_critical_violation is not None


def test_current_critical_event_halts_governance_runtime_only():
    service = RuntimeHealthService(
        _Store(
            [
                {
                    "timestamp": "2026-08-06T11:59:00+00:00",
                    "event_type": "validation_rejected",
                    "severity": "CRITICAL",
                    "payload": {"reason": "SchemaViolation"},
                }
            ]
        ),
        now_provider=lambda: NOW,
    )

    snapshot = service.get_health_snapshot()

    assert snapshot.observation_scope == "current"
    assert snapshot.current_state is RuntimeState.HALTED
    assert snapshot.is_healthy is False


def test_invalid_timestamp_is_not_replaced_by_current_time_or_used_for_health():
    service = RuntimeHealthService(
        _Store(
            [
                {
                    "timestamp": "not-an-iso-date",
                    "event_type": "validation_rejected",
                    "payload": "not-an-object",
                }
            ]
        ),
        now_provider=lambda: NOW,
    )

    snapshot = service.get_health_snapshot()

    assert snapshot.observation_scope == "timestamp_invalid"
    assert snapshot.current_state is RuntimeState.IDLE
    assert snapshot.timestamp_invalid_count == 1
    assert snapshot.latest_event_at is None


def test_future_critical_event_does_not_halt_current_runtime():
    service = RuntimeHealthService(
        _Store(
            [
                {
                    "timestamp": "2026-08-07T12:00:00+00:00",
                    "event_type": "validation_rejected",
                    "severity": "CRITICAL",
                    "payload": {"reason": "GovernanceViolation"},
                }
            ]
        ),
        now_provider=lambda: NOW,
    )

    snapshot = service.get_health_snapshot()

    assert snapshot.observation_scope == "timestamp_future"
    assert snapshot.current_state is RuntimeState.IDLE
    assert snapshot.is_healthy is True
    assert snapshot.future_event_count == 1


def test_unreadable_event_log_is_not_reported_as_empty_or_healthy():
    service = RuntimeHealthService(
        _Store(
            [],
            read_state="unavailable",
            diagnostic="runtime_event_read_failed:PermissionError",
        ),
        now_provider=lambda: NOW,
    )

    snapshot = service.get_health_snapshot()

    assert snapshot.observation_scope == "event_log_unreadable"
    assert snapshot.current_state is RuntimeState.IDLE
    assert snapshot.is_healthy is False
    assert snapshot.event_log_read_state == "unavailable"
