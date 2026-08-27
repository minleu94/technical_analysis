from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence, cast

import pytest

from data_module.formal_simulated_portfolio_ledger import (
    append_simulated_transition,
    build_simulated_transition,
    summarize_simulated_ledger,
)
from data_module.prospective_calibration_policy import (
    build_prospective_calibration_policy,
    publish_prospective_calibration_policy,
)
from data_module.prospective_capture_readiness import (
    PROSPECTIVE_CAPTURE_READINESS_DEFERRED_SCHEMA_VERSION,
    ProspectiveCaptureReadinessError,
    build_prospective_capture_readiness_report,
    write_immutable_capture_readiness_report,
)
from data_module.prospective_formal_clock import (
    build_clock_manifest,
    canonical_json,
    payload_hash,
)
from ml_module.allocation_contracts import AllocationWeightContract, CausalPortfolioState


MODEL_HASH = "sha256:" + "1" * 64
DATASET_HASH = "sha256:" + "2" * 64
UNIVERSE_HASH = "sha256:" + "3" * 64
DECISION_TIMESTAMP = "2026-08-17T08:30:00+08:00"
PLANNING_NOW = datetime.fromisoformat("2026-08-15T09:00:00+08:00")
ACTIVE_NOW = datetime.fromisoformat("2026-08-18T09:00:00+08:00")


def _policy(tmp_path: Path):
    policy = build_prospective_calibration_policy(
        policy_id="calibration-policy:pfs06:test",
        clock_id="clock:prospective:pfs06:test",
        model_artifact_hash=MODEL_HASH,
        dataset_identity_hash=DATASET_HASH,
    )
    path = tmp_path / "calibration-policy.json"
    publish_prospective_calibration_policy(policy, path)
    return policy, path


def _clock(
    tmp_path: Path,
    policy,
    *,
    decision_time: str = "08:30:00",
    pit_decision_time: str | None = None,
):
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
        "clock_id": policy.payload["clock_id"],
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-decision:pfs06-test",
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
    path = tmp_path / "clock.json"
    path.write_text(canonical_json(build_clock_manifest(body)), encoding="utf-8")
    return path


def _report_kwargs(
    tmp_path: Path,
    *,
    active: bool = False,
    decision_time: str = "08:30:00",
    pit_decision_time: str | None = None,
):
    policy, policy_path = _policy(tmp_path)
    clock_path = _clock(
        tmp_path,
        policy,
        decision_time=decision_time,
        pit_decision_time=pit_decision_time,
    )
    return {
        "clock_manifest_path": clock_path,
        "calibration_policy_path": policy_path,
        "decision_timestamp": DECISION_TIMESTAMP,
        "now": ACTIVE_NOW if active else PLANNING_NOW,
        "expected_symbols": ("2317", "2330"),
        "active_clock": active,
    }


