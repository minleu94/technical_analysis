from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from data_module.formal_next_clock_preparation import (
    _inspect_calendar_bundle,
    build_formal_next_clock_preparation_plan,
)
from data_module.official_calendar_bundle import (
    CapturedCalendarResponse,
    build_official_calendar_bundle,
    hash_response_bytes,
    write_raw_response_evidence,
)
from data_module.prospective_formal_clock import payload_hash


def _calendar_candidate(tmp_path: Path) -> Path:
    twse_raw = b'[{"Name":"ordinary","Date":"1150925","Description":"holiday"}]'
    tpex_raw = (
        b'{"calendar":{"total":1,"data":{"20260909":'
        b'{"holiday":false,"holidayList":[]}},"status":"success"}}'
    )
    twse = CapturedCalendarResponse(
        kind="twse",
        key="2026",
        source="https://example.invalid/twse?queryYear=115",
        source_hash=hash_response_bytes(twse_raw),
        payload=json.loads(twse_raw.decode("utf-8")),
        raw_bytes=twse_raw,
        metadata={"http_status": 200},
    )
    tpex = CapturedCalendarResponse(
        kind="tpex",
        key="202609",
        source="https://example.invalid/tpex?ym=202609",
        source_hash=hash_response_bytes(tpex_raw),
        payload=json.loads(tpex_raw.decode("utf-8")),
        raw_bytes=tpex_raw,
        metadata={"http_status": 200},
    )
    bundle = build_official_calendar_bundle(
        start_date=date(2026, 9, 9),
        end_date=date(2026, 9, 9),
        twse_responses={2026: twse},
        tpex_responses={"202609": tpex},
        captured_at=datetime(2026, 9, 8, 10, tzinfo=timezone.utc),
    )
    raw_evidence = write_raw_response_evidence(
        tmp_path / "calendar_raw",
        {"twse:2026": twse, "tpex:202609": tpex},
    )
    bundle["raw_evidence"] = {
        "schema_version": "official-calendar-raw-evidence-manifest.v1",
        "manifest_path": "calendar_raw/manifest.json",
        "manifest_file_hash": raw_evidence["manifest_file_hash"],
        "manifest_hash": raw_evidence["manifest_hash"],
        "entry_count": raw_evidence["entry_count"],
    }
    body = dict(bundle)
    body.pop("bundle_hash", None)
    bundle["bundle_hash"] = payload_hash(body)
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


@pytest.mark.parametrize("tamper_kind", ["raw", "metadata"])
def test_calendar_raw_custody_rejects_raw_or_metadata_tampering(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    bundle_path = _calendar_candidate(tmp_path)
    manifest_path = tmp_path / "calendar_raw" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["entries"][0]
    tampered_path = manifest_path.parent / entry[
        "raw_file" if tamper_kind == "raw" else "metadata_file"
    ]
    if tamper_kind == "raw":
        tampered_path.write_bytes(tampered_path.read_bytes() + b"tampered")
    else:
        tampered_path.write_text('{"tampered":true}', encoding="utf-8")

    _, blockers = _inspect_calendar_bundle(
        bundle_path,
        activation_date=date(2026, 9, 9),
    )

    expected = "raw_hash_invalid" if tamper_kind == "raw" else "metadata_hash_invalid"
    assert any(expected in blocker for blocker in blockers)


def test_calendar_raw_custody_rejects_manifest_path_escape(tmp_path: Path) -> None:
    bundle_path = _calendar_candidate(tmp_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["raw_evidence"]["manifest_path"] = "../outside-manifest.json"
    body = dict(bundle)
    body.pop("bundle_hash", None)
    bundle["bundle_hash"] = payload_hash(body)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    _, blockers = _inspect_calendar_bundle(
        bundle_path,
        activation_date=date(2026, 9, 9),
    )

    assert "official_calendar_bundle_raw_evidence_manifest_path_outside_bundle_root" in blockers


def test_preparation_rejects_owner_decision_after_observed(tmp_path: Path) -> None:
    calendar_path = _calendar_candidate(tmp_path)
    market_db = tmp_path / "market.db"
    cache = tmp_path / "cache.json"
    snapshot = tmp_path / "paper.sqlite"
    market_db.write_bytes(b"market")
    cache.write_bytes(b"cache")
    snapshot.write_bytes(b"snapshot")

    plan = build_formal_next_clock_preparation_plan(
        observed=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        activation_date=date(2026, 9, 9),
        planned_clock_id="clock:prospective:20260909:test",
        controlled_clock_root=tmp_path / "controlled",
        clock_candidate_manifest=tmp_path / "clock.json",
        official_calendar_bundle=calendar_path,
        twse_calendar_cache=cache,
        market_db=market_db,
        publication_root=tmp_path / "publications",
        paper_snapshot_db=snapshot,
        paper_fill_db=tmp_path / "missing-fills.sqlite",
        identity_manifest=tmp_path / "identity.json",
        owner_decision_id="root-test-owner",
        owner_decision_timestamp="2026-09-08T13:00:00+00:00",
    )

    assert "owner_decision_timestamp_after_observed" in plan["blockers"]
