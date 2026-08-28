from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

import scripts.capture_p0_license_evidence as capture


class _FakeHeaders:
    def __init__(self) -> None:
        self._values = {
            "Date": "Fri, 28 Aug 2026 16:00:00 GMT",
            "Last-Modified": "Fri, 28 Aug 2026 15:00:00 GMT",
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": "89",
        }

    def get(self, name: str) -> str | None:
        return self._values.get(name)


class _FakeResponse:
    status = 200
    headers = _FakeHeaders()

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def geturl(self) -> str:
        return "https://www.twse.com.tw/zh/terms/use.html"


def test_preview_is_no_network_and_does_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("preview must not open a URL")

    monkeypatch.setattr(capture, "urlopen", fail_if_called)
    output = tmp_path / "preview.json"
    payload = capture.capture_p0_license_evidence(
        date(2026, 8, 28), output_path=output
    )

    assert payload["capture_mode"] == "preview_no_network"
    assert payload["capture_executed"] is False
    assert payload["license_accepted"] is False
    assert payload["summary"]["target_count"] == 3
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["candidate_only"] is True


def test_output_path_must_be_temp(tmp_path: Path) -> None:
    outside = capture.PROJECT_ROOT / "outside-license-evidence.json"
    with pytest.raises(ValueError, match="TEMP"):
        capture.capture_p0_license_evidence(
            date(2026, 8, 28), output_path=outside
        )


def test_route_registry_url_allowlist_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = capture.build_p0_acquisition_route_registry

    class _BadRoute:
        license_evidence_url = "https://example.invalid/terms"
        route_id = "bad.route"

    class _BadRegistry:
        def for_source(self, source_id: str) -> tuple[_BadRoute, ...]:
            return (_BadRoute(),)

    monkeypatch.setattr(capture, "build_p0_acquisition_route_registry", lambda: _BadRegistry())
    with pytest.raises(ValueError, match="not allowlisted"):
        capture.build_preview_payload(date(2026, 8, 28))
    monkeypatch.setattr(capture, "build_p0_acquisition_route_registry", original)


def test_confirmed_capture_is_bounded_and_does_not_persist_page_text(tmp_path: Path) -> None:
    calls: list[tuple[str, float]] = []
    body = (
        "自動下載需同意；政府資料開放；來源引用完整性；".encode("utf-8")
        + b"x" * 128
    )

    def opener(request: object, *, timeout: float) -> _FakeResponse:
        calls.append((getattr(request, "full_url", ""), timeout))
        return _FakeResponse(body)

    output = Path(__import__("tempfile").gettempdir()) / "technical_analysis_p0_license_evidence" / "test_capture.json"
    payload = capture.capture_p0_license_evidence(
        date(2026, 8, 28),
        confirmed=True,
        timeout_seconds=7,
        max_bytes=64,
        opener=opener,
        output_path=output,
    )

    assert len(calls) == 3
    assert all(timeout == 7 for _, timeout in calls)
    assert payload["capture_mode"] == "confirmed_bounded_live_readonly"
    assert payload["summary"]["captured_count"] == 3
    assert payload["production_ingestion_allowed"] is False
    assert payload["source_acceptance_granted"] is False
    assert all(item["content_persisted"] is False for item in payload["targets"])
    assert all(item["bytes_captured"] == 64 for item in payload["targets"])
    assert all(item["truncated"] is True for item in payload["targets"])
    flags = payload["targets"][0]["keyword_flags"]
    assert flags["automated_access_or_crawler"]["matched"] is True
    assert flags["open_data_or_government_exception"]["matched"] is True
    assert flags["source_attribution_or_integrity"]["matched"] is True
    assert output.exists()


def test_failed_http_target_is_retained_without_aborting(tmp_path: Path) -> None:
    from urllib.error import HTTPError

    def opener(request: object, *, timeout: float) -> object:
        raise HTTPError(
            getattr(request, "full_url", "https://example.invalid"),
            403,
            "forbidden",
            hdrs=None,
            fp=None,
        )

    output = Path(__import__("tempfile").gettempdir()) / "technical_analysis_p0_license_evidence" / "test_http_error.json"
    payload = capture.capture_p0_license_evidence(
        date(2026, 8, 28), confirmed=True, opener=opener, output_path=output
    )

    assert payload["summary"]["captured_count"] == 0
    assert payload["summary"]["failed_count"] == 3
    assert all(item["status"] == "http_error" for item in payload["targets"])
    assert all(item["http_status"] == 403 for item in payload["targets"])
