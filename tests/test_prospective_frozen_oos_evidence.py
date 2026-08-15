from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import cast

import pytest

from data_module.prospective_calibration_policy import (
    build_prospective_calibration_policy,
)
from data_module.prospective_formal_clock import payload_hash
from data_module.prospective_formal_clock_activation import (
    ProspectiveClockActivation,
)
from data_module.prospective_frozen_oos_evidence import (
    ProspectiveFrozenOOSEvidenceError,
    build_prospective_frozen_oos_evidence_package,
    build_prospective_frozen_oos_replay_result,
    write_immutable_frozen_oos_evidence_package,
)


HASHES = ["sha256:" + str(index) * 64 for index in range(1, 10)]
NOW = datetime.fromisoformat("2026-12-31T16:00:00+08:00")


def _activation_and_policy():
    policy = build_prospective_calibration_policy(
        policy_id="calibration-policy:pfs09:test",
        clock_id="clock:prospective:pfs09:test",
        model_artifact_hash=HASHES[0],
        dataset_identity_hash=HASHES[1],
    )
    activation = ProspectiveClockActivation(
        payload={
            "clock_id": "clock:prospective:pfs09:test",
            "clock_manifest_hash": HASHES[2],
            "activation_manifest_hash": HASHES[3],
            "activation_trading_day": "2026-08-17",
            "candidate_model_hash": HASHES[0],
            "candidate_feature_manifest_hash": HASHES[4],
            "calibration_policy_hash": policy.policy_hash,
            "evaluation_policy_hash": HASHES[5],
        },
        activation_manifest_hash=HASHES[3],
    )
    return activation, policy


def _maturity_report(activation: ProspectiveClockActivation) -> dict[str, object]:
    dates = [
        (date(2026, 8, 17) + timedelta(days=index)).isoformat()
        for index in range(20)
    ]
    maturity = {
        str(horizon): {
            "matured_observation_count": 20,
            "matured_capture_dates": dates,
            "rebalance_worthwhile_class_counts": {"0": 10, "1": 10},
        }
        for horizon in (5, 10, 20, 60)
    }
    body: dict[str, object] = {
        "schema_version": "prospective-formal-shadow-maturity-report.v1",
        "status": "maturity_gate_ready_shadow_only",
        "mode": "prospective_formal_simulation",
        "capture_only": True,
        "clock_id": activation.clock_id,
        "clock_manifest_hash": activation.payload["clock_manifest_hash"],
        "activation_manifest_hash": activation.activation_manifest_hash,
        "observed_capture_dates": dates,
        "observed_day_count": 20,
        "minimum_shadow_days": 20,
        "minimum_matured_observations_per_horizon": 20,
        "observation_hashes": HASHES[:3],
        "horizon_maturity": maturity,
        "blockers": [],
        "maturity_gate_pass": True,
        "replay_used": False,
        "backfilled": False,
        "synthetic_outcomes_used": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    return {**body, "report_hash": payload_hash(body)}


def _replay(activation, policy, maturity_hash: str, *, role: str, identity: str = HASHES[6], replay_hash: str = HASHES[7]):
    return build_prospective_frozen_oos_replay_result(
        activation=activation,
        calibration_policy=policy,
        role=role,
        maturity_report_hash=maturity_hash,
        result_identity_hash=identity,
        replay_result_hash=replay_hash,
        source_lineage_hash=HASHES[8],
        outcome_row_count=80,
        horizon_observation_counts={"5": 20, "10": 20, "20": 20, "60": 20},
    )


def _maturity_hash(maturity: dict[str, object]) -> str:
    return cast(str, maturity["report_hash"])


def _calibration_audit(activation, policy, *, quality: bool = True):
    body: dict[str, object] = {
        "schema_version": "prospective-formal-inference-calibration-audit.v1",
        "status": "complete_shadow_diagnostic",
        "policy_hash": policy.policy_hash,
        "clock_id": activation.clock_id,
        "model_artifact_hash": policy.payload["model_artifact_hash"],
        "dataset_identity_hash": policy.payload["dataset_identity_hash"],
        "promotion_pass": False,
        "promotion_eligible": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "post_outcome_method_selection": "forbidden",
        "quality_pass": quality,
        "secret_values_emitted": False,
    }
    return {**body, "audit_hash": payload_hash(body)}


def _psi_report(activation, policy, *, quality: bool = True):
    body: dict[str, object] = {
        "schema_version": "prospective-formal-psi-report.v1",
        "status": "complete",
        "clock_id": activation.clock_id,
        "model_artifact_hash": policy.payload["model_artifact_hash"],
        "dataset_identity_hash": policy.payload["dataset_identity_hash"],
        "reference_identity_hash": HASHES[4],
        "feature_count": 62,
        "max_psi_bp": 120,
        "psi_threshold_bp": 500,
        "quality_pass": quality,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
    }
    return {**body, "report_hash": payload_hash(body)}


def test_complete_frozen_oos_package_binds_two_replays_and_stays_fail_closed() -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    primary = _replay(activation, policy, _maturity_hash(maturity), role="primary")
    verification = _replay(activation, policy, _maturity_hash(maturity), role="verification")
    package = build_prospective_frozen_oos_evidence_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        primary_replay=primary,
        verification_replay=verification,
        calibration_audit=_calibration_audit(activation, policy),
        psi_report=_psi_report(activation, policy),
        now=NOW,
    )
    assert package["status"] == "ready_for_formal_review"
    assert package["primary_replay_result_hash"] == primary["replay_result_hash"]
    assert package["verification_replay_result_hash"] == verification["replay_result_hash"]
    assert package["replay_identity_hash"] == HASHES[6]
    assert package["replay_fit_called"] is False
    assert package["retrained"] is False
    assert package["formal_oos_allowed"] is False
    assert package["production_blend_alpha_bp"] == 0
    assert package["promotion_eligible"] is False


