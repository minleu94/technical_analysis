from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_module.official_calendar_bundle import (
    OfficialCalendarBundleError,
    build_official_calendar_bundle,
    fetch_network_responses,
    hash_response_bytes,
    load_fixture_response,
    write_candidate_bundle,
    write_raw_response_evidence,
)
from scripts.capture_official_calendar_bundle import main


def _twse_payload() -> list[dict[str, str]]:
    return [
        {
            "Name": "中秋節",
            "Date": "1150925",
            "Description": "依規定放假一日。",
        },
        {
            "Name": "國慶日前最後交易日",
            "Date": "1151009",
            "Description": "最後交易。",
        },
    ]


def _tpex_payload() -> dict[str, object]:
    return {
        "calendar": {
            "total": 2,
            "data": {
                "20260901": {"holiday": False, "holidayList": []},
                "20260902": {"holiday": False, "holidayList": []},
            },
            "status": "success",
        },
    }


def _responses() -> tuple[dict[int, object], dict[str, object]]:
    from data_module.official_calendar_bundle import CapturedCalendarResponse

    return (
        {
            2026: CapturedCalendarResponse(
                kind="twse",
                key="2026",
                source="https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule?queryYear=115",
                source_hash="sha256:" + "1" * 64,
                payload=_twse_payload(),
            )
        },
        {
            "202609": CapturedCalendarResponse(
                kind="tpex",
                key="202609",
                source="https://info.tpex.org.tw/api/mktCalendar?ym=202609&lang=zh-tw",
                source_hash="sha256:" + "2" * 64,
                payload=_tpex_payload(),
            )
        },
    )


def test_build_bundle_normalizes_common_days_and_holiday() -> None:
    twse, tpex = _responses()
    bundle = build_official_calendar_bundle(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        twse_responses=twse,  # type: ignore[arg-type]
        tpex_responses=tpex,  # type: ignore[arg-type]
        captured_at=datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc),
    )

    assert bundle["schema_version"] == "official-trading-calendar-bundle.v1"
    assert bundle["candidate_only"] is True
    assert bundle["formal_clock_created"] is False
    assert bundle["network_enabled"] is False
    assert bundle["range"] == {
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
        "day_count": 2,
    }
    days = bundle["days"]
    assert isinstance(days, list)
    assert all(day["twse"]["is_trading_day"] is True for day in days)
    assert all(day["tpex"]["is_trading_day"] is True for day in days)


def test_build_bundle_refuses_missing_weekday_tpex_row() -> None:
    twse, tpex = _responses()
    payload = dict(tpex["202609"].payload)  # type: ignore[union-attr]
    calendar = dict(payload["calendar"])  # type: ignore[index]
    calendar["data"] = {"20260901": {"holiday": False, "holidayList": []}}
    payload["calendar"] = calendar
    from data_module.official_calendar_bundle import CapturedCalendarResponse

    tpex["202609"] = CapturedCalendarResponse(
        kind="tpex",
        key="202609",
        source="tpex",
        source_hash="sha256:" + "2" * 64,
        payload=payload,
    )

    with pytest.raises(OfficialCalendarBundleError, match="no explicit weekday row"):
        build_official_calendar_bundle(
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 2),
            twse_responses=twse,  # type: ignore[arg-type]
            tpex_responses=tpex,  # type: ignore[arg-type]
        )


def test_fixture_loader_uses_raw_file_hash_and_official_source(tmp_path: Path) -> None:
    path = tmp_path / "twse-115.json"
    raw = json.dumps(_twse_payload(), ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)

    response = load_fixture_response(path, kind="twse")

    assert response.key == "2026"
    assert response.source.startswith(
        "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule?queryYear=115"
    )
    assert response.source_hash.startswith("sha256:")
    assert response.raw_bytes == raw
    assert response.source_hash == hash_response_bytes(raw)