def _inputs(report: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    return cast(Sequence[Mapping[str, object]], report["inputs"])


def _guard(report: Mapping[str, object]) -> Mapping[str, object]:
    return cast(Mapping[str, object], report["heavy_rebuild_guard"])


def test_missing_inputs_wait_and_never_launch_heavy_rebuild(tmp_path: Path) -> None:
    report = build_prospective_capture_readiness_report(**_report_kwargs(tmp_path))
    assert report["status"] == "waiting_for_prospective_inputs"
    assert report["capture_only"] is True
    guard = _guard(report)
    assert guard["heavy_rebuild_launch_allowed"] is False
    assert guard["owner_confirmation_received"] is False
    assert guard["direct_ooc_invocation_count"] == 0
    assert report["formal_oos_allowed"] is False
    assert report["pit_decision_timestamp"] == DECISION_TIMESTAMP


def test_readiness_routes_separate_pit_boundary_without_weakening_strictness(
    tmp_path: Path,
) -> None:
    kwargs = _report_kwargs(
        tmp_path,
        active=True,
        decision_time="09:00:00",
        pit_decision_time="08:30:00",
    )
    kwargs["decision_timestamp"] = "2026-08-17T09:00:00+08:00"
    kwargs["pit_decision_timestamp"] = "2026-08-17T08:30:00+08:00"

    report = build_prospective_capture_readiness_report(**kwargs)

    assert report["status"] == "waiting_for_prospective_inputs"
    assert report["decision_timestamp"] == "2026-08-17T09:00:00+08:00"
    assert report["pit_decision_timestamp"] == "2026-08-17T08:30:00+08:00"
    assert all(item["state"] == "missing" for item in _inputs(report))


def test_deferred_readiness_rejects_wrong_separate_pit_boundary(
    tmp_path: Path,
) -> None:
    kwargs = _report_kwargs(
        tmp_path,
        decision_time="09:00:00",
        pit_decision_time="08:30:00",
    )
    kwargs["decision_timestamp"] = "2026-08-17T09:00:00+08:00"
    kwargs["pit_decision_timestamp"] = "2026-08-17T09:00:00+08:00"
    kwargs["defer_until_activation"] = True

    with pytest.raises(ProspectiveCaptureReadinessError, match="PIT time"):
        build_prospective_capture_readiness_report(**kwargs)


def test_deferred_pre_activation_readiness_breaks_non_cash_circular_gate(
    tmp_path: Path,
) -> None:
    kwargs = _report_kwargs(tmp_path)
    kwargs["decision_timestamp"] = "2026-08-17T08:30:00+08:00"
    kwargs["defer_until_activation"] = True

    report = build_prospective_capture_readiness_report(**kwargs)

    assert report["schema_version"] == PROSPECTIVE_CAPTURE_READINESS_DEFERRED_SCHEMA_VERSION
    assert report["status"] == "ready_for_future_activation"
    assert report["input_collection_phase"] == "deferred_until_activation"
    assert all(item["state"] == "deferred" for item in _inputs(report))
    assert all("path" not in item for item in _inputs(report))
    assert report["formal_oos_allowed"] is False
    assert _guard(report)["heavy_rebuild_launch_allowed"] is False


def test_deferred_readiness_rejects_active_clock_or_wrong_decision_time(
    tmp_path: Path,
) -> None:
    kwargs = _report_kwargs(tmp_path, active=True)
    kwargs["decision_timestamp"] = "2026-08-17T08:30:00+08:00"
    kwargs["defer_until_activation"] = True
    with pytest.raises(ProspectiveCaptureReadinessError, match="active clock"):
        build_prospective_capture_readiness_report(**kwargs)

    second_tmp = tmp_path / "wrong-time"
    second_tmp.mkdir()
    kwargs = _report_kwargs(second_tmp)
    kwargs["decision_timestamp"] = "2026-08-17T08:31:00+08:00"
    kwargs["defer_until_activation"] = True
    with pytest.raises(ProspectiveCaptureReadinessError, match="activation decision time"):
        build_prospective_capture_readiness_report(**kwargs)


def _cash_state() -> CausalPortfolioState:
    return CausalPortfolioState.create(
        as_of_date="2026-08-16",
        weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
        weekly_turnover_used_bp=0,
    )


def _write_valid_ledger_manifest(tmp_path: Path, clock_path: Path, policy) -> Path:
    from data_module.prospective_formal_clock import load_clock_manifest_for_capture

    clock = load_clock_manifest_for_capture(clock_path, now=ACTIVE_NOW)
    sqlite_path = tmp_path / "ledger.sqlite"
    first = build_simulated_transition(
        clock=clock,
        decision_date="2026-08-17",
        decision_at=DECISION_TIMESTAMP,
        previous_trading_day="2026-08-16",
        input_state=_cash_state(),
        desired_weights=AllocationWeightContract(
            positions_bp=(("2330", 1_000),), cash_bp=9_000
        ),
        feature_input_hash="sha256:" + "9" * 64,
        estimated_cost_bp=25,
        output_weekly_turnover_used_bp=1_000,
    )
    append_simulated_transition(sqlite_path, first)
    second = build_simulated_transition(
        clock=clock,
        decision_date="2026-08-18",
        decision_at="2026-08-18T08:30:00+08:00",
        previous_trading_day="2026-08-17",
        input_state=first.output_state,
        desired_weights=first.desired_weights,
        feature_input_hash="sha256:" + "a" * 64,
        estimated_cost_bp=0,
        output_weekly_turnover_used_bp=1_000,
        previous_chain_hash=first.chain_hash,
    )
    append_simulated_transition(sqlite_path, second)
    summary = summarize_simulated_ledger(sqlite_path, clock=clock)
    identity = {
        "schema_version": "prospective-formal-simulated-portfolio-ledger-manifest.v1",
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "sqlite_path": "ledger.sqlite",
        "sqlite_file_hash": summary.sqlite_file_hash,
        "transition_chain_hash": summary.transition_chain_hash,
        "decision_date_count": summary.decision_date_count,
        "non_cash_state_day_count": summary.non_cash_state_day_count,
    }
    body: dict[str, object] = {
        **identity,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "consumer_mode": "prospective_formal_simulation",
        "ledger_manifest_hash": payload_hash(identity),
    }
    body["manifest_hash"] = payload_hash(body)
    manifest_path = tmp_path / "ledger-manifest.json"
    manifest_path.write_text(canonical_json(body), encoding="utf-8")
    return manifest_path


def test_valid_ledger_wrapper_is_read_only_accepted(tmp_path: Path) -> None:
    kwargs = _report_kwargs(tmp_path, active=True)
    policy = build_prospective_calibration_policy(
        policy_id="calibration-policy:pfs06:test",
        clock_id="clock:prospective:pfs06:test",
        model_artifact_hash=MODEL_HASH,
        dataset_identity_hash=DATASET_HASH,
    )
    ledger_path = _write_valid_ledger_manifest(
        tmp_path,
        kwargs["clock_manifest_path"],
        policy,
    )
    kwargs["portfolio_ledger_manifest_path"] = ledger_path
    report = build_prospective_capture_readiness_report(**kwargs)
    ledger = next(item for item in _inputs(report) if item["input"] == "causal_simulated_portfolio_ledger")
    assert ledger["state"] == "ready"
    assert ledger["non_cash_state_day_count"] == 2
    assert _guard(report)["heavy_rebuild_launch_allowed"] is False


def test_absolute_or_tampered_ledger_wrapper_is_invalid(tmp_path: Path) -> None:
    kwargs = _report_kwargs(tmp_path, active=True)
    policy = build_prospective_calibration_policy(
        policy_id="calibration-policy:pfs06:test",
        clock_id="clock:prospective:pfs06:test",
        model_artifact_hash=MODEL_HASH,
        dataset_identity_hash=DATASET_HASH,
    )
    path = _write_valid_ledger_manifest(tmp_path, kwargs["clock_manifest_path"], policy)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sqlite_path"] = str((tmp_path / "ledger.sqlite").resolve())
    body = dict(payload)
    body.pop("manifest_hash", None)
    payload["manifest_hash"] = payload_hash(body)
    path.write_text(canonical_json(payload), encoding="utf-8")
    kwargs["portfolio_ledger_manifest_path"] = path
    report = build_prospective_capture_readiness_report(**kwargs)
    ledger = next(item for item in _inputs(report) if item["input"] == "causal_simulated_portfolio_ledger")
    assert ledger["state"] == "invalid"
    assert "relative child" in str(ledger["detail"])


def test_invalid_rule_and_pit_inputs_stay_fail_closed(tmp_path: Path) -> None:
    kwargs = _report_kwargs(tmp_path)
    rule_path = tmp_path / "rule.json"
    rule_path.write_text(canonical_json({"schema_version": "wrong"}), encoding="utf-8")
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(
        canonical_json({"schema_version": "pit-sector-membership-sidecar-v1"}),
        encoding="utf-8",
    )
    kwargs["rule_history_path"] = rule_path
    kwargs["pit_sector_membership_path"] = pit_path
    report = build_prospective_capture_readiness_report(**kwargs)
    states = {item["input"]: item["state"] for item in _inputs(report)}
    assert states["prospective_rule_champion_history"] == "invalid"
    assert states["prospective_pit_sector_membership"] == "invalid"
    assert report["status"] == "waiting_for_prospective_inputs"


def test_readiness_report_is_immutable(tmp_path: Path) -> None:
    report = build_prospective_capture_readiness_report(**_report_kwargs(tmp_path))
    output = tmp_path / "readiness.json"
    file_hash = write_immutable_capture_readiness_report(output, report)
    assert file_hash.startswith("sha256:")
    with pytest.raises(ProspectiveCaptureReadinessError, match="already exists"):
        write_immutable_capture_readiness_report(output, report)


def test_fixture_cli_requires_explicit_guard_and_keeps_heavy_off(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.inspect_prospective_capture_readiness import main

    kwargs = _report_kwargs(tmp_path)
    symbols_path = tmp_path / "symbols.json"
    symbols_path.write_text(json.dumps(["2317", "2330"]), encoding="utf-8")
    output = tmp_path / "readiness.json"
    assert main(
        [
            "--clock-manifest",
            str(kwargs["clock_manifest_path"]),
            "--calibration-policy",
            str(kwargs["calibration_policy_path"]),
            "--decision-timestamp",
            DECISION_TIMESTAMP,
            "--now",
            PLANNING_NOW.isoformat(),
            "--symbols-json",
            str(symbols_path),
            "--output",
            str(output),
        ]
    ) == 2
    capsys.readouterr()
    exit_code = main(
        [
            "--fixture-only",
            "--clock-manifest",
            str(kwargs["clock_manifest_path"]),
            "--calibration-policy",
            str(kwargs["calibration_policy_path"]),
            "--decision-timestamp",
            DECISION_TIMESTAMP,
            "--now",
            PLANNING_NOW.isoformat(),
            "--symbols-json",
            str(symbols_path),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.is_file()
    assert '"heavy_rebuild_launch_allowed": false' in captured.out
    assert captured.err == ""


def test_deferred_fixture_cli_publishes_staging_readiness_without_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.inspect_prospective_capture_readiness import main

    kwargs = _report_kwargs(tmp_path)
    symbols_path = tmp_path / "symbols.json"
    symbols_path.write_text(json.dumps(["2317", "2330"]), encoding="utf-8")
    output = tmp_path / "deferred-readiness.json"
    exit_code = main(
        [
            "--fixture-only",
            "--defer-until-activation",
            "--clock-manifest",
            str(kwargs["clock_manifest_path"]),
            "--calibration-policy",
            str(kwargs["calibration_policy_path"]),
            "--decision-timestamp",
            "2026-08-17T08:30:00+08:00",
            "--now",
            PLANNING_NOW.isoformat(),
            "--symbols-json",
            str(symbols_path),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.is_file()
    assert '"deferred_inputs": 3' in captured.out
    assert '"formal_oos_allowed": false' in captured.out
    assert captured.err == ""


def test_deferred_fixture_cli_accepts_separate_pit_timestamp(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.inspect_prospective_capture_readiness import main

    kwargs = _report_kwargs(
        tmp_path,
        decision_time="09:00:00",
        pit_decision_time="08:30:00",
    )
    symbols_path = tmp_path / "symbols.json"
    symbols_path.write_text(json.dumps(["2317", "2330"]), encoding="utf-8")
    output = tmp_path / "split-deferred-readiness.json"
    exit_code = main(
        [
            "--fixture-only",
            "--defer-until-activation",
            "--clock-manifest",
            str(kwargs["clock_manifest_path"]),
            "--calibration-policy",
            str(kwargs["calibration_policy_path"]),
            "--decision-timestamp",
            "2026-08-17T09:00:00+08:00",
            "--pit-decision-timestamp",
            "2026-08-17T08:30:00+08:00",
            "--now",
            PLANNING_NOW.isoformat(),
            "--symbols-json",
            str(symbols_path),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["decision_timestamp"] == "2026-08-17T09:00:00+08:00"
    assert payload["pit_decision_timestamp"] == "2026-08-17T08:30:00+08:00"
    assert '"formal_oos_allowed": false' in captured.out
    assert captured.err == ""


def test_controlled_environment_mode_fails_closed_without_formal_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.inspect_prospective_capture_readiness as inspector

    kwargs = _report_kwargs(tmp_path)
    symbols_path = tmp_path / "symbols.json"
    symbols_path.write_text(json.dumps(["2317", "2330"]), encoding="utf-8")
    output = tmp_path / "readiness.json"
    monkeypatch.setattr(
        inspector,
        "build_prospective_activation_environment_preflight",
        lambda: {
            "status": "waiting_for_controlled_environment",
            "blockers": [
                "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH:missing",
                "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH:missing",
                "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH:missing",
            ],
            "formal_paths": {},
        },
    )
    exit_code = inspector.main(
        [
            "--controlled-environment",
            "--clock-manifest",
            str(kwargs["clock_manifest_path"]),
            "--calibration-policy",
            str(kwargs["calibration_policy_path"]),
            "--decision-timestamp",
            DECISION_TIMESTAMP,
            "--now",
            PLANNING_NOW.isoformat(),
            "--symbols-json",
            str(symbols_path),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert not output.exists()
    assert "environment_blockers" in captured.err
    assert "secret_values_emitted" in captured.err
    assert "HMAC" not in captured.err


def test_readiness_cli_rejects_mixed_environment_modes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.inspect_prospective_capture_readiness import main

    kwargs = _report_kwargs(tmp_path)
    symbols_path = tmp_path / "symbols.json"
    symbols_path.write_text(json.dumps(["2317", "2330"]), encoding="utf-8")
    output = tmp_path / "readiness.json"
    exit_code = main(
        [
            "--fixture-only",
            "--controlled-environment",
            "--clock-manifest",
            str(kwargs["clock_manifest_path"]),
            "--calibration-policy",
            str(kwargs["calibration_policy_path"]),
            "--decision-timestamp",
            DECISION_TIMESTAMP,
            "--now",
            PLANNING_NOW.isoformat(),
            "--symbols-json",
            str(symbols_path),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "exactly one" in captured.err
