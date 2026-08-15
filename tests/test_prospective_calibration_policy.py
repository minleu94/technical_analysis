from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Mapping, Sequence, cast

import pytest

from data_module.prospective_calibration_policy import (
    ProspectiveCalibrationError,
    audit_prospective_inference_calibration,
    build_prospective_calibration_policy,
    publish_prospective_calibration_policy,
    validate_policy_against_clock,
)
from data_module.prospective_formal_clock import (
    build_clock_manifest,
    payload_hash,
    validate_clock_manifest,
)


MODEL_HASH = "sha256:" + "1" * 64
DATASET_HASH = "sha256:" + "2" * 64
INFERENCE_HASH = "sha256:" + "3" * 64


def _policy(tmp_path: Path):
    return build_prospective_calibration_policy(
        policy_id="calibration-policy:pfs05:test",
        clock_id="clock:prospective:pfs05:test",
        model_artifact_hash=MODEL_HASH,
        dataset_identity_hash=DATASET_HASH,
    )


def _record(
    policy,
    horizon: int,
    rank: int,
    *,
    identity_ece: int = 700,
    identity_brier: int = 2_000,
    isotonic_ece: int = 400,
    isotonic_brier: int = 1_800,
    class_counts: tuple[int, int] = (5, 5),
    rebalance_counts: tuple[int, int] = (5, 5),
) -> dict[str, object]:
    return {
        "policy_hash": policy.policy_hash,
        "fold_id": f"h{horizon}-fold-{rank}",
        "fold_rank": rank,
        "fit_fold_ids": [f"h{horizon}-fold-{index}" for index in range(rank)],
        "fit_fold_ranks": list(range(rank)),
        "horizon_trading_days": horizon,
        "sample_count": sum(class_counts),
        "class_counts": {"0": class_counts[0], "1": class_counts[1]},
        "rebalance_worthwhile_class_counts": {
            "0": rebalance_counts[0],
            "1": rebalance_counts[1],
        },
        "identity_metrics": {
            "ece_bp": identity_ece,
            "brier_bp": identity_brier,
        },
        "isotonic_metrics": {
            "ece_bp": isotonic_ece,
            "brier_bp": isotonic_brier,
        },
        "model_artifact_hash": MODEL_HASH,
        "dataset_identity_hash": DATASET_HASH,
        "inference_identity_hash": INFERENCE_HASH,
        "source_lineage_hash": "sha256:" + ("a" * 64),
    }


def _records(policy) -> list[dict[str, object]]:
    return [
        _record(policy, horizon, rank)
        for horizon in (5, 10, 20, 60)
        for rank in (2, 3)
    ]


