from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import cast

import pytest

from data_module.prospective_formal_clock import (
    CALENDAR_EVIDENCE_SCHEMA_VERSION,
    PROSPECTIVE_FORMAL_CLOCK_MODE,
    PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION,
    ProspectiveFormalClockError,
    build_clock_manifest,
    inspect_clock_manifest,
    load_clock_manifest,
    payload_hash,
)


_NOW = datetime.fromisoformat("2026-08-14T09:00:00+08:00")
_CALENDAR = {
    "schema_version": CALENDAR_EVIDENCE_SCHEMA_VERSION,
    "date": "2026-08-17",
    "is_trading_day": True,
    "reason_code": "twse_holiday_schedule_open",
    "source": "TWSE holidaySchedule",
    "source_hash": "sha256:" + "1" * 64,
}


def _manifest(**overrides: object) -> dict[str, object]:
    seed = {
        "kind": "cash",
        "cash_bp": 10_000,
        "position_count": 0,
    }
    seed["state_hash"] = payload_hash(seed)
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION,
        "status": "planned",
        "clock_id": "clock:prospective:20260817:r1",
        "mode": PROSPECTIVE_FORMAL_CLOCK_MODE,
        "owner_decision_id": "owner-decision:prospective-clock-20260814",
        "owner_decision_timestamp": "2026-08-14T08:45:00+08:00",
        "activation_trading_day": "2026-08-17",
        "decision_timezone": "Asia/Taipei",
        "decision_time": "08:30:00",
        "activation_calendar_evidence": dict(_CALENDAR),
        "seed_state": seed,
        "virtual_notional_minor_units": 1_000_000,
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        "policy_hash": "sha256:" + "2" * 64,
        "universe_hash": "sha256:" + "3" * 64,
        "source_policy_hash": "sha256:" + "4" * 64,
        "candidate_model_hash": "sha256:" + "5" * 64,
        "candidate_feature_manifest_hash": "sha256:" + "6" * 64,
        "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
        "calibration_policy_hash": "sha256:" + "7" * 64,
        "evaluation_policy_hash": "sha256:" + "8" * 64,
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    body.update(overrides)
    if "manifest_hash" not in body:
        body = build_clock_manifest(body)
    return body


def test_valid_future_clock_manifest_is_accepted(tmp_path: Path) -> None:
    clock = load_clock_manifest(
        _write_manifest(_manifest(), tmp_path),
        now=_NOW,
    )

    assert clock.mode == PROSPECTIVE_FORMAL_CLOCK_MODE
    assert clock.activation_trading_day.isoformat() == "2026-08-17"
    assert clock.custody_payload()["real_money"] is False
    assert clock.custody_payload()["broker_execution"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("activation_trading_day", "2026-08-14", "strictly after"),
        ("activation_trading_day", "2026-08-13", "strictly after"),
        ("candidate_training_cutoff", "2026-08-17T08:30:00+08:00", "before activation"),
        ("real_money", True, "real_money"),
        ("broker_execution", True, "broker_execution"),
        ("historical_backfill_claimed", True, "historical_backfill_claimed"),
    ],
)
def test_clock_rejects_retroactive_or_unsafe_manifest(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    body = _manifest(**{field: value})
    with pytest.raises(ProspectiveFormalClockError, match=message):
        load_clock_manifest(_write_manifest(body, tmp_path), now=_NOW)


def test_clock_rejects_unknown_fields_and_tampered_hash(tmp_path: Path) -> None:
    unknown = _manifest(unexpected="nope")
    with pytest.raises(ProspectiveFormalClockError, match="unknown fields"):
        load_clock_manifest(_write_manifest(unknown, tmp_path), now=_NOW)

    tampered = _manifest()
    tampered["policy_version"] = "policy-tampered"
    with pytest.raises(ProspectiveFormalClockError, match="manifest hash mismatch"):
        load_clock_manifest(_write_manifest(tampered, tmp_path), now=_NOW)


def test_clock_requires_official_calendar_evidence(tmp_path: Path) -> None:
    body = _manifest()
    body.pop("activation_calendar_evidence")
    body.pop("manifest_hash")
    body = build_clock_manifest(body)
    with pytest.raises(ProspectiveFormalClockError, match="missing fields.*activation_calendar_evidence"):
        load_clock_manifest(_write_manifest(body, tmp_path), now=_NOW)


def test_clock_rejects_invalid_seed_state_and_non_integer_notional(tmp_path: Path) -> None:
    bad_seed = _manifest()
    bad_seed["seed_state"] = {
        "kind": "cash",
        "cash_bp": 10_000,
        "position_count": 1,
        "state_hash": "sha256:" + "a" * 64,
    }
    bad_seed = build_clock_manifest({key: value for key, value in bad_seed.items() if key != "manifest_hash"})
    with pytest.raises(ProspectiveFormalClockError, match="position_count"):
        load_clock_manifest(_write_manifest(bad_seed, tmp_path), now=_NOW)

    bad_notional = _manifest(virtual_notional_minor_units=1.5)
    with pytest.raises(ProspectiveFormalClockError, match="positive integer"):
        load_clock_manifest(_write_manifest(bad_notional, tmp_path), now=_NOW)


def test_inspector_is_read_only_and_uses_manifest_calendar_evidence(tmp_path: Path) -> None:
    manifest_path = _write_manifest(_manifest(), tmp_path)
    report = inspect_clock_manifest(manifest_path, now=_NOW, calendar_evidence=None)
    assert report["status"] == "ready_for_activation"
    assert report["formal_oos_allowed"] is False
    assert report["read_only"] is True
    assert report["secret_values_emitted"] is False
    assert not (tmp_path / "formal.sqlite").exists()


def test_inspector_fails_closed_for_invalid_calendar_evidence(tmp_path: Path) -> None:
    invalid_calendar = dict(_CALENDAR)
    invalid_calendar["is_trading_day"] = False
    body = _manifest(activation_calendar_evidence=invalid_calendar)
    manifest_path = _write_manifest(body, tmp_path)
    report = inspect_clock_manifest(manifest_path, now=_NOW)
    assert report["status"] == "blocked"
    blockers = cast(list[object], report["blockers"])
    assert any("not an official trading day" in str(item) for item in blockers)


def test_inspector_accepts_injected_calendar_evidence(tmp_path: Path) -> None:
    manifest_path = _write_manifest(_manifest(), tmp_path)
    report = inspect_clock_manifest(
        manifest_path,
        now=_NOW,
        calendar_evidence=_CALENDAR,
    )
    assert report["status"] == "ready_for_activation"
    clock_payload = cast(dict[str, object], report["clock"])
    manifest_file_hash = cast(str, report["manifest_file_hash"])
    assert clock_payload["clock_id"] == "clock:prospective:20260817:r1"
    assert manifest_file_hash.startswith("sha256:")


def test_external_calendar_evidence_cannot_override_manifest(tmp_path: Path) -> None:
    manifest_path = _write_manifest(_manifest(), tmp_path)
    mismatched = dict(_CALENDAR)
    mismatched["source_hash"] = "sha256:" + "9" * 64
    with pytest.raises(ProspectiveFormalClockError, match="does not match manifest"):
        load_clock_manifest(
            manifest_path,
            now=_NOW,
            calendar_evidence=mismatched,
        )


def _write_manifest(payload: dict[str, object], root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / "manifest.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