def test_missing_or_failed_quality_inputs_only_create_blockers() -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    package = build_prospective_frozen_oos_evidence_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        primary_replay=None,
        verification_replay=None,
        calibration_audit=None,
        psi_report=None,
        now=NOW,
    )
    blockers = cast(list[str], package["blockers"])
    assert package["status"] == "waiting_for_frozen_oos_evidence"
    assert "primary_replay_missing" in blockers
    assert "psi_report_missing" in blockers
    assert package["formal_oos_allowed"] is False

    primary = _replay(activation, policy, _maturity_hash(maturity), role="primary")
    verification = _replay(activation, policy, _maturity_hash(maturity), role="verification")
    degraded = build_prospective_frozen_oos_evidence_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        primary_replay=primary,
        verification_replay=verification,
        calibration_audit=_calibration_audit(activation, policy, quality=False),
        psi_report=_psi_report(activation, policy, quality=False),
        now=NOW,
    )
    assert "calibration_quality_failed" in cast(list[str], degraded["blockers"])
    assert "psi_quality_failed" in cast(list[str], degraded["blockers"])


def test_primary_verification_identity_mismatch_is_blocked() -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    primary = _replay(activation, policy, _maturity_hash(maturity), role="primary")
    verification = _replay(
        activation,
        policy,
        _maturity_hash(maturity),
        role="verification",
        identity=HASHES[5],
    )
    package = build_prospective_frozen_oos_evidence_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        primary_replay=primary,
        verification_replay=verification,
        calibration_audit=_calibration_audit(activation, policy),
        psi_report=_psi_report(activation, policy),
        now=NOW,
    )
    assert "primary_verification_identity_mismatch" in cast(list[str], package["blockers"])


def test_maturity_gate_not_passed_cannot_enter_pfs09() -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    maturity["status"] = "waiting_for_maturity"
    body = dict(maturity)
    body.pop("report_hash", None)
    maturity["report_hash"] = payload_hash(body)
    with pytest.raises(ProspectiveFrozenOOSEvidenceError, match="maturity report status"):
        build_prospective_frozen_oos_evidence_package(
            activation=activation,
            calibration_policy=policy,
            maturity_report=maturity,
            primary_replay=None,
            verification_replay=None,
            calibration_audit=None,
            psi_report=None,
            now=NOW,
        )


def test_evidence_package_is_create_only(tmp_path: Path) -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    primary = _replay(activation, policy, _maturity_hash(maturity), role="primary")
    verification = _replay(activation, policy, _maturity_hash(maturity), role="verification")
    package = build_prospective_frozen_oos_evidence_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        primary_replay=primary,
        verification_replay=verification,
        calibration_audit=_calibration_audit(activation, policy),
        psi_report=_psi_report(activation, policy),
        now=NOW,
    )
    output = tmp_path / "evidence.json"
    assert write_immutable_frozen_oos_evidence_package(output, package).startswith("sha256:")
    with pytest.raises(ProspectiveFrozenOOSEvidenceError, match="already exists"):
        write_immutable_frozen_oos_evidence_package(output, package)
    assert json.loads(output.read_text(encoding="utf-8"))["package_hash"] == package[
        "package_hash"
    ]


def test_replay_result_rejects_fit_or_future_target_flag() -> None:
    activation, policy = _activation_and_policy()
    result = _replay(activation, policy, HASHES[8], role="primary")
    tampered = dict(result)
    tampered["fit_called"] = True
    body = dict(tampered)
    body.pop("result_hash", None)
    tampered["result_hash"] = payload_hash(body)
    from data_module.prospective_frozen_oos_evidence import validate_prospective_frozen_oos_replay_result

    with pytest.raises(ProspectiveFrozenOOSEvidenceError, match="fit_called"):
        validate_prospective_frozen_oos_replay_result(
            tampered,
            activation=activation,
            calibration_policy=policy,
            expected_maturity_report_hash=HASHES[8],
        )


def test_pfs09_cli_requires_fixture_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.inspect_prospective_frozen_oos import main

    code = main(
        [
            "--clock-manifest",
            str(tmp_path / "clock.json"),
            "--calibration-policy",
            str(tmp_path / "policy.json"),
            "--readiness-report",
            str(tmp_path / "readiness.json"),
            "--activation-manifest",
            str(tmp_path / "activation.json"),
            "--maturity-report",
            str(tmp_path / "maturity.json"),
            "--now",
            NOW.isoformat(),
            "--output",
            str(tmp_path / "evidence.json"),
        ]
    )
    assert code == 2
    assert "fixture-only" in capsys.readouterr().err