def test_policy_is_immutable_and_hash_bound(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    path = tmp_path / "policy.json"
    publication = publish_prospective_calibration_policy(policy, path)
    assert publication.policy_hash == policy.policy_hash
    assert publication.policy_file_hash.startswith("sha256:")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == (
        "prospective-formal-inference-calibration-policy.v1"
    )
    with pytest.raises(ProspectiveCalibrationError, match="already exists"):
        publish_prospective_calibration_policy(policy, path)


def test_inference_audit_passes_only_as_shadow_diagnostic(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    audit = audit_prospective_inference_calibration(
        policy=policy,
        fold_records=_records(policy),
    )
    assert audit["quality_pass"] is True
    assert audit["promotion_pass"] is False
    assert audit["promotion_eligible"] is False
    assert audit["formal_oos_allowed"] is False
    assert audit["production_blend_alpha_bp"] == 0
    assert audit["primary_method"] == "isotonic_integer_bp"
    methods = cast(Mapping[str, Mapping[str, object]], audit["methods"])
    assert methods["isotonic_integer_bp"]["ece_bp"] == 400
    assert methods["identity"]["brier_bp"] == 2_000
    assert cast(Sequence[str], audit["blockers"]) == []


def test_target_fold_cannot_enter_calibration_fit(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    records = _records(policy)
    target = next(
        item
        for item in records
        if item["horizon_trading_days"] == 5 and item["fold_rank"] == 3
    )
    target["fit_fold_ranks"] = [0, 1, 3]
    report = audit_prospective_inference_calibration(
        policy=policy,
        fold_records=records,
    )
    assert report["quality_pass"] is False
    assert "calibration_fit_boundary_failed:h5:f3" in cast(
        Sequence[str], report["blockers"]
    )


def test_post_outcome_method_selection_cannot_hide_worse_isotonic_metrics(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path)
    records = _records(policy)
    for record in records:
        record["isotonic_metrics"] = {"ece_bp": 300, "brier_bp": 2_001}
    report = audit_prospective_inference_calibration(
        policy=policy,
        fold_records=records,
    )
    assert report["quality_pass"] is False
    assert "primary_calibration_brier_not_improved" in cast(
        Sequence[str], report["blockers"]
    )
    assert report["primary_method"] == "isotonic_integer_bp"


def test_class_zero_only_rebalance_head_is_a_blocker(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    records = _records(policy)
    for record in records:
        record["rebalance_worthwhile_class_counts"] = {"0": 10, "1": 0}
    report = audit_prospective_inference_calibration(
        policy=policy,
        fold_records=records,
    )
    assert report["quality_pass"] is False
    assert "rebalance_worthwhile_class_coverage_missing:h5" in cast(
        Sequence[str], report["blockers"]
    )


def test_missing_horizon_is_fail_closed(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    records = [item for item in _records(policy) if item["horizon_trading_days"] != 60]
    report = audit_prospective_inference_calibration(
        policy=policy,
        fold_records=records,
    )
    assert report["quality_pass"] is False
    assert "calibration_horizon_missing:h60" in cast(
        Sequence[str], report["blockers"]
    )


def test_policy_must_bind_to_clock_policy_hash_and_model(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
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
    clock_payload: dict[str, object] = {
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
        "clock_id": policy.payload["clock_id"],
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-decision:pfs05-test",
        "owner_decision_timestamp": "2026-08-14T08:45:00+08:00",
        "activation_trading_day": "2026-08-17",
        "decision_timezone": "Asia/Taipei",
        "decision_time": "08:30:00",
        "activation_calendar_evidence": calendar,
        "seed_state": seed,
        "virtual_notional_minor_units": 1_000_000,
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        "policy_hash": "sha256:" + "5" * 64,
        "universe_hash": "sha256:" + "6" * 64,
        "source_policy_hash": "sha256:" + "7" * 64,
        "candidate_model_hash": MODEL_HASH,
        "candidate_feature_manifest_hash": "sha256:" + "8" * 64,
        "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
        "calibration_policy_hash": policy.policy_hash,
        "evaluation_policy_hash": "sha256:" + "9" * 64,
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    clock = validate_clock_manifest(
        build_clock_manifest(clock_payload),
        now=datetime.fromisoformat("2026-08-15T09:00:00+08:00"),
    )
    validate_policy_against_clock(policy, clock)
    bad_payload = dict(policy.payload)
    bad_payload["clock_id"] = "clock:other"
    bad_payload["policy_hash"] = payload_hash(
        {key: value for key, value in bad_payload.items() if key != "policy_hash"}
    )
    bad_policy = type(policy)(payload=bad_payload, policy_hash=bad_payload["policy_hash"])
    with pytest.raises(ProspectiveCalibrationError, match="clock_id mismatch"):
        validate_policy_against_clock(bad_policy, clock)


def test_fixture_cli_is_explicit_and_secret_safe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = _policy(tmp_path)
    policy_path = tmp_path / "policy.json"
    publish_prospective_calibration_policy(policy, policy_path)
    records_path = tmp_path / "records.json"
    records_path.write_text(json.dumps(_records(policy)), encoding="utf-8")
    output_path = tmp_path / "audit.json"
    from scripts.audit_prospective_inference_calibration import main

    exit_code = main(
        [
            "--fixture-only",
            "--policy",
            str(policy_path),
            "--fold-records-json",
            str(records_path),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert output_path.is_file()
    assert '"quality_pass": true' in captured.out
    assert '"secret_values_emitted": false' in captured.out
    assert captured.err == ""
