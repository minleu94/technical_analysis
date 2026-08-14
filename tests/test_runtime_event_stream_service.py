from app_module.runtime_services.event_stream_service import RuntimeEventStreamService
from runtime.interfaces.store_interface import (
    RuntimeEventCursor,
    RuntimeEventReadBatch,
)


class _Store:
    def read_events_after(self, cursor, *, limit):
        assert cursor == RuntimeEventCursor(4)
        assert limit == 50
        return RuntimeEventReadBatch(
            events=(
                {
                    "event_id": "event-1",
                    "timestamp": "not-a-date",
                    "severity": "not-a-severity",
                    "payload": ["untrusted"],
                },
            ),
            next_cursor=RuntimeEventCursor(50),
            has_more=False,
            invalid_line_count=2,
        )


def test_stream_service_translates_untrusted_jsonl_payload_without_inventing_time():
    update = RuntimeEventStreamService(_Store()).read_new_events(RuntimeEventCursor(4))

    assert update.next_cursor == RuntimeEventCursor(50)
    assert update.invalid_line_count == 2
    assert update.events[0].timestamp is None
    assert update.events[0].timestamp_raw == "not-a-date"
    assert update.events[0].severity.value == "INFO"
    assert update.events[0].payload_preview == {"raw_payload": ["untrusted"]}
