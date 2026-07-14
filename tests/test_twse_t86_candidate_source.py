from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from data_module.twse_t86_candidate_source import (
    T86FetchError,
    fetch_t86_envelope,
    persist_raw_envelope,
)


class Response:
    def __init__(self, status=200, body=b'{"stat":"OK","fields":[],"data":[]}', content_type="application/json"):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": content_type, "Retry-After": "0"}


def test_retry_is_bounded_and_records_rate_limit():
    responses = iter([Response(429), Response(503), Response()])
    sleeps = []
    envelope = fetch_t86_envelope(
        date(2026, 7, 10), transport=lambda **_: next(responses),
        sleep=lambda seconds: sleeps.append(seconds), now=lambda: datetime(2026, 7, 13, 8, tzinfo=UTC),
    )
    assert [item.status_code for item in envelope.attempts] == [429, 503, 200]
    assert len(sleeps) == 2
    assert envelope.request_params["date"] == "20260710"
    assert envelope.payload_sha256
    assert envelope.raw_row_count == 0


@pytest.mark.parametrize("response", [Response(body=b""), Response(body=b"<html>error</html>", content_type="text/html")])
def test_empty_and_html_fail_closed(response):
    with pytest.raises(T86FetchError):
        fetch_t86_envelope(date(2026, 7, 10), transport=lambda **_: response, sleep=lambda _: None)


def test_raw_persistence_is_content_addressed_and_never_overwrites(tmp_path: Path):
    envelope = fetch_t86_envelope(date(2026, 7, 10), transport=lambda **_: Response(), sleep=lambda _: None)
    first = persist_raw_envelope(envelope, output_root=tmp_path)
    second = persist_raw_envelope(envelope, output_root=tmp_path)
    assert first == second
    assert first.read_bytes() == envelope.payload
    assert len([path for path in (tmp_path / "raw" / "2026-07-10").glob("*.json") if not path.name.endswith(".metadata.json")]) == 1
