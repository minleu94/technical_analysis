from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from scripts.scheduled import run_ml_direct_chain_maintenance as runner


def _write_publication(output_root: Path) -> Path:
    publication_root = output_root / "ml_pit_year_shards"
    publication_dir = publication_root / "runs" / "pit-bootstrap"
    dataset_dir = publication_dir / "all_field_enriched"
    dataset_dir.mkdir(parents=True)
    dataset = {
        "schema_version": "ml-pit-year-shard-dataset.v1",
        "stage": "raw_pit_observations",
        "format": "gzip_jsonl",
        "dataset_id": "all_field_enriched",
        "decision_at": "2026-08-12T08:30:00+08:00",
        "history_start_date": "2014-01-01",
        "features": [],
        "safety": {
            "formal_dataset": True,
            "unreviewed_included": False,
            "excluded_leakage_included": False,
            "research_shadow_isolated": True,
            "raw_float_persistence_allowed": False,
        },
    }
    dataset["manifest_hash"] = dataset_assembler._sha256_json(dataset)
    dataset_path = dataset_dir / "manifest.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    publication = {
        "schema_version": "ml-pit-year-shards.v1",
        "stage": "raw_pit_observations",
        "publication_id": "pit-bootstrap",
        "decision_at": dataset["decision_at"],
        "history_start_date": dataset["history_start_date"],
        "scope": {"all_universe": True},
        "datasets": {
            "all_field_enriched": {
                "manifest_path": "all_field_enriched/manifest.json",
                "manifest_hash": dataset["manifest_hash"],
            }
        },
    }
    publication["manifest_hash"] = runner.maintenance._canonical_sha256(
        publication
    )
    publication_path = publication_dir / "manifest.json"
    publication_path.write_text(json.dumps(publication), encoding="utf-8")
    pointer_root = publication_root
    pointer_root.mkdir(parents=True, exist_ok=True)
    (pointer_root / "latest_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "ml-pit-year-shards-pointer.v1",
                "publication_id": "pit-bootstrap",
                "manifest_path": "runs/pit-bootstrap/manifest.json",
                "manifest_hash": publication["manifest_hash"],
            }
        ),
        encoding="utf-8",
    )
    return dataset_path


def test_resolve_latest_raw_dataset_requires_pointer_bound_all_universe(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    dataset_path = _write_publication(output_root)

    resolved, training_as_of = runner.resolve_latest_raw_dataset(output_root)

    assert resolved == dataset_path.resolve()
    assert training_as_of == "2026-08-12T08:30:00+08:00"


def test_resolve_latest_raw_dataset_rejects_non_all_universe_scope(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_publication(output_root)
    publication_path = (
        output_root
        / "ml_pit_year_shards"
        / "runs"
        / "pit-bootstrap"
        / "manifest.json"
    )
    publication = json.loads(publication_path.read_text(encoding="utf-8"))
    publication["scope"] = {"all_universe": False}
    logical = dict(publication)
    logical.pop("manifest_hash", None)
    publication["manifest_hash"] = runner.maintenance._canonical_sha256(logical)
    publication_path.write_text(json.dumps(publication), encoding="utf-8")
    pointer_path = (
        output_root / "ml_pit_year_shards" / "latest_manifest.json"
    )
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["manifest_hash"] = publication["manifest_hash"]
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    try:
        runner.resolve_latest_raw_dataset(output_root)
    except ValueError as exc:
        assert "all-universe" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("non-all-universe publication must be rejected")


def test_live_maintenance_owner_requires_matching_process_custody(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    training = tmp_path / "training"
    training.mkdir()
    (training / ".ml_direct_chain_maintenance.lock").write_text(
        "2468\n", encoding="utf-8"
    )

    class _Process:
        def cmdline(self) -> list[str]:
            return [
                "python.exe",
                "scripts/maintain_ml_direct_v3_refresh_chain.py",
                "--training-output-dir",
                str(training),
            ]

    original_process = runner.maintenance.psutil.Process
    monkeypatch.setattr(
        runner.maintenance.psutil,
        "Process",
        lambda pid=None: _Process() if pid is not None else original_process(),
    )

    assert runner._live_maintenance_owner(training) == 2468


def test_maintenance_lock_state_marks_inaccessible_live_owner_unverifiable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    training = tmp_path / "training"
    training.mkdir()
    (training / ".ml_direct_chain_maintenance.lock").write_text(
        "2468\n", encoding="utf-8"
    )

    class _Process:
        def cmdline(self) -> list[str]:
            raise runner.maintenance.psutil.AccessDenied(pid=2468)

    original_process = runner.maintenance.psutil.Process
    monkeypatch.setattr(
        runner.maintenance.psutil,
        "Process",
        lambda pid=None: _Process() if pid is not None else original_process(),
    )

    assert runner._maintenance_lock_state(training) == (
        "owner_lock_unverifiable",
        2468,
    )


def test_run_maintainer_with_heartbeat_refreshes_verified_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = tmp_path / "scheduled" / "latest_status.json"
    training = tmp_path / "training"
    training.mkdir()
    lock_states = iter(
        [
            ("verified", 2468),
            ("missing_or_invalid", None),
        ]
    )

    class _Process:
        def __init__(self) -> None:
            self.poll_count = 0

        def poll(self) -> int | None:
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

    process = _Process()
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda _command, cwd: process,
    )
    monkeypatch.setattr(
        runner,
        "_maintenance_lock_state",
        lambda _training: next(lock_states),
    )
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    return_code = runner._run_maintainer_with_heartbeat(
        ["python.exe", "maintainer.py"],
        status_path=status_path,
        running_status={"status": "running", "formal_oos_allowed": False},
        training_output_dir=training,
        poll_seconds=30,
    )

    assert return_code == 0
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "running"
    assert status["maintenance_lock_state"] == "verified"
    assert status["maintenance_owner_process_id"] == 2468
    assert isinstance(status["heartbeat_at"], str)
