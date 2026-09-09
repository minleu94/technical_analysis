from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import cast

import pytest

from ml_module.natural_shadow_pruning_evidence import (
    NaturalShadowPruningEvidenceError,
    build_natural_shadow_pruning_evidence,
    write_natural_shadow_pruning_evidence,
)
from scripts.inspect_ml_natural_shadow_pruning_evidence import main as evidence_cli


MODEL_HASH = "sha256:" + "1" * 64
DATASET_HASH = "sha256:" + "2" * 64
POLICY_HASH = "sha256:" + "3" * 64


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _observation(
    decision_date: date,
    *,
    revision: int = 1,
    credit: bool = True,
    lanes: bool = True,
    metrics: dict[str, object] | None = None,
    model_hash: str = MODEL_HASH,
    policy_hash: str = POLICY_HASH,
    emitted_at: str | None = None,
    available_at: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "ml-allocation-shadow-observation.v1",
        "decision_date": decision_date.isoformat(),
        "custody_hash": _hash({"date": decision_date.isoformat(), "revision": revision}),
        "revision": revision,
        "emitted_at": emitted_at or f"{decision_date.isoformat()}T09:00:00+08:00",
        "promotion_day_credit_allowed": credit,
        "replayed": False,
        "backfilled": False,
        "synthetic_outcomes_used": False,
        "custody": {
            "model_hash": model_hash,
            "dataset_identity_hash": DATASET_HASH,
            "policy_hash": policy_hash,
        },
    }
    if lanes:
        body["lanes"] = [
            {
                "slice_id": "alpha:0",
                "alpha_bp": 0,
                "lane_metrics": metrics,
            }
        ]
    if available_at is not None:
        body["available_at"] = available_at
    return {**body, "record_hash": _hash(body)}


def _outcome(
    observation: dict[str, object],
    *,
    complete: bool = True,
    revision: int = 1,
    worthwhile: bool = True,
    matured_date: date | None = None,
) -> dict[str, object]:
    observation_hash = str(observation["record_hash"])
    horizon_rows = [5, 10, 20, 60] if complete else [5]
    matured_day = matured_date or date.fromisoformat(str(observation["decision_date"]))
    body: dict[str, object] = {
        "schema_version": "ml-allocation-shadow-outcome.v1",
        "observation_hash": observation_hash,
        "custody_hash": _hash({"observation_hash": observation_hash, "revision": revision}),
        "revision": revision,
        "status": "matured_all_horizons" if complete else "partial_horizon_maturity",
        "completed_horizons_trading_sessions": horizon_rows,
        "latest_used_date": matured_day.isoformat(),
        "downside_outcomes": [
            {
                "horizon_trading_sessions": horizon,
                "outcome_date": (matured_day + timedelta(days=horizon)).isoformat(),
                "available_at": f"{matured_day.isoformat()}T17:00:00+08:00",
                "actual_downside": 0 if worthwhile else 1,
                "realized_return_bp": 100 if worthwhile else -100,
            }
            for horizon in horizon_rows
        ],
    }
    return {**body, "record_hash": _hash(body)}


