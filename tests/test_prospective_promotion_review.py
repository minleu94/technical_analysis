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
from data_module.prospective_promotion_review import (
    REQUIRED_MACHINE_GATES,
    ProspectivePromotionReviewError,
    build_prospective_promotion_review_package,
    validate_prospective_promotion_review_package,
    write_immutable_promotion_review_package,
)


HASHES = ["sha256:" + str(index) * 64 for index in range(1, 10)]
NOW = datetime.fromisoformat("2026-12-31T16:00:00+08:00")


def _activation_and_policy():
    policy = build_prospective_calibration_policy(
        policy_id="calibration-policy:pfs10:test",
        clock_id="clock:prospective:pfs10:test",
        model_artifact_hash=HASHES[0],
        dataset_identity_hash=HASHES[1],
    )
    activation = ProspectiveClockActivation(
        payload={
            "clock_id": "clock:prospective:pfs10:test",
            "clock_manifest_hash": HASHES[2],
            "activation_trading_day": "2026-08-17",
            "candidate_model_hash": HASHES[0],
            "candidate_feature_manifest_hash": HASHES[3],
            "calibration_policy_hash": policy.policy_hash,
            "evaluation_policy_hash": HASHES[4],
        },
        activation_manifest_hash=HASHES[5],
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


def _oos_package(activation: ProspectiveClockActivation, policy, maturity):
    body: dict[str, object] = {
        "schema_version": "prospective-formal-frozen-oos-evidence.v1",
        "status": "ready_for_formal_review",
        "mode": "prospective_formal_simulation",
        "capture_only": True,
        "clock_id": activation.clock_id,
        "clock_manifest_hash": activation.payload["clock_manifest_hash"],
        "activation_manifest_hash": activation.activation_manifest_hash,
        "maturity_report_hash": maturity["report_hash"],
        "candidate_model_hash": policy.payload["model_artifact_hash"],
        "candidate_feature_manifest_hash": activation.payload["candidate_feature_manifest_hash"],
        "dataset_identity_hash": policy.payload["dataset_identity_hash"],
        "calibration_policy_hash": policy.policy_hash,
        "evaluation_policy_hash": activation.payload["evaluation_policy_hash"],
        "primary_replay_result_hash": HASHES[6],
        "verification_replay_result_hash": HASHES[6],
        "replay_identity_hash": HASHES[7],
        "calibration_audit_hash": HASHES[8],
        "calibration_quality_pass": True,
        "psi_report_hash": HASHES[8],
        "psi_quality_pass": True,
        "blockers": [],
        "replay_fit_called": False,
        "retrained": False,
        "post_outcome_method_selection": False,
        "replay_used": True,
        "backfilled": False,
        "synthetic_outcomes_used": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    return {**body, "package_hash": payload_hash(body)}


def _all_gates() -> dict[str, bool]:
    return {name: True for name in REQUIRED_MACHINE_GATES}


def test_all_machine_gates_ready_still_requires_owner_review() -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    oos = _oos_package(activation, policy, maturity)
    review = build_prospective_promotion_review_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        oos_evidence_package=oos,
        machine_gates=_all_gates(),
        machine_metrics={"matured_shadow_days": 20, "max_ece_bp": 400, "max_psi_bp": 120},
        now=NOW,
    )
    assert review["status"] == "ready_for_owner_review"
    assert review["owner_review_required"] is True
    assert review["owner_review_received"] is False
    assert review["owner_authorization_received"] is False
    assert review["promotion_eligible"] is False
    assert review["formal_oos_allowed"] is False
    assert review["production_blend_alpha_bp"] == 0


def test_missing_or_failed_machine_gates_block_without_authority() -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    oos = _oos_package(activation, policy, maturity)
    review = build_prospective_promotion_review_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        oos_evidence_package=oos,
        machine_gates=None,
        machine_metrics=None,
        now=NOW,
    )
    blockers = cast(list[str], review["blockers"])
    assert review["status"] == "blocked_for_owner_review"
    assert "machine_gate_input_missing" in blockers
    assert review["promotion_eligible"] is False

    gates = _all_gates()
    gates["cost_after_fee_pass"] = False
    failed = build_prospective_promotion_review_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        oos_evidence_package=oos,
        machine_gates=gates,
        machine_metrics={},
        now=NOW,
    )
    assert "machine_gate_failed:cost_after_fee_pass" in cast(list[str], failed["blockers"])


def test_tampered_owner_or_machine_gate_is_rejected(tmp_path: Path) -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    oos = _oos_package(activation, policy, maturity)
    review = build_prospective_promotion_review_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        oos_evidence_package=oos,
        machine_gates=_all_gates(),
        machine_metrics={},
        now=NOW,
    )
    tampered = dict(review)
    tampered["owner_authorization_received"] = True
    body = dict(tampered)
    body.pop("review_hash", None)
    tampered["review_hash"] = payload_hash(body)
    with pytest.raises(ProspectivePromotionReviewError, match="owner_authorization_received"):
        validate_prospective_promotion_review_package(
            tampered,
            activation=activation,
            calibration_policy=policy,
            oos_evidence_package=oos,
        )
    output = tmp_path / "review.json"
    assert write_immutable_promotion_review_package(output, review).startswith("sha256:")
    with pytest.raises(ProspectivePromotionReviewError, match="already exists"):
        write_immutable_promotion_review_package(output, review)
    assert json.loads(output.read_text(encoding="utf-8"))["review_hash"] == review[
        "review_hash"
    ]


def test_non_ready_oos_evidence_is_a_review_blocker() -> None:
    activation, policy = _activation_and_policy()
    maturity = _maturity_report(activation)
    oos = _oos_package(activation, policy, maturity)
    oos["status"] = "waiting_for_frozen_oos_evidence"
    oos["blockers"] = ["calibration_quality_failed"]
    body = dict(oos)
    body.pop("package_hash", None)
    oos["package_hash"] = payload_hash(body)
    review = build_prospective_promotion_review_package(
        activation=activation,
        calibration_policy=policy,
        maturity_report=maturity,
        oos_evidence_package=oos,
        machine_gates=_all_gates(),
        machine_metrics={},
        now=NOW,
    )
    assert "oos_evidence_not_ready_for_formal_review" in cast(list[str], review["blockers"])


def test_pfs10_cli_requires_fixture_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.inspect_prospective_promotion_review import main

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
            "--oos-evidence-package",
            str(tmp_path / "oos.json"),
            "--now",
            NOW.isoformat(),
            "--output",
            str(tmp_path / "review.json"),
        ]
    )
    assert code == 2
    assert "fixture-only" in capsys.readouterr().err
