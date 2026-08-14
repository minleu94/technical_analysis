import json

from app_module.runtime_services.runtime_controller import RuntimeController
from app_module.runtime_services.event_stream_service import RuntimeEventStreamUpdate
from app_module.runtime_services.scheduled_operations_service import (
    ScheduledOperationsStatusService,
)
from runtime.interfaces.store_interface import RuntimeEventCursor, RuntimeEventReadBatch
from runtime.store.local_file_store import LocalFileStore


def test_absent_event_file_preserves_tail_attach_sentinel(tmp_path):
    batch = LocalFileStore(str(tmp_path / "runtime")).read_events_after(
        RuntimeEventCursor(-1)
    )

    assert batch.events == ()
    assert batch.next_cursor == RuntimeEventCursor(-1)


def test_incremental_reader_skips_incomplete_line_and_retries_it_after_append(tmp_path):
    store = LocalFileStore(str(tmp_path / "runtime"))
    events_path = tmp_path / "runtime" / "events" / "runtime_events.jsonl"
    events_path.parent.mkdir(parents=True)
    events_path.write_bytes(
        b'{"event_id":"one"}\n'
        b'not-json\n'
        b'{"event_id":"two"}\n'
        b'{"event_id":"three"'
    )

    first = store.read_events_after(RuntimeEventCursor(0))

    assert [event["event_id"] for event in first.events] == ["one", "two"]
    assert first.invalid_line_count == 1
    assert first.has_more is True

    with events_path.open("ab") as handle:
        handle.write(b"}\n")
    second = store.read_events_after(first.next_cursor)

    assert [event["event_id"] for event in second.events] == ["three"]
    assert second.has_more is False


def test_incremental_reader_exposes_invalid_lines_as_degraded_without_moving_past_them(
    tmp_path,
):
    store = LocalFileStore(str(tmp_path / "runtime"))
    events_path = tmp_path / "runtime" / "events" / "runtime_events.jsonl"
    events_path.parent.mkdir(parents=True)
    events_path.write_bytes(b"not-json\n{" + b'"event_id":"ok"}' + b"\n")

    result = store.read_events_after(RuntimeEventCursor(0))

    assert result.read_state == "degraded"
    assert result.diagnostic == "runtime_event_invalid_lines:1"
    assert result.invalid_line_count == 1
    assert [event["event_id"] for event in result.events] == ["ok"]


def test_incremental_reader_exposes_io_failure_and_preserves_cursor(tmp_path, monkeypatch):
    store = LocalFileStore(str(tmp_path / "runtime"))
    events_path = tmp_path / "runtime" / "events" / "runtime_events.jsonl"
    events_path.parent.mkdir(parents=True)
    events_path.write_text('{"event_id":"one"}\n', encoding="utf-8")
    cursor = RuntimeEventCursor(3)

    def _raise_os_error(_path):
        raise OSError("simulated read failure")

    monkeypatch.setattr("runtime.store.local_file_store.os.path.getsize", _raise_os_error)

    result = store.read_events_after(cursor)

    assert result.events == ()
    assert result.next_cursor == cursor
    assert result.read_state == "unavailable"
    assert result.diagnostic == "runtime_event_read_failed:OSError"


def test_controller_records_incremental_event_io_failure_without_halting_polling(
    tmp_path,
):
    controller = RuntimeController(str(tmp_path / "runtime"))
    cursor = RuntimeEventCursor(-1)
    controller.event_stream_service.read_new_events = lambda _cursor, *, limit: RuntimeEventStreamUpdate(
        events=(),
        next_cursor=cursor,
        cursor_reset=False,
        invalid_line_count=0,
        read_state="unavailable",
        diagnostic="runtime_event_read_failed:OSError",
    )

    controller.poll_updates()

    assert controller.runtime_event_diagnostics == [
        "runtime_event_read_failed:OSError"
    ]


def test_controller_attaches_at_existing_tail_then_publishes_only_new_event_without_fake_time(tmp_path):
    runtime_dir = tmp_path / "runtime"
    store = LocalFileStore(str(runtime_dir))
    store.append_event({"event_id": "historical", "timestamp": "2026-01-01T00:00:00+00:00"})
    controller = RuntimeController(str(runtime_dir))
    received = []
    controller.event_bus.subscribe_events(received.append)

    controller.poll_updates()
    store.append_event(
        {
            "event_id": "new-invalid-time",
            "timestamp": "not-a-date",
            "event_type": "validation_rejected",
        }
    )
    controller.poll_updates()

    assert [event.event_id for event in received] == ["new-invalid-time"]
    assert received[0].timestamp is None
    assert received[0].timestamp_raw == "not-a-date"


def test_tail_reader_ignores_unterminated_json_for_health_reads(tmp_path):
    store = LocalFileStore(str(tmp_path / "runtime"))
    events_path = tmp_path / "runtime" / "events" / "runtime_events.jsonl"
    events_path.parent.mkdir(parents=True)
    events_path.write_text(
        json.dumps({"event_id": "complete"}) + "\n" + '{"event_id":"partial"',
        encoding="utf-8",
    )

    result = store.read_latest_events_result()

    assert result.events == ({"event_id": "complete"},)
    assert result.read_state == "observed"


def test_controller_publishes_fail_closed_schedule_snapshot_when_status_service_raises(tmp_path):
    controller = RuntimeController(
        str(tmp_path / "runtime"),
        scheduled_output_root=tmp_path / "scheduled",
        monotonic_clock=lambda: 0,
    )
    fallback_service = ScheduledOperationsStatusService(tmp_path / "scheduled")

    class _BrokenScheduledService:
        def get_snapshot(self):
            raise OSError("unreadable")

        def build_unavailable_snapshot(self, diagnostic):
            return fallback_service.build_unavailable_snapshot(diagnostic)

    controller.scheduled_operations_service = _BrokenScheduledService()
    received = []
    controller.event_bus.subscribe_scheduled_operations(received.append)

    controller.poll_updates()

    assert len(received) == 1
    assert received[0].overall_state == "attention"
    assert received[0].core_ready_count == 0
    assert controller.runtime_event_diagnostics == [
        "scheduled_operations_read_failed:OSError"
    ]
