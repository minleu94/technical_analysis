from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from data_module.prospective_formal_clock import (
    CALENDAR_EVIDENCE_SCHEMA_VERSION,
    PROSPECTIVE_FORMAL_CLOCK_MODE,
    PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION,
    ProspectiveFormalClockError,
    build_clock_manifest,
    payload_hash,
    validate_clock_manifest,
    write_immutable_clock_manifest,
)
from scripts.publish_prospective_formal_clock import main


_NOW = "2026-08-15T09:00:00+08:00"
_HASHES = {
    "policy_hash": "sha256:" + "2" * 64,
    "universe_hash": "sha256:" + "3" * 64,
    "source_policy_hash": "sha256:" + "4" * 64,
    "candidate_model_hash": "sha256:" + "5" * 64,
    "candidate_feature_manifest_hash": "sha256:" + "6" * 64,
    "calibration_policy_hash": "sha256:" + "7" * 64,
    "evaluation_policy_hash": "sha256:" + "8" * 64,
}


def _calendar(day: str = "2026-08-17") -> dict[str, object]:
    return {
        "schema_version": CALENDAR_EVIDENCE_SCHEMA_VERSION,
        "date": day,
        "is_trading_day": True,
        "reason_code": "twse_holiday_schedule_open",
        "source": "TWSE holidaySchedule",
        "source_hash": "sha256:" + "1" * 64,
    }


def _seed() -> dict[str, object]:
    seed: dict[str, object] = {
        "kind": "cash",
        "cash_bp": 10_000,
        "position_count": 0,
    }
    seed["state_hash"] = payload_hash(seed)
    return seed


def _clock_body(**overrides: object) -> dict[str, object]:
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
        "activation_calendar_evidence": _calendar(),
        "seed_state": _seed(),
        "virtual_notional_minor_units": 1_000_000,
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        **_HASHES,
        "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    body.update(overrides)
    return body


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _cli_args(tmp_path: Path, *, fixture_only: bool = True, activation_day: str = "2026-08-17") -> list[str]:
    calendar_path = tmp_path / "calendar.json"
    seed_path = tmp_path / "seed.json"
    _write_json(calendar_path, _calendar(activation_day))
    _write_json(seed_path, _seed())
    args = [
        "--clock-id",
        "clock:prospective:20260817:r1",
        "--owner-decision-id",
        "owner-decision:prospective-clock-20260814",
        "--owner-decision-timestamp",
        "2026-08-14T08:45:00+08:00",
        "--activation-trading-day",
        activation_day,
        "--calendar-evidence-json",
        str(calendar_path),
        "--seed-state-json",
        str(seed_path),
        "--virtual-notional-minor-units",
        "1000000",
        "--strategy-version",
        "rule-v1",
        "--policy-version",
        "policy-v1",
    ]
    for name, value in _HASHES.items():
        args.extend([f"--{name.replace('_', '-')}", value])
    args.extend(
        [
            "--candidate-training-cutoff",
            "2026-08-13T08:30:00+08:00",
            "--now",
            _NOW,
            "--output",
            str(tmp_path / "clock.json"),
        ]
    )
    if fixture_only:
        args.insert(0, "--fixture-only")
    return args


def test_write_clock_manifest_is_create_only_and_hashes_bytes(tmp_path: Path) -> None:
    manifest = build_clock_manifest(_clock_body())
    validate_clock_manifest(
        manifest,
        now=datetime.fromisoformat(_NOW),
        calendar_evidence=_calendar(),
    )
    output = tmp_path / "clock.json"
    file_hash = write_immutable_clock_manifest(output, manifest)
    assert file_hash.startswith("sha256:")
    assert json.loads(output.read_text(encoding="utf-8")) == manifest
    with pytest.raises(ProspectiveFormalClockError, match="already exists"):
        write_immutable_clock_manifest(output, manifest)


def test_cli_requires_explicit_fixture_only(tmp_path: Path) -> None:
    assert main(_cli_args(tmp_path, fixture_only=False)) == 2
    assert not (tmp_path / "clock.json").exists()


def test_cli_publishes_owner_bound_future_clock(tmp_path: Path) -> None:
    assert main(_cli_args(tmp_path)) == 0
    manifest = json.loads((tmp_path / "clock.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "planned"
    assert manifest["activation_trading_day"] == "2026-08-17"
    assert manifest["real_money"] is False
    assert manifest["historical_backfill_claimed"] is False
    validate_clock_manifest(
        manifest,
        now=datetime.fromisoformat(_NOW),
        calendar_evidence=_calendar(),
    )


def test_cli_publishes_distinct_pit_and_owner_decision_times(tmp_path: Path) -> None:
    args = _cli_args(tmp_path)
    output_index = args.index("--output") + 1
    args[output_index] = str(tmp_path / "clock_distinct_times.json")
    decision_index = args.index("--decision-time") if "--decision-time" in args else None
    if decision_index is None:
        args[args.index("--calendar-evidence-json"):args.index("--calendar-evidence-json")] = [
            "--decision-time",
            "09:00:00",
            "--pit-decision-time",
            "08:30:00",
        ]
    else:
        args[decision_index + 1] = "09:00:00"
    assert main(args) == 0
    manifest = json.loads((tmp_path / "clock_distinct_times.json").read_text(encoding="utf-8"))
    assert manifest["decision_time"] == "09:00:00"
    assert manifest["pit_decision_time"] == "08:30:00"


def test_cli_rejects_same_day_activation(tmp_path: Path) -> None:
    assert main(_cli_args(tmp_path, activation_day="2026-08-15")) == 2
    assert not (tmp_path / "clock.json").exists()
