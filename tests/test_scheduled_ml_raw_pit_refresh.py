from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from data_module.ml_daily_price_source_quality import DailyPriceSourceQualityError
from data_module.ml_storage_capacity import (
    SCHEDULED_REQUIRED_FREE_BYTES,
    SCHEDULED_SAFETY_RESERVE_BYTES,
)
from scripts import build_ml_pit_year_shards as pit_builder
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


def test_extract_source_quality_summary_keeps_only_bounded_builder_payload() -> None:
    summary = {
        "candidate_count": 4_476_508,
        "classification_counts": {
            "canonical_daily_row_missing": 1,
            "sqlite_row_mismatch_against_canonical_daily_csv": 1,
        },
        "samples": [{"symbol": "2330", "date": "2026-09-08"}],
    }

    extracted = runner._extract_source_quality_summary(
        "diagnostic line\n"
        + json.dumps(
            {
                "status": "blocked",
                "source_quality_summary": summary,
                "candidates": ["the full report is never emitted"],
            }
        )
    )

    assert extracted == summary


def test_builder_quality_summary_bounds_candidates_and_keeps_report_hash() -> None:
    report = {
        "schema_version": "quality.v1",
        "status": "quarantine_required",
        "read_only": True,
        "repair_performed": False,
        "formal_training_allowed": False,
        "candidate_count": 4_476_508,
        "classification_counts": {
            "canonical_daily_row_missing": 4_476_507,
            "sqlite_row_mismatch_against_canonical_daily_csv": 1,
        },
        "affected_date_counts": {
            "2026-09-07": 4_476_507,
            "2026-09-08": 1,
        },
        "report_hash": "sha256:" + "a" * 64,
        "candidates": [
            {
                "symbol": "2330",
                "date": "2026-09-07",
                "classification": "canonical_daily_row_missing",
                "differing_fields": ["open"],
                "detector": {
                    "previous_close": "100",
                    "current_open": "10",
                    "next_open": None,
                    "threshold_factor": "10",
                    "policy_version": "guard.v1",
                    "future_source_row_used": False,
                },
                "canonical_file": {
                    "path": "D:/daily_price/20260907.csv",
                    "status": "missing",
                    "file_sha256": None,
                },
                "canonical_candidates": [
                    {
                        "row": {},
                        "file": {
                            "path": "D:/daily_price_tpex/20260907.csv",
                            "status": "valid",
                            "file_sha256": "sha256:" + "c" * 64,
                            "market": "TPEX",
                            "source_directory": "D:/daily_price_tpex",
                        },
                    }
                ],
            }
        ],
    }

    summary = pit_builder._compact_source_quality_summary(report)

    assert summary["candidate_count"] == 4_476_508
    assert summary["classification_counts"] == report["classification_counts"]
    assert summary["affected_date_count"] == 2
    samples = summary["samples"]
    assert isinstance(samples, list)
    assert len(samples) == 1
    assert summary["report_hash"] == report["report_hash"]
    assert "candidates" not in summary
    assert summary["samples"][0]["canonical_candidates"][0]["market"] == "TPEX"