def test_network_fetch_is_bounded_and_hashes_response() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def request(url: str, *, params: dict[str, str], **_: object) -> SimpleNamespace:
        calls.append((url, params))
        if "twse" in url:
            return SimpleNamespace(json=lambda: _twse_payload(), content=b"twse-raw")
        return SimpleNamespace(json=lambda: _tpex_payload(), content=b"tpex-raw")

    twse, tpex = fetch_network_responses(
        years={2026}, months={"202609"}, request_fn=request
    )

    assert len(calls) == 2
    assert calls[0][1] == {"queryYear": "115"}
    assert calls[1][1] == {"ym": "202609", "lang": "zh-tw"}
    assert twse[2026].source_hash == "sha256:" + hashlib.sha256(b"twse-raw").hexdigest()
    assert tpex["202609"].source_hash == "sha256:" + hashlib.sha256(b"tpex-raw").hexdigest()
    assert twse[2026].raw_bytes == b"twse-raw"
    assert tpex["202609"].raw_bytes == b"tpex-raw"
    assert twse[2026].metadata["request_params"] == {"queryYear": "115"}  # type: ignore[index]
    assert tpex["202609"].metadata["request_params"] == {  # type: ignore[index]
        "ym": "202609",
        "lang": "zh-tw",
    }


def test_cli_fixture_capture_is_create_only_and_candidate_only(tmp_path: Path) -> None:
    twse_path = tmp_path / "twse.json"
    tpex_path = tmp_path / "tpex.json"
    twse_path.write_text(json.dumps(_twse_payload(), ensure_ascii=False), encoding="utf-8")
    tpex_path.write_text(json.dumps(_tpex_payload(), ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "calendar-bundle.json"

    code = main(
        [
            "--start-date",
            "2026-09-01",
            "--end-date",
            "2026-09-02",
            "--twse-fixture",
            str(twse_path),
            "--tpex-fixture",
            str(tpex_path),
            "--output",
            str(output),
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate_only"] is True
    assert payload["formal_clock_created"] is False
    assert payload["network_enabled"] is False
    assert payload["raw_evidence"]["entry_count"] == 2
    raw_manifest = output.parent / payload["raw_evidence"]["manifest_path"]
    manifest = json.loads(raw_manifest.read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 2
    for entry in manifest["entries"]:
        raw_path = raw_manifest.parent / entry["raw_file"]
        assert hash_response_bytes(raw_path.read_bytes()) == entry["raw_file_hash"]
        metadata_path = raw_manifest.parent / entry["metadata_file"]
        assert metadata_path.is_file()
    assert main(
        [
            "--start-date",
            "2026-09-01",
            "--end-date",
            "2026-09-02",
            "--twse-fixture",
            str(twse_path),
            "--tpex-fixture",
            str(tpex_path),
            "--output",
            str(output),
        ]
    ) == 2


def test_cli_without_fixtures_or_confirmation_does_not_write(tmp_path: Path) -> None:
    output = tmp_path / "blocked.json"
    code = main(
        [
            "--start-date",
            "2026-09-01",
            "--end-date",
            "2026-09-02",
            "--output",
            str(output),
        ]
    )

    assert code == 1
    assert not output.exists()


def test_candidate_writer_rejects_non_temp_path(tmp_path: Path) -> None:
    twse, tpex = _responses()
    bundle = build_official_calendar_bundle(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        twse_responses=twse,  # type: ignore[arg-type]
        tpex_responses=tpex,  # type: ignore[arg-type]
    )
    with pytest.raises(OfficialCalendarBundleError, match="TEMP"):
        write_candidate_bundle(Path.cwd() / "candidate-outside-test.json", bundle)


def test_raw_evidence_writer_rejects_missing_bytes_instead_of_reserializing(
    tmp_path: Path,
) -> None:
    twse, _ = _responses()
    with pytest.raises(OfficialCalendarBundleError, match="lacks captured raw bytes"):
        write_raw_response_evidence(tmp_path / "raw", {"twse:2026": twse[2026]})  # type: ignore[arg-type]


def test_raw_evidence_manifest_keeps_exact_bytes_and_metadata(tmp_path: Path) -> None:
    raw = b'{"exact": [1, 2], "whitespace": true}\r\n'
    from data_module.official_calendar_bundle import CapturedCalendarResponse

    response = CapturedCalendarResponse(
        kind="twse",
        key="2026",
        source="https://example.invalid/twse",
        source_hash=hash_response_bytes(raw),
        payload={"exact": [1, 2], "whitespace": True},
        raw_bytes=raw,
        metadata={"http_status": 200, "request_params": {"queryYear": "115"}},
    )
    result = write_raw_response_evidence(tmp_path / "raw", {"twse:2026": response})
    raw_path = tmp_path / "raw" / "twse_2026.response.bin"
    assert raw_path.read_bytes() == raw
    assert result["entry_count"] == 1
    assert result["entries"][0]["raw_file_hash"] == hash_response_bytes(raw)  # type: ignore[index]