def _write_sidecar(
    path: Path,
    observations: list[dict[str, object]],
    outcomes: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE shadow_observations (
                record_hash TEXT PRIMARY KEY,
                decision_date TEXT NOT NULL,
                custody_hash TEXT NOT NULL,
                revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE (decision_date, custody_hash),
                UNIQUE (decision_date, revision)
            );
            CREATE TABLE shadow_outcomes (
                record_hash TEXT PRIMARY KEY,
                observation_hash TEXT NOT NULL,
                custody_hash TEXT NOT NULL,
                revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE (observation_hash, custody_hash),
                UNIQUE (observation_hash, revision)
            );
            """
        )
        for observation in observations:
            connection.execute(
                "INSERT INTO shadow_observations VALUES (?, ?, ?, ?, ?)",
                (
                    observation["record_hash"],
                    observation["decision_date"],
                    observation["custody_hash"],
                    observation["revision"],
                    _canonical(observation),
                ),
            )
        for outcome in outcomes:
            connection.execute(
                "INSERT INTO shadow_outcomes VALUES (?, ?, ?, ?, ?)",
                (
                    outcome["record_hash"],
                    outcome["observation_hash"],
                    outcome["custody_hash"],
                    outcome["revision"],
                    _canonical(outcome),
                ),
            )


def _complete_metrics() -> dict[str, object]:
    return {
        "sample_count": 30,
        "hit_rate_bp": 6000,
        "score_monotonic": True,
        "payoff_ratio_bp": 12000,
    }


def test_pending_projection_counts_only_creditable_complete_natural_observations(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    credited_but_partial = _observation(date(2026, 1, 1))
    research_only = _observation(date(2026, 1, 2), credit=False)
    _write_sidecar(
        sidecar,
        [credited_but_partial, research_only],
        [
            _outcome(credited_but_partial, complete=False),
            _outcome(research_only, complete=True),
        ],
    )

    report = build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-01-03",
        expected_model_hash=MODEL_HASH,
        expected_dataset_identity_hash=DATASET_HASH,
    )

    assert report["status"] == "pending_maturity"
    assert report["observation_count"] == 2
    assert report["matured_observation_count"] == 0
    assert report["pending_observation_count"] == 2
    assert report["pruning_review_inputs"] == []
    pending = cast(list[Mapping[str, object]], report["pending_observations"])
    reasons = {
        reason
        for item in pending
        for reason in cast(list[str], item["reasons"])
    }
    assert "natural_day_credit_not_allowed" in reasons
    assert "outcome_not_matured_all_horizons" in reasons


def test_latest_revisions_are_deduped_and_output_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    first = _observation(date(2026, 1, 5), revision=1)
    latest = _observation(date(2026, 1, 5), revision=2)
    _write_sidecar(
        sidecar,
        [first, latest],
        [
            _outcome(latest, complete=False, revision=1),
            _outcome(latest, complete=True, revision=2),
        ],
    )

    report = build_natural_shadow_pruning_evidence(sidecar, as_of_date=date(2026, 1, 6))
    source = cast(Mapping[str, object], report["source"])
    assert source["latest_observation_count"] == 1
    assert source["latest_outcome_count"] == 1
    assert report["matured_observation_count"] == 1
    assert report["matured_observation_hashes"] == [latest["record_hash"]]
    assert report["pending_observation_count"] == 0

    output = tmp_path / "evidence.json"
    assert write_natural_shadow_pruning_evidence(output, report) == "inserted"
    assert write_natural_shadow_pruning_evidence(output, report) == "idempotent"
    changed = build_natural_shadow_pruning_evidence(sidecar, as_of_date=date(2026, 1, 7))
    with pytest.raises(NaturalShadowPruningEvidenceError, match="conflict"):
        write_natural_shadow_pruning_evidence(output, changed)


def test_matured_projection_keeps_pruning_pending_until_real_lane_metrics_exist(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    observations = [
        _observation(date(2026, 2, 1) + timedelta(days=index), metrics=None)
        for index in range(20)
    ]
    outcomes = [
        _outcome(observation, worthwhile=index % 2 == 0)
        for index, observation in enumerate(observations)
    ]
    _write_sidecar(sidecar, observations, outcomes)

    report = build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-02-28",
        expected_model_hash=MODEL_HASH,
        expected_dataset_identity_hash=DATASET_HASH,
    )

    assert report["matured_observation_count"] == 20
    assert report["maturity_blockers"] == []
    assert report["status"] == "pending_pruning_metrics"
    assert report["pruning_review_inputs"] == []
    assert report["pending_pruning_slices"] == [
        {
            "slice_id": "alpha:0",
            "matured_observation_count": 20,
            "reason": "pruning_metrics_missing_or_invalid",
        }
    ]
    boundary = cast(Mapping[str, object], report["pruning_boundary"])
    assert boundary["apply_action"] is False
    assert boundary["promotion_eligible"] is False


def test_ready_projection_exposes_only_supplied_metrics_and_no_action_boundary(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    observations = [
        _observation(
            date(2026, 3, 1) + timedelta(days=index),
            metrics=_complete_metrics(),
        )
        for index in range(20)
    ]
    outcomes = [
        _outcome(observation, worthwhile=index % 2 == 0)
        for index, observation in enumerate(observations)
    ]
    _write_sidecar(sidecar, observations, outcomes)

    report = build_natural_shadow_pruning_evidence(sidecar, as_of_date="2026-03-31")

    assert report["status"] == "ready_for_pruning_review"
    inputs = cast(list[Mapping[str, object]], report["pruning_review_inputs"])
    assert len(inputs) == 1
    assert inputs[0]["slice_id"] == "alpha:0"
    assert inputs[0]["matured_observation_count"] == 20
    assert inputs[0]["metrics_complete"] is True
    input_observations = cast(list[Mapping[str, object]], inputs[0]["observations"])
    assert input_observations[0]["metrics"] == _complete_metrics()
    assert report["pruning_boundary"] == {
        "evidence_only": True,
        "apply_action": False,
        "review_required": True,
        "promotion_eligible": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
    }


def test_zero_sample_lane_metrics_remain_pruning_pending(tmp_path: Path) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    zero_sample_metrics = {**_complete_metrics(), "sample_count": 0}
    observations = [
        _observation(
            date(2026, 3, 1) + timedelta(days=index),
            metrics=zero_sample_metrics,
        )
        for index in range(20)
    ]
    _write_sidecar(
        sidecar,
        observations,
        [
            _outcome(observation, worthwhile=index % 2 == 0)
            for index, observation in enumerate(observations)
        ],
    )

    report = build_natural_shadow_pruning_evidence(sidecar, as_of_date="2026-03-31")

    assert report["matured_observation_count"] == 20
    assert report["status"] == "pending_pruning_metrics"
    assert report["pruning_review_inputs"] == []
    assert report["pending_pruning_slices"] == [
        {
            "slice_id": "alpha:0",
            "matured_observation_count": 20,
            "reason": "pruning_metrics_missing_or_invalid",
        }
    ]


def test_read_only_projection_rejects_missing_or_tampered_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(NaturalShadowPruningEvidenceError, match="does not exist"):
        build_natural_shadow_pruning_evidence(missing, as_of_date="2026-01-01")
    assert not missing.exists()

    sidecar = tmp_path / "tampered.sqlite"
    observation = _observation(date(2026, 1, 1))
    _write_sidecar(sidecar, [observation], [_outcome(observation)])
    with sqlite3.connect(sidecar) as connection:
        payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM shadow_observations LIMIT 1"
            ).fetchone()[0]
        )
        payload["lanes"][0]["alpha_bp"] = 1000
        connection.execute(
            "UPDATE shadow_observations SET payload_json = ?",
            (_canonical(payload),),
        )
    with pytest.raises(NaturalShadowPruningEvidenceError, match="does not match payload"):
        build_natural_shadow_pruning_evidence(sidecar, as_of_date="2026-01-02")


def test_as_of_selects_revision_available_by_cutoff(tmp_path: Path) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    first = _observation(
        date(2026, 4, 1),
        revision=1,
        emitted_at="2026-04-01T09:00:00+08:00",
    )
    later = _observation(
        date(2026, 4, 1),
        revision=2,
        emitted_at="2026-04-07T09:00:00+08:00",
    )
    _write_sidecar(sidecar, [first, later], [_outcome(first)])

    report = build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-04-06",
        expected_model_hash=MODEL_HASH,
        expected_dataset_identity_hash=DATASET_HASH,
        expected_policy_hash=POLICY_HASH,
    )

    assert report["matured_observation_hashes"] == [first["record_hash"]]
    assert report["pending_observation_count"] == 0


def test_mixed_frozen_identities_cannot_pool_maturity(tmp_path: Path) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    second_model = "sha256:" + "4" * 64
    observations = [
        _observation(
            date(2026, 5, 1) + timedelta(days=index),
            model_hash=MODEL_HASH if index < 10 else second_model,
        )
        for index in range(20)
    ]
    _write_sidecar(
        sidecar,
        observations,
        [
            _outcome(observation, worthwhile=index % 2 == 0)
            for index, observation in enumerate(observations)
        ],
    )

    report = build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-05-31",
        expected_dataset_identity_hash=DATASET_HASH,
    )

    assert report["status"] == "pending_maturity"
    assert report["matured_observation_count"] == 0
    assert report["pending_observation_count"] == 20
    pending = cast(list[Mapping[str, object]], report["pending_observations"])
    assert all(
        "source_identity_cohort_mixed" in cast(list[str], item["reasons"])
        for item in pending
    )


def test_matured_observation_without_lanes_stays_pruning_pending(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    observations = [
        _observation(
            date(2026, 6, 1) + timedelta(days=index),
            lanes=False,
        )
        for index in range(20)
    ]
    _write_sidecar(
        sidecar,
        observations,
        [
            _outcome(observation, worthwhile=index % 2 == 0)
            for index, observation in enumerate(observations)
        ],
    )

    report = build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-06-30",
        expected_model_hash=MODEL_HASH,
        expected_dataset_identity_hash=DATASET_HASH,
        expected_policy_hash=POLICY_HASH,
    )

    assert report["maturity_blockers"] == []
    assert report["status"] == "pending_pruning_metrics"
    assert report["pruning_review_inputs"] == []
    pending_slices = cast(list[Mapping[str, object]], report["pending_pruning_slices"])
    assert len(pending_slices) == 20
    assert all(
        item["reason"] == "pruning_lanes_missing_or_invalid"
        for item in pending_slices
    )


def test_as_of_uses_absolute_instant_with_taipei_day_boundary(tmp_path: Path) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    utc_observation = _observation(
        date(2026, 8, 1),
        emitted_at="2026-08-01T00:00:00Z",
    )
    offset_observation = _observation(
        date(2026, 8, 2),
        emitted_at="2026-08-02T08:00:00+08:00",
    )
    _write_sidecar(
        sidecar,
        [utc_observation, offset_observation],
        [_outcome(utc_observation), _outcome(offset_observation)],
    )

    report = build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-08-02",
        expected_model_hash=MODEL_HASH,
        expected_dataset_identity_hash=DATASET_HASH,
        expected_policy_hash=POLICY_HASH,
    )

    assert report["matured_observation_count"] == 2
    assert report["pending_observation_count"] == 0


def test_taipei_midnight_late_observation_is_pending_at_prior_as_of_date(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    observation = _observation(
        date(2026, 8, 2),
        emitted_at="2026-08-02T16:00:00Z",
    )
    _write_sidecar(sidecar, [observation], [_outcome(observation)])

    report = build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-08-02",
        expected_model_hash=MODEL_HASH,
        expected_dataset_identity_hash=DATASET_HASH,
        expected_policy_hash=POLICY_HASH,
    )

    assert report["matured_observation_count"] == 0
    pending = cast(list[Mapping[str, object]], report["pending_observations"])
    assert "observation_not_available_at_as_of_date" in cast(
        list[str], pending[0]["reasons"]
    )


def test_later_available_clock_wins_over_earlier_emitted_clock(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    observation = _observation(
        date(2026, 8, 4),
        emitted_at="2026-08-04T09:00:00+08:00",
        available_at="2026-08-05T00:00:00+08:00",
    )
    _write_sidecar(sidecar, [observation], [_outcome(observation)])

    report = build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-08-04",
        expected_model_hash=MODEL_HASH,
        expected_dataset_identity_hash=DATASET_HASH,
        expected_policy_hash=POLICY_HASH,
    )

    assert report["matured_observation_count"] == 0
    pending = cast(list[Mapping[str, object]], report["pending_observations"])
    assert "observation_not_available_at_as_of_date" in cast(
        list[str], pending[0]["reasons"]
    )


def test_public_evidence_cli_replays_create_only_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sidecar = tmp_path / "shadow.sqlite"
    observation = _observation(date(2026, 7, 1), credit=False)
    _write_sidecar(sidecar, [observation], [_outcome(observation)])
    output = tmp_path / "evidence.json"
    args = [
        "--shadow-sidecar",
        str(sidecar),
        "--as-of-date",
        "2026-07-02",
        "--output",
        str(output),
    ]

    assert evidence_cli(args) == 0
    first_stdout = json.loads(capsys.readouterr().out)
    assert first_stdout["status"] == "pending_maturity"
    assert first_stdout["pruning_boundary"]["apply_action"] is False
    assert json.loads(output.read_text(encoding="utf-8")) == first_stdout

    assert evidence_cli(args) == 0
    second_stdout = json.loads(capsys.readouterr().out)
    assert second_stdout == first_stdout