def test_builder_cli_emits_compact_quality_summary_on_guard_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = {
        "schema_version": "quality.v1",
        "status": "quarantine_required",
        "read_only": True,
        "repair_performed": False,
        "formal_training_allowed": False,
        "candidate_count": 2,
        "classification_counts": {"canonical_daily_row_missing": 2},
        "affected_date_counts": {"2026-08-12": 2},
        "report_hash": "sha256:" + "b" * 64,
        "candidates": [
            {
                "symbol": "2330",
                "date": "2026-08-12",
                "classification": "canonical_daily_row_missing",
            }
        ],
    }

    def raise_quality_error(*_args: object, **_kwargs: object) -> object:
        raise DailyPriceSourceQualityError(
            "daily price source quality quarantine required: 2 candidate rows",
            report=report,
        )

    monkeypatch.setattr(pit_builder.PITYearShardExporter, "build", raise_quality_error)
    database = tmp_path / "source.db"
    database.write_bytes(b"sqlite-placeholder")

    exit_code = pit_builder.main(
        [
            "--database",
            str(database),
            "--output-dir",
            str(tmp_path / "out"),
            "--decision-at",
            "2026-08-12T08:30:00+08:00",
            "--symbols",
            "2330",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["error_type"] == "DailyPriceSourceQualityError"
    assert payload["source_quality_summary"]["candidate_count"] == 2
    assert "candidates" not in payload["source_quality_summary"]


def test_main_persists_bounded_source_quality_summary_on_builder_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    _write_freshness_status(output_root)
    database = data_root / "sqlite" / "twstock.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    database.write_bytes(b"sqlite-placeholder")
    monkeypatch.setattr(
        runner,
        "_taipei_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=_TAIPEI),
    )
    monkeypatch.setattr(
        runner.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=700 * 1024**3,
            used=100 * 1024**3,
            free=600 * 1024**3,
        ),
    )
    monkeypatch.setattr(runner, "_direct_chain_instance_lock_present", lambda _root: False)

    class _FakeLock:
        owner_pid = 424_242

        def authorize_child(self, _child_pid: int) -> None:
            return None

    fake_lock = _FakeLock()
    monkeypatch.setattr(runner, "_acquire_lock", lambda _path: fake_lock)
    monkeypatch.setattr(runner, "_release_lock", lambda _lock: None)
    monkeypatch.setattr(
        runner,
        "build_heavy_chain_reservation_handoff_environment",
        lambda _lock, *, environment, parent_pid: environment,
    )
    summary = {
        "candidate_count": 4_476_508,
        "classification_counts": {
            "canonical_daily_row_missing": 6_488,
            "sqlite_row_mismatch_against_canonical_daily_csv": 990,
        },
        "samples": [{"symbol": "2330", "classification": "test"}],
    }

    class _FakeBuilderProcess:
        pid = 424_243
        returncode = 2

        def communicate(self) -> tuple[str, str]:
            return (
                json.dumps(
                    {
                        "status": "blocked",
                        "error_type": "DailyPriceSourceQualityError",
                        "source_quality_summary": summary,
                    }
                ),
                "",
            )

    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *_args, **_kwargs: _FakeBuilderProcess(),
    )

    exit_code = runner.main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--database",
            str(database),
        ]
    )

    receipt = json.loads(
        (
            output_root
            / "scheduled"
            / "ml_raw_pit_refresh"
            / "latest_status.json"
        ).read_text(encoding="utf-8")
    )
    assert exit_code == 1
    assert receipt["status"] == "failed"
    assert receipt["builder_returncode"] == 2
    assert receipt["source_quality_summary"] == summary


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
    monkeypatch.setattr(
        runner.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=SCHEDULED_REQUIRED_FREE_BYTES + 10_000,
            used=10_000,
            free=SCHEDULED_REQUIRED_FREE_BYTES + 1_000,
        ),
    )
    observed: dict[str, object] = {}

    class _FakeBuilderProcess:
        pid = 999_991
        returncode = 0

        def communicate(self) -> tuple[str, str]:
            return "builder ok", ""

    def fake_popen(command: list[str], **kwargs: object) -> _FakeBuilderProcess:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return _FakeBuilderProcess()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)

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
    source_flags = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--daily-price-source-dir"
    ]
    assert source_flags == [
        str((data_root / "daily_price").resolve()),
        str((data_root / "daily_price_tpex").resolve()),
    ]
    assert refresh_payload["daily_price_source_dirs"] == source_flags
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


def test_main_blocks_before_builder_when_storage_is_below_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    _write_freshness_status(output_root)
    monkeypatch.setattr(
        runner,
        "_taipei_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=_TAIPEI),
    )
    monkeypatch.setattr(
        runner.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=100, used=95, free=5),
    )
    builder_called = False

    def fail_builder(*_args: object, **_kwargs: object) -> None:
        nonlocal builder_called
        builder_called = True
        raise AssertionError("builder must not run without filesystem headroom")

    monkeypatch.setattr(runner.subprocess, "run", fail_builder)

    exit_code = runner.main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
                "--minimum-free-space-bytes",
                str(SCHEDULED_SAFETY_RESERVE_BYTES),
        ]
    )

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
    assert refresh_payload["status"] == "blocked_insufficient_storage"
    assert refresh_payload["storage_preflight"]["free_bytes"] == 5
    assert refresh_payload["storage_preflight"]["minimum_free_space_bytes"] == (
        SCHEDULED_SAFETY_RESERVE_BYTES
    )


def test_main_records_locked_without_starting_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    status_path = output_root / "scheduled" / "ml_raw_pit_refresh" / "latest_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({"status": "running", "process_id": 999}), encoding="utf-8")
    _write_freshness_status(output_root)
    monkeypatch.setattr(runner, "_acquire_lock", lambda _path: None)
    monkeypatch.setattr(
        runner,
        "_storage_preflight",
        lambda _path, minimum_free_space_bytes: {
            "total_bytes": 400 * 1024**3,
            "used_bytes": 0,
            "free_bytes": 300 * 1024**3,
            "minimum_free_space_bytes": minimum_free_space_bytes,
            "within_minimum_free_space": True,
        },
    )

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


def test_raw_direct_custody_guard_blocks_live_owner_and_allows_stale_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = tmp_path / "release_v4"
    states = iter([("verified", 2468), ("stale", 2468)])
    monkeypatch.setattr(
        runner.direct_chain_runner,
        "_maintenance_lock_state",
        lambda _training: next(states),
    )
    monkeypatch.setattr(
        runner.direct_chain_runner.maintenance,
        "_target_processes",
        lambda _root: [],
    )

    assert runner._direct_chain_instance_lock_present(release_root) is True
    assert runner._direct_chain_instance_lock_present(release_root) is False


def test_raw_direct_custody_guard_blocks_live_continuation_after_owner_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = tmp_path / "release_v4"
    monkeypatch.setattr(
        runner.direct_chain_runner.maintenance,
        "_target_processes",
        lambda _root: [(8642, "continue_ml_direct_v3_refresh_chain.py")],
    )
    monkeypatch.setattr(
        runner.direct_chain_runner,
        "_maintenance_lock_state",
        lambda _training: (_ for _ in ()).throw(
            AssertionError("live continuation should be sufficient custody")
        ),
    )

    assert runner._direct_chain_instance_lock_present(release_root) is True
