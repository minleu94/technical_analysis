from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from data_module.formal_simulated_portfolio_ledger import (
    append_simulated_transition,
    build_simulated_transition,
)
from data_module.prospective_calibration_policy import (
    build_prospective_calibration_policy,
)
from data_module.prospective_formal_clock import (
    build_clock_manifest,
    canonical_json,
    load_clock_manifest_for_capture,
    payload_hash,
)
from data_module.prospective_simulated_ledger_manifest import (
    ProspectiveSimulatedLedgerManifestError,
    build_prospective_simulated_ledger_manifest,
    publish_prospective_simulated_ledger_manifest,
)
from ml_module.allocation_contracts import AllocationWeightContract, CausalPortfolioState


MODEL_HASH = "sha256:" + "1" * 64
DATASET_HASH = "sha256:" + "2" * 64
UNIVERSE_HASH = "sha256:" + "3" * 64
PLANNING_NOW = datetime.fromisoformat("2026-08-18T09:00:00+08:00")


def _clock(tmp_path: Path):
    policy = build_prospective_calibration_policy(
        policy_id="calibration-policy:ledger-manifest:test",
        clock_id="clock:prospective:ledger-manifest:test",
        model_artifact_hash=MODEL_HASH,
        dataset_identity_hash=DATASET_HASH,
    )
    seed = {"kind": "cash", "cash_bp": 10_000, "position_count": 0}
    seed["state_hash"] = payload_hash(seed)
    body: dict[str, object] = {
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
        "clock_id": policy.payload["clock_id"],
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-decision:ledger-manifest:test",
        "owner_decision_timestamp": "2026-08-14T08:45:00+08:00",
        "activation_trading_day": "2026-08-17",
        "decision_timezone": "Asia/Taipei",
        "decision_time": "08:30:00",
        "activation_calendar_evidence": {
            "schema_version": "official-trading-calendar-evidence.v1",
            "date": "2026-08-17",
            "is_trading_day": True,
            "reason_code": "twse_holiday_schedule_open",
            "source": "TWSE holidaySchedule",
            "source_hash": "sha256:" + "4" * 64,
        },
        "seed_state": seed,
        "virtual_notional_minor_units": 1_000_000,
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        "policy_hash": "sha256:" + "5" * 64,
        "universe_hash": UNIVERSE_HASH,
        "source_policy_hash": "sha256:" + "6" * 64,
        "candidate_model_hash": MODEL_HASH,
        "candidate_feature_manifest_hash": "sha256:" + "7" * 64,
        "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
        "calibration_policy_hash": policy.policy_hash,
        "evaluation_policy_hash": "sha256:" + "8" * 64,
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    clock_path = tmp_path / "clock.json"
    clock_path.write_text(canonical_json(build_clock_manifest(body)), encoding="utf-8")
    return load_clock_manifest_for_capture(clock_path, now=PLANNING_NOW)


def _ledger(tmp_path: Path, clock) -> Path:
    sqlite_path = tmp_path / "ledger.sqlite"
    input_state = CausalPortfolioState.create(
        as_of_date="2026-08-16",
        weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
        weekly_turnover_used_bp=0,
    )
    transition = build_simulated_transition(
        clock=clock,
        decision_date="2026-08-17",
        decision_at="2026-08-17T08:30:00+08:00",
        previous_trading_day="2026-08-16",
        input_state=input_state,
        desired_weights=AllocationWeightContract(
            positions_bp=(("2330", 1_000),),
            cash_bp=9_000,
        ),
        feature_input_hash="sha256:" + "9" * 64,
        estimated_cost_bp=25,
        output_weekly_turnover_used_bp=1_000,
    )
    append_simulated_transition(sqlite_path, transition)
    follow_up = build_simulated_transition(
        clock=clock,
        decision_date="2026-08-18",
        decision_at="2026-08-18T08:30:00+08:00",
        previous_trading_day="2026-08-17",
        input_state=transition.output_state,
        desired_weights=transition.desired_weights,
        feature_input_hash="sha256:" + "a" * 64,
        estimated_cost_bp=0,
        output_weekly_turnover_used_bp=1_000,
        previous_chain_hash=transition.chain_hash,
    )
    append_simulated_transition(sqlite_path, follow_up)
    return sqlite_path


def test_manifest_publisher_custodies_relative_sqlite_and_non_cash_state(
    tmp_path: Path,
) -> None:
    clock = _clock(tmp_path)
    sqlite_path = _ledger(tmp_path, clock)
    output = tmp_path / "ledger-manifest.json"
    manifest = build_prospective_simulated_ledger_manifest(
        clock=clock,
        sqlite_path=sqlite_path,
        manifest_path=output,
        now=PLANNING_NOW,
    )
    assert manifest["schema_version"] == (
        "prospective-formal-simulated-portfolio-ledger-manifest.v1"
    )
    assert manifest["status"] == "complete"
    assert manifest["formal_source_only"] is True
    assert manifest["research_only"] is False
    assert manifest["formal_consumer_compatible"] is True
    assert manifest["promotion_eligible"] is False
    assert manifest["sqlite_path"] == "ledger.sqlite"
    assert manifest["non_cash_state_day_count"] == 1
    assert publish_prospective_simulated_ledger_manifest(output, manifest).startswith(
        "sha256:"
    )
    assert json.loads(output.read_text(encoding="utf-8"))["manifest_hash"] == manifest[
        "manifest_hash"
    ]
    with pytest.raises(ProspectiveSimulatedLedgerManifestError, match="already exists"):
        publish_prospective_simulated_ledger_manifest(output, manifest)


def test_manifest_publisher_rejects_sqlite_outside_manifest_directory(
    tmp_path: Path,
) -> None:
    clock = _clock(tmp_path)
    other_dir = tmp_path.parent / f"other-{tmp_path.name}"
    other_dir.mkdir()
    outside = _ledger(other_dir, clock)
    with pytest.raises(ProspectiveSimulatedLedgerManifestError, match="child"):
        build_prospective_simulated_ledger_manifest(
            clock=clock,
            sqlite_path=outside,
            manifest_path=tmp_path / "ledger-manifest.json",
            now=PLANNING_NOW,
        )


def test_manifest_publisher_rechecks_sqlite_hash_before_write(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    sqlite_path = _ledger(tmp_path, clock)
    output = tmp_path / "ledger-manifest.json"
    manifest = build_prospective_simulated_ledger_manifest(
        clock=clock,
        sqlite_path=sqlite_path,
        manifest_path=output,
        now=PLANNING_NOW,
    )
    sqlite_path.write_bytes(sqlite_path.read_bytes() + b"tamper")
    with pytest.raises(ProspectiveSimulatedLedgerManifestError, match="file hash"):
        publish_prospective_simulated_ledger_manifest(output, manifest)


def test_manifest_publisher_cli_requires_fixture_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.publish_prospective_simulated_portfolio_ledger import main

    code = main(
        [
            "--clock-manifest",
            str(tmp_path / "clock.json"),
            "--sqlite",
            str(tmp_path / "ledger.sqlite"),
            "--now",
            PLANNING_NOW.isoformat(),
            "--output",
            str(tmp_path / "manifest.json"),
        ]
    )
    assert code == 2
    assert "fixture-only" in capsys.readouterr().err
