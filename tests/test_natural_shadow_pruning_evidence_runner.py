from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from ml_module import natural_shadow_pruning_evidence as natural_evidence
from scripts import run_daily_ml_allocation_orchestration as orchestration
from scripts import natural_shadow_pruning_evidence_runner as runner
from scripts.natural_shadow_pruning_evidence_runner import (
    run_natural_shadow_pruning_evidence,
)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _write_pending_sidecar(path: Path) -> None:
    observation_body: dict[str, object] = {
        "schema_version": "ml-allocation-shadow-observation.v1",
        "decision_date": "2026-09-08",
        "custody_hash": _hash({"custody": "runner-test"}),
        "revision": 1,
        "emitted_at": "2026-09-08T09:00:00+08:00",
        "promotion_day_credit_allowed": False,
        "replayed": False,
        "backfilled": False,
        "synthetic_outcomes_used": False,
        "custody": {
            "model_hash": "sha256:" + "1" * 64,
            "dataset_identity_hash": "sha256:" + "2" * 64,
            "policy_hash": "sha256:" + "3" * 64,
        },
        "lanes": [
            {
                "slice_id": "alpha:0",
                "alpha_bp": 0,
                "lane_metrics": None,
            }
        ],
    }
    observation = {
        **observation_body,
        "record_hash": _hash(observation_body),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE shadow_observations (
                record_hash TEXT PRIMARY KEY,
                decision_date TEXT NOT NULL,
                custody_hash TEXT NOT NULL,
                revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE (decision_date, custody_hash),
                UNIQUE (decision_date, revision)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE shadow_outcomes (
                record_hash TEXT PRIMARY KEY,
                observation_hash TEXT NOT NULL,
                custody_hash TEXT NOT NULL,
                revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE (observation_hash, custody_hash),
                UNIQUE (observation_hash, revision)
            )
            """
        )
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


def test_missing_sidecar_is_normal_pending_and_daily_weekly_status_is_immutable(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "missing" / "shadow_evidence.sqlite"
    result = run_natural_shadow_pruning_evidence(
        sidecar_database_path=sidecar,
        output_root=tmp_path / "run",
        as_of_date=date(2026, 9, 8),
    )

    assert result["status"] == "pending"
    assert result["integrity_state"] == "awaiting_source"
    assert result["pending_is_normal_wait"] is True
    assert result["exit_code"] == 0
    assert result["evidence_path"] is None
    assert result["pruning_action_performed"] is False
    assert result["promotion_action_performed"] is False
    daily_status = Path(str(result["daily_status_path"]))
    weekly_status = Path(str(result["weekly_status_path"]))
    assert daily_status.is_file()
    assert weekly_status.is_file()
    assert json.loads(daily_status.read_text(encoding="utf-8"))["status_hash"] == (
        result["status_hash"]
    )

    replay = run_natural_shadow_pruning_evidence(
        sidecar_database_path=sidecar,
        output_root=tmp_path / "run",
        as_of_date=date(2026, 9, 8),
    )
    assert replay["status_hash"] == result["status_hash"]
    assert replay["daily_status_write"] == "idempotent"
    assert replay["weekly_status_write"] == "idempotent"


def test_real_sidecar_projection_writes_hash_bound_daily_and_weekly_evidence(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "collector" / "shadow_evidence.sqlite"
    _write_pending_sidecar(sidecar)
    result = run_natural_shadow_pruning_evidence(
        sidecar_database_path=sidecar,
        output_root=tmp_path / "run",
        as_of_date="2026-09-08",
    )

    assert result["status"] == "pending"
    assert result["evidence_status"] == "pending_maturity"
    assert result["integrity_state"] == "verified"
    assert result["exit_code"] == 0
    evidence_path = Path(str(result["evidence_path"]))
    weekly_path = Path(str(result["weekly_evidence_path"]))
    assert evidence_path.is_file()
    assert weekly_path.is_file()
    assert evidence_path.read_bytes() == weekly_path.read_bytes()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["evidence_hash"] == result["evidence_hash"]
    assert result["daily_evidence_write"] == "inserted"
    assert result["weekly_evidence_write"] == "inserted"
    assert result["pruning_boundary"]["apply_action"] is False
    assert result["pruning_boundary"]["promotion_eligible"] is False

    replay = run_natural_shadow_pruning_evidence(
        sidecar_database_path=sidecar,
        output_root=tmp_path / "run",
        as_of_date="2026-09-08",
    )
    assert replay["evidence_hash"] == result["evidence_hash"]
    assert replay["daily_evidence_write"] == "idempotent"
    assert replay["weekly_evidence_write"] == "idempotent"


def test_invalid_sidecar_is_degraded_and_does_not_become_pending(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "collector" / "shadow_evidence.sqlite"
    _write_pending_sidecar(sidecar)
    with sqlite3.connect(sidecar) as connection:
        connection.execute(
            "UPDATE shadow_observations SET payload_json = ?",
            ("{}",),
        )

    result = run_natural_shadow_pruning_evidence(
        sidecar_database_path=sidecar,
        output_root=tmp_path / "run",
        as_of_date="2026-09-08",
    )

    assert result["status"] == "blocked_integrity"
    assert result["integrity_state"] == "failed"
    assert result["pending_is_normal_wait"] is False
    assert result["exit_code"] == 2
    assert result["evidence_path"] is None
    assert result["pruning_action_performed"] is False
    assert result["promotion_action_performed"] is False


def test_status_publication_stages_complete_bytes_before_atomic_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "status.json"

    def fail_fsync(_file_descriptor: int) -> None:
        raise OSError("simulated crash during fsync")

    monkeypatch.setattr(runner.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated crash"):
        runner._create_only_bytes(target, b"complete-status")

    assert not target.exists()
    assert not list(tmp_path.glob(".*.tmp"))

    monkeypatch.undo()
    assert runner._create_only_bytes(target, b"complete-status") == "inserted"
    assert runner._create_only_bytes(target, b"complete-status") == "idempotent"
    with pytest.raises(runner.NaturalShadowPruningScheduleError, match="conflict"):
        runner._create_only_bytes(target, b"different-status")


def test_evidence_writer_crash_does_not_leave_partial_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sidecar = tmp_path / "collector" / "shadow_evidence.sqlite"
    _write_pending_sidecar(sidecar)
    evidence = natural_evidence.build_natural_shadow_pruning_evidence(
        sidecar,
        as_of_date="2026-09-08",
    )
    target = tmp_path / "evidence" / "projection.json"
    target.parent.mkdir()

    def fail_fsync(_file_descriptor: int) -> None:
        raise OSError("simulated evidence crash during fsync")

    monkeypatch.setattr(natural_evidence.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated evidence crash"):
        natural_evidence.write_natural_shadow_pruning_evidence(target, evidence)

    assert not target.exists()
    assert not list(target.parent.glob(".*.tmp"))

    monkeypatch.undo()
    assert natural_evidence.write_natural_shadow_pruning_evidence(
        target,
        evidence,
    ) == "inserted"
    assert natural_evidence.write_natural_shadow_pruning_evidence(
        target,
        evidence,
    ) == "idempotent"


def test_orchestration_common_status_exit_binds_pruning_result_and_exit_code(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "scheduled" / "ml_allocation_copilot"
    status = {
        "schema_version": "fixture",
        "status": "passed_rule_only",
        "decision_at": "2026-09-08T08:30:00+08:00",
        "failed_reasons": [],
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "writes_source_database": False,
    }
    result = orchestration._write_status(run_root, status)

    pruning = result["natural_shadow_pruning_evidence"]
    assert isinstance(pruning, dict)
    assert pruning["status"] == "pending"
    assert pruning["exit_code"] == 0
    assert result["natural_shadow_pruning_evidence_exit_code"] == 0
    assert result["status"] == "passed_rule_only"
    assert json.loads(
        (run_root / "latest_status.json").read_text(encoding="utf-8")
    )["natural_shadow_pruning_evidence_exit_code"] == 0
