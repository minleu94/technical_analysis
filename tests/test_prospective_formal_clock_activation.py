from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Mapping, cast

import pytest

from data_module.prospective_calibration_policy import (
    build_prospective_calibration_policy,
)
from data_module.prospective_formal_clock import (
    build_clock_manifest,
    canonical_json,
    file_sha256,
    load_clock_manifest,
    payload_hash,
)
from data_module.prospective_formal_clock_activation import (
    CONTROLLED_PATH_ENV_NAMES,
    DAILY_CAPTURE_SEQUENCE,
    ProspectiveClockActivationError,
    build_daily_capture_activation_record,
    build_prospective_clock_activation_manifest,
    validate_prospective_clock_activation_manifest,
    write_immutable_clock_activation_manifest,
    write_immutable_daily_capture_activation_record,
)


MODEL_HASH = "sha256:" + "1" * 64
DATASET_HASH = "sha256:" + "2" * 64
UNIVERSE_HASH = "sha256:" + "3" * 64
PLANNING_NOW = datetime.fromisoformat("2026-08-15T10:00:00+08:00")
ACTIVE_NOW = datetime.fromisoformat("2026-08-17T09:00:00+08:00")


def _clock_and_policy(
    tmp_path: Path,
    *,
    decision_time: str = "08:30:00",
    pit_decision_time: str | None = None,
):
    policy = build_prospective_calibration_policy(
        policy_id="calibration-policy:pfs07:test",
        clock_id="clock:prospective:pfs07:test",
        model_artifact_hash=MODEL_HASH,
        dataset_identity_hash=DATASET_HASH,
    )
    seed = {"kind": "cash", "cash_bp": 10_000, "position_count": 0}
    seed["state_hash"] = payload_hash(seed)
    calendar = {
        "schema_version": "official-trading-calendar-evidence.v1",
        "date": "2026-08-17",
        "is_trading_day": True,
        "reason_code": "twse_holiday_schedule_open",
        "source": "TWSE holidaySchedule",
        "source_hash": "sha256:" + "4" * 64,
    }
    body: dict[str, object] = {
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
        "clock_id": "clock:prospective:pfs07:test",
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-decision:pfs07-test",
        "owner_decision_timestamp": "2026-08-14T08:45:00+08:00",
        "activation_trading_day": "2026-08-17",
        "decision_timezone": "Asia/Taipei",
        "decision_time": decision_time,
        "activation_calendar_evidence": calendar,
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
    if pit_decision_time is not None:
        body["pit_decision_time"] = pit_decision_time
    clock_path = tmp_path / "clock.json"
    clock_path.write_text(canonical_json(build_clock_manifest(body)), encoding="utf-8")
    return load_clock_manifest(clock_path, now=PLANNING_NOW), policy


def _readiness(tmp_path: Path, clock, policy) -> tuple[dict[str, object], dict[str, Path]]:
    paths = {
        CONTROLLED_PATH_ENV_NAMES[0]: tmp_path / "portfolio-ledger.json",
        CONTROLLED_PATH_ENV_NAMES[1]: tmp_path / "rule-history.json",
        CONTROLLED_PATH_ENV_NAMES[2]: tmp_path / "pit-sector.json",
    }
    for path in paths.values():
        path.write_text(f"fixture:{path.name}", encoding="utf-8")
    input_names = (
        "causal_simulated_portfolio_ledger",
        "prospective_rule_champion_history",
        "prospective_pit_sector_membership",
    )
    inputs: list[dict[str, object]] = []
    for input_name, env_name in zip(input_names, CONTROLLED_PATH_ENV_NAMES):
        path = paths[env_name].resolve()
        inputs.append(
            {
                "input": input_name,
                "state": "ready",
                "path": str(path),
                "file_hash": file_sha256(path),
            }
        )
    body: dict[str, object] = {
        "schema_version": "prospective-formal-capture-readiness.v1",
        "status": "ready_for_future_activation",
        "mode": "prospective_formal_simulation",
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "calibration_policy_hash": policy.policy_hash,
        "decision_timestamp": "2026-08-15T09:30:00+08:00",
        "active_clock": False,
        "inputs": inputs,
        "capture_only": True,
        "heavy_rebuild_guard": {
            "heavy_rebuild_launch_allowed": False,
            "owner_confirmation_required_for_heavy_rebuild": True,
            "owner_confirmation_received": False,
            "direct_ooc_invocation_count": 0,
            "reason": "capture_only_preflight_never_launches_direct_or_ooc",
        },
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    return {**body, "readiness_hash": payload_hash(body)}, paths


def _deferred_readiness(clock, policy) -> dict[str, object]:
    inputs = [
        {
            "input": input_name,
            "state": "deferred",
            "reason": reason,
            "controlled_path_env_name": env_name,
            "formal_consumer_compatible": False,
        }
        for input_name, reason, env_name in (
            (
                "causal_simulated_portfolio_ledger",
                "collect_after_activation_first_non_cash_transition",
                CONTROLLED_PATH_ENV_NAMES[0],
            ),
            (
                "prospective_rule_champion_history",
                "collect_after_activation_controlled_store_snapshot",
                CONTROLLED_PATH_ENV_NAMES[1],
            ),
            (
                "prospective_pit_sector_membership",
                "collect_after_activation_licensed_publication",
                CONTROLLED_PATH_ENV_NAMES[2],
            ),
        )
    ]
    body: dict[str, object] = {
        "schema_version": "prospective-formal-capture-readiness-deferred.v1",
        "status": "ready_for_future_activation",
        "mode": "prospective_formal_simulation",
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "calibration_policy_hash": policy.policy_hash,
        "decision_timestamp": "2026-08-17T08:30:00+08:00",
        "active_clock": False,
        "inputs": inputs,
        "input_collection_phase": "deferred_until_activation",
        "capture_only": True,
        "heavy_rebuild_guard": {
            "heavy_rebuild_launch_allowed": False,
            "owner_confirmation_required_for_heavy_rebuild": True,
            "owner_confirmation_received": False,
            "direct_ooc_invocation_count": 0,
            "reason": "capture_only_preflight_never_launches_direct_or_ooc",
        },
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    return {**body, "readiness_hash": payload_hash(body)}


def _build_activation(tmp_path: Path):
    clock, policy = _clock_and_policy(tmp_path)
    readiness, paths = _readiness(tmp_path, clock, policy)
    manifest = build_prospective_clock_activation_manifest(
        clock=clock,
        calibration_policy=policy,
        readiness_report=readiness,
        controlled_paths=paths,
        controlled_store_id="controlled-store:pfs07-test",
        hmac_secret_store_configured=True,
        owner_activation_id="owner-activation:pfs07-test",
        owner_activation_timestamp=datetime.fromisoformat(
            "2026-08-15T09:00:00+08:00"
        ),
        now=PLANNING_NOW,
    )
    return clock, policy, readiness, paths, manifest


def test_activation_freezes_identities_and_three_controlled_paths(tmp_path: Path) -> None:
    clock, policy, readiness, paths, manifest = _build_activation(tmp_path)

    assert manifest["status"] == "scheduled"
    assert manifest["activation_trading_day"] == "2026-08-17"
    assert manifest["candidate_model_hash"] == MODEL_HASH
    assert manifest["calibration_policy_hash"] == policy.policy_hash
    assert manifest["controlled_paths"]
    assert manifest["heavy_rebuild_launch_allowed"] is False
    assert manifest["formal_oos_allowed"] is False
    activation = validate_prospective_clock_activation_manifest(
        manifest,
        clock=clock,
        calibration_policy=policy,
        readiness_report=readiness,
        now=PLANNING_NOW,
    )
    assert activation.activation_manifest_hash == manifest["manifest_hash"]
    assert set(cast(Mapping[str, object], manifest["controlled_paths"])) == set(
        CONTROLLED_PATH_ENV_NAMES
    )
    assert all(path.is_file() for path in paths.values())


def test_activation_preserves_separate_pit_decision_time(tmp_path: Path) -> None:
    clock, policy = _clock_and_policy(
        tmp_path,
        decision_time="09:00:00",
        pit_decision_time="08:30:00",
    )
    readiness, paths = _readiness(tmp_path, clock, policy)

    manifest = build_prospective_clock_activation_manifest(
        clock=clock,
        calibration_policy=policy,
        readiness_report=readiness,
        controlled_paths=paths,
        controlled_store_id="controlled-store:pfs07-split-test",
        hmac_secret_store_configured=True,
        owner_activation_id="owner-activation:pfs07-split-test",
        owner_activation_timestamp=datetime.fromisoformat(
            "2026-08-15T09:00:00+08:00"
        ),
        now=PLANNING_NOW,
    )

    assert manifest["decision_time"] == "09:00:00"
    assert manifest["pit_decision_time"] == "08:30:00"
    validate_prospective_clock_activation_manifest(
        manifest,
        clock=clock,
        calibration_policy=policy,
        readiness_report=readiness,
        now=PLANNING_NOW,
    )


def test_deferred_activation_can_be_scheduled_before_non_cash_inputs_exist(
    tmp_path: Path,
) -> None:
    clock, policy = _clock_and_policy(tmp_path)
    readiness = _deferred_readiness(clock, policy)
    deferred_paths = {name: None for name in CONTROLLED_PATH_ENV_NAMES}

    manifest = build_prospective_clock_activation_manifest(
        clock=clock,
        calibration_policy=policy,
        readiness_report=readiness,
        controlled_paths=deferred_paths,
        controlled_store_id="controlled-store:pfs07-test",
        hmac_secret_store_configured=True,
        owner_activation_id="owner-activation:pfs07-deferred",
        owner_activation_timestamp=datetime.fromisoformat(
            "2026-08-15T09:00:00+08:00"
        ),
        now=PLANNING_NOW,
    )

    assert manifest["readiness_status"] == "inputs_deferred_until_activation"
    controlled = cast(Mapping[str, Mapping[str, object]], manifest["controlled_paths"])
    assert all(entry["deferred"] is True for entry in controlled.values())
    assert all(entry["path"] is None for entry in controlled.values())
    validated = validate_prospective_clock_activation_manifest(
        manifest,
        clock=clock,
        calibration_policy=policy,
        readiness_report=readiness,
        now=PLANNING_NOW,
    )
    assert validated.activation_trading_day.isoformat() == "2026-08-17"


def test_activation_rejects_secret_absence_or_rebuild_request(tmp_path: Path) -> None:
    clock, policy = _clock_and_policy(tmp_path)
    readiness, paths = _readiness(tmp_path, clock, policy)
    with pytest.raises(ProspectiveClockActivationError, match="secret store"):
        build_prospective_clock_activation_manifest(
            clock=clock,
            calibration_policy=policy,
            readiness_report=readiness,
            controlled_paths=paths,
            controlled_store_id="controlled-store:pfs07-test",
            hmac_secret_store_configured=False,
            owner_activation_id="owner-activation:pfs07-test",
            owner_activation_timestamp=datetime.fromisoformat(
                "2026-08-15T09:00:00+08:00"
            ),
            now=PLANNING_NOW,
        )
    with pytest.raises(ProspectiveClockActivationError, match="rebuild"):
        build_prospective_clock_activation_manifest(
            clock=clock,
            calibration_policy=policy,
            readiness_report=readiness,
            controlled_paths=paths,
            controlled_store_id="controlled-store:pfs07-test",
            hmac_secret_store_configured=True,
            owner_activation_id="owner-activation:pfs07-test",
            owner_activation_timestamp=datetime.fromisoformat(
                "2026-08-15T09:00:00+08:00"
            ),
            now=PLANNING_NOW,
            rebuild_requested=True,
        )


def test_activation_rejects_path_drift_and_tampered_readiness(tmp_path: Path) -> None:
    clock, policy, readiness, paths, manifest = _build_activation(tmp_path)
    paths[CONTROLLED_PATH_ENV_NAMES[1]].write_text("changed", encoding="utf-8")
    with pytest.raises(ProspectiveClockActivationError, match="file changed"):
        validate_prospective_clock_activation_manifest(
            manifest,
            clock=clock,
            calibration_policy=policy,
            readiness_report=readiness,
            now=PLANNING_NOW,
        )
    paths[CONTROLLED_PATH_ENV_NAMES[1]].write_text("fixture:rule-history.json", encoding="utf-8")
    tampered = dict(readiness)
    tampered["status"] = "waiting_for_prospective_inputs"
    with pytest.raises(ProspectiveClockActivationError, match="not ready"):
        validate_prospective_clock_activation_manifest(
            manifest,
            clock=clock,
            calibration_policy=policy,
            readiness_report=tampered,
            now=PLANNING_NOW,
        )


def test_activation_manifest_is_create_only(tmp_path: Path) -> None:
    clock, policy, readiness, _, manifest = _build_activation(tmp_path)
    output = tmp_path / "activation.json"
    first_hash = write_immutable_clock_activation_manifest(output, manifest)
    assert first_hash.startswith("sha256:")
    with pytest.raises(ProspectiveClockActivationError, match="already exists"):
        write_immutable_clock_activation_manifest(output, manifest)
    assert json.loads(output.read_text(encoding="utf-8"))["manifest_hash"] == manifest[
        "manifest_hash"
    ]


def test_daily_capture_record_is_lightweight_and_zero_credit(tmp_path: Path) -> None:
    clock, policy, readiness, _, manifest = _build_activation(tmp_path)
    activation = validate_prospective_clock_activation_manifest(
        manifest,
        clock=clock,
        calibration_policy=policy,
        readiness_report=readiness,
        now=PLANNING_NOW,
    )
    record = build_daily_capture_activation_record(
        activation=activation,
        capture_date="2026-08-17",
        decision_timestamp="2026-08-17T08:30:00+08:00",
        started_at=datetime.fromisoformat("2026-08-17T08:31:00+08:00"),
        now=ACTIVE_NOW,
    )
    assert record["status"] == "started"
    assert record["scheduled_sequence"] == list(DAILY_CAPTURE_SEQUENCE)
    assert record["completed_steps"] == []
    assert record["elapsed_day_credit"] == 0
    assert record["formal_credit"] == 0
    assert record["direct_ooc_invocation_count"] == 0
    assert record["same_day_advice_used"] is False
    assert record["future_teacher_target_used"] is False
    output = tmp_path / "daily-capture.json"
    assert write_immutable_daily_capture_activation_record(output, record).startswith(
        "sha256:"
    )


@pytest.mark.parametrize(
    ("capture_date", "decision_timestamp", "message"),
    [
        ("2026-08-16", "2026-08-16T08:30:00+08:00", "precedes activation"),
        ("2026-08-17", "2026-08-17T09:00:00+08:00", "decision_time"),
    ],
)
def test_daily_capture_rejects_backfill_or_wrong_decision_time(
    tmp_path: Path,
    capture_date: str,
    decision_timestamp: str,
    message: str,
) -> None:
    clock, policy, readiness, _, manifest = _build_activation(tmp_path)
    activation = validate_prospective_clock_activation_manifest(
        manifest,
        clock=clock,
        calibration_policy=policy,
        readiness_report=readiness,
        now=PLANNING_NOW,
    )
    with pytest.raises(ProspectiveClockActivationError, match=message):
        build_daily_capture_activation_record(
            activation=activation,
            capture_date=capture_date,
            decision_timestamp=decision_timestamp,
            started_at=datetime.fromisoformat("2026-08-17T09:00:00+08:00"),
            now=ACTIVE_NOW,
        )


def test_activation_cli_requires_fixture_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.activate_prospective_formal_clock import main

    code = main(
        [
            "--clock-manifest",
            str(tmp_path / "clock.json"),
            "--calibration-policy",
            str(tmp_path / "policy.json"),
            "--readiness-report",
            str(tmp_path / "readiness.json"),
            "--portfolio-ledger-path",
            str(tmp_path / "ledger.json"),
            "--rule-history-path",
            str(tmp_path / "rule.json"),
            "--pit-sector-path",
            str(tmp_path / "pit.json"),
            "--controlled-store-id",
            "store",
            "--owner-activation-id",
            "activation",
            "--owner-activation-timestamp",
            "2026-08-15T09:00:00+08:00",
            "--now",
            PLANNING_NOW.isoformat(),
            "--output",
            str(tmp_path / "activation.json"),
        ]
    )
    assert code == 2
    assert "fixture-only" in capsys.readouterr().err


def test_activation_cli_controlled_environment_fails_closed_without_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.activate_prospective_formal_clock as activation_cli

    monkeypatch.setattr(
        activation_cli,
        "build_prospective_activation_environment_preflight",
        lambda: {
            "status": "waiting_for_controlled_environment",
            "blockers": [
                "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH:missing",
                "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH:missing",
                "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH:missing",
            ],
            "formal_paths": {},
            "hmac_secret_store": {"configured": True},
        },
    )
    monkeypatch.setattr(activation_cli, "resolve_controlled_store_id", lambda: None)
    code = activation_cli.main(
        [
            "--fixture-only",
            "--controlled-environment",
            "--clock-manifest",
            str(tmp_path / "clock.json"),
            "--calibration-policy",
            str(tmp_path / "policy.json"),
            "--readiness-report",
            str(tmp_path / "readiness.json"),
            "--owner-activation-id",
            "owner-activation:test",
            "--owner-activation-timestamp",
            "2026-08-15T09:00:00+08:00",
            "--now",
            PLANNING_NOW.isoformat(),
            "--output",
            str(tmp_path / "activation.json"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert not (tmp_path / "activation.json").exists()
    assert "environment_blockers" in captured.err
    assert "secret_values_emitted" in captured.err
    assert "HMAC secret" not in captured.err


def test_activation_cli_can_defer_inputs_in_controlled_environment(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.activate_prospective_formal_clock as activation_cli

    clock, policy = _clock_and_policy(tmp_path)
    clock_path = tmp_path / "clock.json"
    policy_path = tmp_path / "policy.json"
    readiness_path = tmp_path / "readiness-deferred.json"
    policy_path.write_text(canonical_json(policy.to_dict()), encoding="utf-8")
    readiness_path.write_text(
        canonical_json(_deferred_readiness(clock, policy)), encoding="utf-8"
    )
    monkeypatch.setattr(
        activation_cli,
        "build_prospective_activation_environment_preflight",
        lambda: {
            "status": "waiting_for_controlled_environment",
            "blockers": [
                "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH:missing",
                "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH:missing",
                "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH:missing",
            ],
            "formal_paths": {},
            "hmac_secret_store": {"configured": True},
        },
    )
    monkeypatch.setattr(
        activation_cli,
        "resolve_controlled_store_id",
        lambda: "controlled-store:pfs07-test",
    )
    secret = "never-print-this-test-secret"
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", secret)
    output = tmp_path / "activation-deferred.json"

    code = activation_cli.main(
        [
            "--fixture-only",
            "--controlled-environment",
            "--defer-inputs",
            "--clock-manifest",
            str(clock_path),
            "--calibration-policy",
            str(policy_path),
            "--readiness-report",
            str(readiness_path),
            "--owner-activation-id",
            "owner-activation:pfs07-deferred-cli",
            "--owner-activation-timestamp",
            "2026-08-15T09:00:00+08:00",
            "--now",
            PLANNING_NOW.isoformat(),
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert secret not in captured.out
    assert secret not in captured.err
    assert '"inputs_deferred": true' in captured.out
    manifest = json.loads(output.read_text(encoding="utf-8"))
    controlled = cast(Mapping[str, Mapping[str, object]], manifest["controlled_paths"])
    assert all(entry["deferred"] is True for entry in controlled.values())
    assert all(entry["path"] is None for entry in controlled.values())
    assert manifest["formal_oos_allowed"] is False
    assert manifest["promotion_eligible"] is False


def test_activation_cli_controlled_environment_rejects_explicit_store_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.activate_prospective_formal_clock import main

    code = main(
        [
            "--fixture-only",
            "--controlled-environment",
            "--controlled-store-id",
            "store-id-must-not-be-mixed",
            "--clock-manifest",
            str(tmp_path / "clock.json"),
            "--calibration-policy",
            str(tmp_path / "policy.json"),
            "--readiness-report",
            str(tmp_path / "readiness.json"),
            "--owner-activation-id",
            "owner-activation:test",
            "--owner-activation-timestamp",
            "2026-08-15T09:00:00+08:00",
            "--now",
            PLANNING_NOW.isoformat(),
            "--output",
            str(tmp_path / "activation.json"),
        ]
    )
    assert code == 2
    assert "forbids explicit" in capsys.readouterr().err
