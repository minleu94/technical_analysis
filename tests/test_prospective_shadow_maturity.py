from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import cast

import pytest

from data_module.prospective_formal_clock import payload_hash
from data_module.prospective_formal_clock_activation import (
    ProspectiveClockActivation,
)
from data_module.prospective_shadow_maturity import (
    ProspectiveShadowMaturityError,
    build_prospective_shadow_maturity_report,
    build_prospective_shadow_observation,
    validate_prospective_shadow_observation,
    write_immutable_shadow_maturity_report,
)


NOW = datetime.fromisoformat("2026-12-31T16:00:00+08:00")
HASHES = ["sha256:" + str(index) * 64 for index in range(1, 10)]


def _activation() -> ProspectiveClockActivation:
    return ProspectiveClockActivation(
        payload={
            "clock_id": "clock:prospective:pfs08:test",
            "clock_manifest_hash": HASHES[0],
            "activation_trading_day": "2026-08-17",
            "decision_time": "08:30:00",
            "owner_activation_id": "owner-activation:pfs08-test",
        },
        activation_manifest_hash=HASHES[1],
    )


def _observation(activation: ProspectiveClockActivation, day: date, index: int):
    rows = [
        {
            "horizon_trading_days": horizon,
            "outcome_date": (day + timedelta(days=horizon)).isoformat(),
            "matured_at": (
                day + timedelta(days=horizon)
            ).isoformat()
            + "T12:00:00+08:00",
            "realized_return_bp": index * 10 - 100,
            "rebalance_worthwhile": index % 2 == 0,
            "outcome_source_hash": HASHES[(index + horizon) % len(HASHES)],
        }
        for horizon in (5, 10, 20, 60)
    ]
    return build_prospective_shadow_observation(
        activation=activation,
        capture_date=day.isoformat(),
        decision_timestamp=day.isoformat() + "T08:30:00+08:00",
        previous_trading_day=(day - timedelta(days=1)).isoformat(),
        input_state_date=(day - timedelta(days=1)).isoformat(),
        pit_publication_hash=HASHES[2],
        rule_snapshot_hash=HASHES[3],
        portfolio_transition_hash=HASHES[4],
        inference_artifact_hash=HASHES[5],
        source_lineage_hash=HASHES[6],
        outcome_rows=rows,
        now=NOW,
    )


def test_missing_shadow_days_waits_and_never_allows_formal_oos() -> None:
    report = build_prospective_shadow_maturity_report(
        activation=_activation(),
        observations=[],
        now=NOW,
    )
    assert report["status"] == "waiting_for_maturity"
    assert report["maturity_gate_pass"] is False
    assert report["formal_oos_allowed"] is False
    assert report["production_blend_alpha_bp"] == 0
    assert "shadow_days_insufficient:0/20" in cast(list[str], report["blockers"])


def test_twenty_complete_days_and_all_horizons_are_shadow_only_ready() -> None:
    activation = _activation()
    observations = [
        _observation(activation, date(2026, 8, 17) + timedelta(days=index), index)
        for index in range(20)
    ]
    report = build_prospective_shadow_maturity_report(
        activation=activation,
        observations=observations,
        now=NOW,
    )
    assert report["status"] == "maturity_gate_ready_shadow_only"
    assert report["maturity_gate_pass"] is True
    assert report["observed_day_count"] == 20
    horizon = cast(dict[str, object], report["horizon_maturity"])
    for key in ("5", "10", "20", "60"):
        detail = cast(dict[str, object], horizon[key])
        assert detail["matured_observation_count"] == 20
        assert detail["rebalance_worthwhile_class_counts"] == {"0": 10, "1": 10}
    assert report["replay_used"] is False
    assert report["backfilled"] is False
    assert report["synthetic_outcomes_used"] is False
    assert report["formal_oos_allowed"] is False


def test_observation_rejects_future_outcome_and_unsafe_flags() -> None:
    activation = _activation()
    day = date(2026, 8, 17)
    with pytest.raises(ProspectiveShadowMaturityError, match="outside matured boundary"):
        build_prospective_shadow_observation(
            activation=activation,
            capture_date=day.isoformat(),
            decision_timestamp="2026-08-17T08:30:00+08:00",
            previous_trading_day="2026-08-16",
            input_state_date="2026-08-16",
            pit_publication_hash=HASHES[2],
            rule_snapshot_hash=HASHES[3],
            portfolio_transition_hash=HASHES[4],
            inference_artifact_hash=HASHES[5],
            source_lineage_hash=HASHES[6],
            outcome_rows=[
                {
                    "horizon_trading_days": 5,
                    "outcome_date": "2027-01-01",
                    "matured_at": "2027-01-01T12:00:00+08:00",
                    "realized_return_bp": 10,
                    "rebalance_worthwhile": True,
                    "outcome_source_hash": HASHES[7],
                }
            ],
            now=NOW,
        )
    observation = _observation(activation, day, 0)
    unsafe = dict(observation)
    unsafe["future_teacher_target_used"] = True
    unsafe_body = dict(unsafe)
    unsafe_body.pop("observation_hash", None)
    unsafe["observation_hash"] = payload_hash(unsafe_body)
    with pytest.raises(ProspectiveShadowMaturityError, match="future_teacher_target_used"):
        validate_prospective_shadow_observation(unsafe, activation=activation, now=NOW)


def test_maturity_rejects_duplicate_or_unsorted_capture_dates() -> None:
    activation = _activation()
    first = _observation(activation, date(2026, 8, 17), 0)
    duplicate = _observation(activation, date(2026, 8, 17), 1)
    with pytest.raises(ProspectiveShadowMaturityError, match="unique and sorted"):
        build_prospective_shadow_maturity_report(
            activation=activation,
            observations=[first, duplicate],
            now=NOW,
        )


def test_maturity_report_is_create_only(tmp_path: Path) -> None:
    report = build_prospective_shadow_maturity_report(
        activation=_activation(),
        observations=[],
        now=NOW,
    )
    output = tmp_path / "maturity.json"
    assert write_immutable_shadow_maturity_report(output, report).startswith("sha256:")
    with pytest.raises(ProspectiveShadowMaturityError, match="already exists"):
        write_immutable_shadow_maturity_report(output, report)
    assert json.loads(output.read_text(encoding="utf-8"))["report_hash"] == report[
        "report_hash"
    ]


def test_maturity_cli_requires_fixture_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.inspect_prospective_shadow_maturity import main

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
            "--observations-json",
            str(tmp_path / "observations.json"),
            "--now",
            NOW.isoformat(),
            "--output",
            str(tmp_path / "maturity.json"),
        ]
    )
    assert code == 2
    assert "fixture-only" in capsys.readouterr().err
