from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from scripts.scheduled import run_ml_raw_pit_refresh as runner


_TAIPEI = ZoneInfo("Asia/Taipei")


def _write_freshness_status(
    output_root: Path,
    *,
    status: str = "passed",
    daily_date: str = "2026-08-12",
    technical_date: str = "2026-08-12",
    completed_at: str = "2026-08-12T07:00:00+08:00",
) -> Path:
    status_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(
            {
                "status": status,
                "completed_at": completed_at,
                "steps": [
                    {
                        "name": "check_overview_after",
                        "result": {
                            "daily_data": {"latest_date": daily_date},
                            "technical_indicators": {
                                "latest_date": technical_date
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return status_path


def _write_raw_publication(
    raw_root: Path,
    *,
    decision_at: str = "2026-08-12T08:30:00+08:00",
) -> Path:
    publication_dir = raw_root / "runs" / "pit-test"
    dataset_dir = publication_dir / "all_field_enriched"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    dataset = {
        "schema_version": "ml-pit-year-shard-dataset.v1",
        "stage": "raw_pit_observations",
        "format": "gzip_jsonl",
        "dataset_id": "all_field_enriched",
        "decision_at": decision_at,
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
        "publication_id": "pit-test",
        "decision_at": decision_at,
        "history_start_date": "2014-01-01",
        "scope": {"all_universe": True},
        "datasets": {
            "all_field_enriched": {
                "manifest_path": "all_field_enriched/manifest.json",
                "manifest_hash": dataset["manifest_hash"],
            }
        },
    }
    publication["manifest_hash"] = runner._canonical_sha256(publication)
    publication_path = publication_dir / "manifest.json"
    publication_path.write_text(json.dumps(publication), encoding="utf-8")

    pointer_path = raw_root / "latest_manifest.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(
        json.dumps(
            {
                "schema_version": "ml-pit-year-shards-pointer.v1",
                "publication_id": "pit-test",
                "manifest_path": "runs/pit-test/manifest.json",
                "manifest_hash": publication["manifest_hash"],
            }
        ),
        encoding="utf-8",
    )
    return publication_path


def test_core_freshness_proof_requires_current_core_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "output"
    status_path = _write_freshness_status(output_root)
    monkeypatch.setattr(
        runner,
        "_taipei_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=_TAIPEI),
    )

    proof = runner._core_freshness_proof(status_path)

    assert proof.latest_core_date.isoformat() == "2026-08-12"
    assert proof.decision_at == "2026-08-12T08:30:00+08:00"
    assert proof.data_update_status == "passed"


def test_core_freshness_proof_blocks_lagging_technical_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status_path = _write_freshness_status(
        tmp_path / "output",
        technical_date="2026-08-11",
    )
    monkeypatch.setattr(
        runner,
        "_taipei_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=_TAIPEI),
    )

    with pytest.raises(runner._UpstreamNotReady, match="technical_indicators_lagging"):
        runner._core_freshness_proof(status_path)


def test_latest_raw_publication_is_pointer_and_safety_bound(tmp_path: Path) -> None:
    raw_root = tmp_path / "ml_pit_year_shards"
    publication_path = _write_raw_publication(raw_root)

    publication = runner._latest_raw_publication(raw_root)

    assert publication is not None
    assert publication.publication_id == "pit-test"
    assert publication.publication_manifest_path == publication_path.resolve()
    assert publication.dataset_manifest_hash.startswith("sha256:")


def test_refresh_needed_when_same_cutoff_was_published_before_update(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "ml_pit_year_shards"
    publication_path = _write_raw_publication(raw_root)
    os.utime(
        publication_path,
        (
            datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc).timestamp(),
            datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc).timestamp(),
        ),
    )
    current = runner._latest_raw_publication(raw_root)
    assert current is not None
    proof = runner._CoreFreshnessProof(
        latest_core_date=datetime(2026, 8, 12, tzinfo=_TAIPEI).date(),
        decision_at="2026-08-12T08:30:00+08:00",
        completed_at=datetime(2026, 8, 12, 15, 0, tzinfo=_TAIPEI),
        data_update_status="passed",
    )

    assert runner._refresh_needed(current, proof) is True

    newer_mtime = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc).timestamp()
    os.utime(publication_path, (newer_mtime, newer_mtime))
    current = runner._latest_raw_publication(raw_root)
    assert current is not None
    assert runner._refresh_needed(current, proof) is False


def test_main_skips_when_current_publication_is_new_enough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    status_path = _write_freshness_status(output_root)
    raw_root = output_root / "release_v4" / "ml_pit_year_shards"
    publication_path = _write_raw_publication(raw_root)
    mtime = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc).timestamp()
    os.utime(publication_path, (mtime, mtime))
    monkeypatch.setattr(
        runner,
        "_taipei_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=_TAIPEI),
    )
    builder_called = False

    def fail_builder(*_args: object, **_kwargs: object) -> None:
        nonlocal builder_called
        builder_called = True
        raise AssertionError("builder must not run for current publication")

    monkeypatch.setattr(runner.subprocess, "run", fail_builder)

    exit_code = runner.main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--status-path",
            str(output_root / "scheduled" / "ml_raw_pit_refresh" / "latest_status.json"),
        ]
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    refresh_payload = json.loads(
        (
            output_root
            / "scheduled"
            / "ml_raw_pit_refresh"
            / "latest_status.json"
        ).read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert builder_called is False
    assert payload["status"] == "passed"
    assert refresh_payload["status"] == "skipped_current"


def test_main_runs_builder_and_validates_new_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    status_path = _write_freshness_status(output_root)
    database = data_root / "sqlite" / "twstock.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    database.write_bytes(b"sqlite-placeholder")
    raw_root = output_root / "release_v4" / "ml_pit_year_shards"
    publication_path = _write_raw_publication(raw_root)
    published = runner._latest_raw_publication(raw_root)
    assert published is not None
    publication_path.unlink()
    current_results = iter((None, published))
    monkeypatch.setattr(runner, "_latest_raw_publication", lambda _root: next(current_results))
    monkeypatch.setattr(
        runner,
        "_taipei_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=_TAIPEI),
    )
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="builder ok", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    exit_code = runner.main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--database",
            str(database),
            "--batch-size",
            "1024",
        ]
    )

    refresh_path = output_root / "scheduled" / "ml_raw_pit_refresh" / "latest_status.json"
    refresh_payload = json.loads(refresh_path.read_text(encoding="utf-8"))
    command = observed["command"]
    assert isinstance(command, list)
    assert exit_code == 0
    assert refresh_payload["status"] == "completed"
    assert "--all-universe" in command
    assert command[command.index("--decision-at") + 1] == "2026-08-12T08:30:00+08:00"
    assert command[command.index("--database") + 1] == str(database.resolve())
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "passed"


def test_main_records_upstream_block_without_running_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    _write_freshness_status(output_root, status="running")
    monkeypatch.setattr(
        runner,
        "_taipei_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=_TAIPEI),
    )

    exit_code = runner.main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
        ]
    )

    payload = json.loads(
        (
            output_root
            / "scheduled"
            / "ml_raw_pit_refresh"
            / "latest_status.json"
        ).read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert payload["status"] == "blocked_upstream_not_ready"


def test_main_records_locked_without_starting_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    status_path = output_root / "scheduled" / "ml_raw_pit_refresh" / "latest_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({"status": "running", "process_id": 999}), encoding="utf-8")
    monkeypatch.setattr(runner, "_acquire_lock", lambda _path: None)

    exit_code = runner.main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--status-path",
            str(status_path),
        ]
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "skipped_locked"
    assert payload["reason"] == "another_raw_pit_refresh_is_running"
