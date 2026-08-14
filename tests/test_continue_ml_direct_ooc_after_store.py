from __future__ import annotations

import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

import scripts.continue_ml_direct_ooc_after_store as continuation


def test_main_publishes_live_waiting_status_before_store_wait(
    tmp_path: Path, monkeypatch
) -> None:
    store_output_dir = tmp_path / "store"
    training_output_dir = tmp_path / "training"
    store_output_dir.mkdir()
    training_output_dir.mkdir()
    observed: dict[str, object] = {}
    status_path = training_output_dir / "continuation_status.json"

    def fake_wait(**_: object) -> None:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        observed.update(payload)
        raise RuntimeError("test_wait_boundary")

    monkeypatch.setattr(
        continuation,
        "_wait_for_expected_process",
        fake_wait,
    )

    result = continuation.main(
        [
            "--direct-process-id",
            "123",
            "--store-output-dir",
            str(store_output_dir),
            "--training-output-dir",
            str(training_output_dir),
        ]
    )

    assert result == 2
    assert observed == {
        "status": "waiting_for_direct_store",
        "direct_process_id": 123,
        "store_output_dir": str(store_output_dir.resolve()),
        "training_output_dir": str(training_output_dir.resolve()),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    terminal_payload = json.loads(
        status_path.read_text(encoding="utf-8")
    )
    assert terminal_payload["status"] == "blocked"
    assert terminal_payload["message"] == "test_wait_boundary"


def test_main_publishes_store_custody_validation_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_output_dir = tmp_path / "store"
    training_output_dir = tmp_path / "training"
    store_output_dir.mkdir()
    training_output_dir.mkdir()
    status_path = training_output_dir / "continuation_status.json"
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        continuation,
        "_wait_for_expected_process",
        lambda **_: None,
    )

    def fake_validate(*_args: object, **_kwargs: object) -> object:
        observed.update(json.loads(status_path.read_text(encoding="utf-8")))
        raise RuntimeError("test_validation_boundary")

    monkeypatch.setattr(
        continuation,
        "_validated_store_manifest",
        fake_validate,
    )

    result = continuation.main(
        [
            "--direct-process-id",
            "123",
            "--store-output-dir",
            str(store_output_dir),
            "--training-output-dir",
            str(training_output_dir),
        ]
    )

    assert result == 2
    assert observed["status"] == "store_custody_validation_starting"
    assert observed["formal_oos_allowed"] is False
    assert observed["broker_order_allowed"] is False


def test_latest_direct_heartbeat_is_exposed_only_when_schema_and_run_match(
    tmp_path: Path,
) -> None:
    store_output_dir = tmp_path / "store"
    run_directory = store_output_dir / "runs" / "direct-ooc-test"
    run_directory.mkdir(parents=True)
    heartbeat = {
        "schema_version": "portfolio-ml-direct-heartbeat.v1",
        "run_id": "direct-ooc-test",
        "pid": 123,
        "status": "running",
        "stage": "building_year",
        "current_year": 2019,
        "completed_years": [2014, 2015, 2016, 2017, 2018],
    }
    (run_directory / "heartbeat.json").write_text(
        json.dumps(heartbeat),
        encoding="utf-8",
    )

    assert continuation._latest_direct_heartbeat(store_output_dir) == (
        heartbeat
    )
    assert continuation._latest_direct_heartbeat(
        store_output_dir,
        direct_process_id=123,
    ) == heartbeat
    assert continuation._latest_direct_heartbeat(
        store_output_dir,
        direct_process_id=456,
    ) is None

    child_heartbeat = dict(heartbeat)
    child_heartbeat["pid"] = os.getpid()
    (run_directory / "heartbeat.json").write_text(
        json.dumps(child_heartbeat),
        encoding="utf-8",
    )
    assert continuation._latest_direct_heartbeat(
        store_output_dir,
        direct_process_id=os.getppid(),
    ) == child_heartbeat

    mismatched = dict(heartbeat)
    mismatched["run_id"] = "other-run"
    (run_directory / "heartbeat.json").write_text(
        json.dumps(mismatched),
        encoding="utf-8",
    )
    assert continuation._latest_direct_heartbeat(store_output_dir) is None


def test_ooc_training_publishes_live_heartbeat_until_process_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = tmp_path / "training" / "continuation_status.json"
    training_output_dir = tmp_path / "training"
    training_output_dir.mkdir()
    store_manifest_path = tmp_path / "store" / "manifest.json"
    store_manifest_path.parent.mkdir()
    store_manifest = {"manifest_hash": "sha256:" + "a" * 64}

    class FakeProcess:
        pid = 9876

        def __init__(self) -> None:
            self._poll_values = iter((None, 0))

        def poll(self) -> int | None:
            return next(self._poll_values)

        def terminate(self) -> None:
            raise AssertionError("process should not be terminated")

        def wait(self, **_: object) -> int:
            return 0

    monkeypatch.setattr(
        continuation.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )
    monkeypatch.setattr(continuation.time, "sleep", lambda _: None)

    result = continuation._run_training_with_heartbeat(
        command=["python", "train.py"],
        status_path=status_path,
        training_output_dir=training_output_dir,
        store_manifest_path=store_manifest_path,
        store_manifest=store_manifest,
        poll_seconds=1,
    )

    assert result == 0
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "portfolio-ml-ooc-heartbeat.v1"
    assert payload["status"] == "training_running"
    assert payload["training_process_id"] == 9876
    assert payload["store_manifest_hash"] == store_manifest["manifest_hash"]
    assert payload["formal_oos_allowed"] is False
    assert payload["broker_order_allowed"] is False


def test_atomic_status_write_retries_windows_replace_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "continuation_status.json"
    real_replace = continuation.os.replace
    attempts = {"count": 0}

    def flaky_replace(source: object, target: object) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("test_windows_replace_lock")
        real_replace(source, target)

    monkeypatch.setattr(continuation.os, "replace", flaky_replace)
    monkeypatch.setattr(continuation.time, "sleep", lambda _: None)

    continuation._atomic_write_json(path, {"status": "training_running"})

    assert attempts["count"] == 3
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == (
        "training_running"
    )


def test_process_custody_mismatch_fails_closed() -> None:
    with pytest.raises(
        RuntimeError,
        match="direct process custody mismatch",
    ):
        continuation._assert_expected_process_command(
            "python unrelated_worker.py --output-dir C:\\other",
            "C:\\expected-store",
        )


def test_validated_store_manifest_rejects_stale_latest_pointer(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "store"
    output_root.mkdir()
    (output_root / "latest_manifest.json").write_text(
        json.dumps(
            {
                "manifest_hash": "sha256:" + "1" * 64,
                "manifest_path": "runs/run/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        RuntimeError,
        match="latest pointer was not refreshed",
    ):
        continuation._validated_store_manifest(
            output_root,
            minimum_pointer_mtime_ns=time.time_ns() + 1,
        )


def test_validated_store_manifest_rechecks_year_fold_and_checkpoint_custody(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "store"
    run_directory = output_root / "runs" / "direct-current"
    run_directory.mkdir(parents=True)
    year_manifest_hash = "sha256:" + "2" * 64
    fold_manifest_hash = "sha256:" + "3" * 64
    manifest = {
        "manifest_hash": "sha256:" + "1" * 64,
        "run_id": "direct-current",
        "status": "complete",
        "execution": {
            "direct_numeric_store": True,
            "direct_store_complete": True,
            "memory_budget_enforced": True,
            "within_memory_budget": True,
            "temporary_storage_preflight": {"within_budget": True},
        },
        "formal_source_only": True,
        "research_shadow_included": False,
        "fold_count": 4,
        "row_count": 10,
        "years": [{"year": 2024, "manifest_hash": year_manifest_hash}],
        "folds": [{"fold_id": "fold-1", "manifest_hash": fold_manifest_hash}],
    }
    manifest["manifest_hash"] = continuation.store_module._sha256_json(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    manifest_path = run_directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    year_directory = run_directory / "year=2024"
    year_directory.mkdir()
    (year_directory / "manifest.json").write_text("{}", encoding="utf-8")
    (year_directory / "carry.state.gz").write_bytes(b"carry")
    checkpoint = {
        "complete": True,
        "run_id": "direct-current",
        "manifest_hash": manifest["manifest_hash"],
        "manifest_file_hash": continuation._file_sha256(manifest_path),
        "completed_years": [
            {
                "year": 2024,
                "manifest_hash": year_manifest_hash,
                "manifest_file_hash": continuation._file_sha256(
                    year_directory / "manifest.json"
                ),
                "carry_file_hash": continuation._file_sha256(
                    year_directory / "carry.state.gz"
                ),
            }
        ],
    }
    (run_directory / "checkpoint.json").write_text(
        json.dumps(checkpoint), encoding="utf-8"
    )
    (output_root / "latest_manifest.json").write_text(
        json.dumps(
            {
                "manifest_hash": manifest["manifest_hash"],
                "manifest_path": "runs/direct-current/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        continuation.store_module,
        "_verify_year_directory",
        lambda **_: True,
    )
    monkeypatch.setattr(
        continuation.store_module,
        "_verify_fold_manifest",
        lambda *_args, **_kwargs: True,
    )

    path, result = continuation._validated_store_manifest(output_root)

    assert path == manifest_path
    assert result["run_id"] == "direct-current"

    monkeypatch.setattr(
        continuation.store_module,
        "_verify_year_directory",
        lambda **_: False,
    )
    with pytest.raises(
        RuntimeError,
        match="direct year artifact custody mismatch: 2024",
    ):
        continuation._validate_direct_artifact_custody(
            manifest_path=manifest_path,
            manifest=manifest,
        )


def test_legacy_direct_store_is_refreshed_to_current_builder_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "store"
    output_root.mkdir()
    status_path = tmp_path / "training" / "continuation_status.json"
    manifest = {
        "manifest_hash": "sha256:" + "a" * 64,
        "execution": {
            "temporary_storage_budget_bytes": 123,
        },
        "store_identity": {
            "direct_builder_schema_version": "portfolio-ml-direct-numeric.v3",
            "direct_identity": {
                "schema_version": "portfolio-ml-direct-numeric.v3",
                "raw_manifest_hash": "sha256:" + "b" * 64,
                "raw_manifest_file_hash": "sha256:" + "c" * 64,
                "corporate_action_manifest_file_hash": (
                    "sha256:" + "0" * 64
                ),
                "sector_membership_file_hash": None,
                "training_as_of": "2026-07-30T08:30:00+08:00",
                "benchmark_entity_id": "TAIEX",
                "minimum_train_dates": 252,
                "test_date_count": 63,
                "purge_trading_days": 60,
                "embargo_trading_days": 5,
            },
        },
    }
    discovered_raw = tmp_path / "raw-manifest.json"
    discovered_raw.write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        continuation,
        "_discover_hash_bound_manifest",
        lambda **_: discovered_raw,
    )

    def fake_run(command, **_kwargs):
        # ``platform.uname()`` may call the same subprocess module while
        # importing the direct-store module on Windows.
        if command == "ver":
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "Microsoft Windows [Version 10.0.0]\r\n"
                    if _kwargs.get("text")
                    else b"Microsoft Windows [Version 10.0.0]\r\n"
                ),
            )
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        continuation.subprocess,
        "run",
        fake_run,
    )
    refreshed = {
        "manifest_hash": "sha256:" + "d" * 64,
    }
    monkeypatch.setattr(
        continuation,
        "_validated_store_manifest",
        lambda *_args, **_kwargs: (tmp_path / "v4.json", refreshed),
    )

    path, result = continuation._ensure_current_direct_schema(
        output_root=output_root,
        manifest_path=tmp_path / "legacy.json",
        manifest=manifest,
        status_path=status_path,
        batch_size=8192,
        workers=2,
        memory_budget_mb=4096,
    )

    assert path == tmp_path / "v4.json"
    assert result == refreshed
    assert len(calls) == 1
    assert "build_portfolio_ml_direct_numeric_store.py" in calls[0][1]
    assert "--raw-manifest" in calls[0]
    assert str(discovered_raw) in calls[0]
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "direct_schema_refresh_starting"
    assert status["target_direct_schema"] == "portfolio-ml-direct-numeric.v4"


def _write_sector_sidecar(
    path: Path,
    *,
    source_id: str = "twse:historical-sector-membership",
) -> None:
    row = {
        "symbol": "2330",
        "sector_id": "SEMI",
        "available_at": "2023-12-31T18:00:00+08:00",
        "effective_from": "2024-01-01",
        "effective_to": None,
        "status": "accepted",
        "source_id": source_id,
        "license_id": "twse-open-data-license-v1",
        "source_hash": "sha256:" + "a" * 64,
    }
    rows_hash = continuation.dataset_assembler._sha256_json([row])
    manifest_without_hash = {
        "schema_version": (
            continuation.dataset_assembler.SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION
        ),
        "row_count": 1,
        "rows_hash": rows_hash,
    }
    canonical_hash = continuation.dataset_assembler._sha256_json(
        {
            "sidecar_schema_version": (
                continuation.dataset_assembler.SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION
            ),
            "manifest": manifest_without_hash,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": (
                    continuation.dataset_assembler.SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION
                ),
                "manifest": {
                    **manifest_without_hash,
                    "canonical_hash": canonical_hash,
                },
                "rows": [row],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def test_current_v4_auto_discovers_only_valid_pit_sector_sidecar(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "sidecars" / "pit_sector_membership.json"
    _write_sector_sidecar(sidecar)

    assert continuation.discover_valid_sector_membership(
        output_root=tmp_path / "store",
        training_as_of="2026-08-11T08:30:00+08:00",
    ) == sidecar.resolve()


def test_current_v4_ignores_current_company_snapshot_sidecar(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "sidecars" / "pit_sector_membership.json"
    _write_sector_sidecar(sidecar, source_id="companies.csv")

    assert continuation.discover_valid_sector_membership(
        output_root=tmp_path / "store",
        training_as_of="2026-08-11T08:30:00+08:00",
    ) is None


def test_current_v4_sidecar_detection_starts_new_immutable_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "store"
    output_root.mkdir()
    sidecar = output_root / "sidecars" / "pit_sector_membership.json"
    _write_sector_sidecar(sidecar)
    status_path = tmp_path / "training" / "continuation_status.json"
    manifest = {
        "manifest_hash": "sha256:" + "a" * 64,
        "execution": {"temporary_storage_budget_bytes": 123},
        "store_identity": {
            "direct_builder_schema_version": "portfolio-ml-direct-numeric.v4",
            "direct_identity": {
                "schema_version": "portfolio-ml-direct-numeric.v4",
                "raw_manifest_hash": "sha256:" + "b" * 64,
                "raw_manifest_file_hash": "sha256:" + "c" * 64,
                "corporate_action_manifest_file_hash": (
                    "sha256:" + "0" * 64
                ),
                "sector_membership_file_hash": None,
                "training_as_of": "2026-08-11T08:30:00+08:00",
                "benchmark_entity_id": "TAIEX",
                "minimum_train_dates": 252,
                "test_date_count": 63,
                "purge_trading_days": 60,
                "embargo_trading_days": 5,
            },
        },
    }
    discovered_raw = tmp_path / "raw-manifest.json"
    discovered_raw.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        continuation,
        "_discover_hash_bound_manifest",
        lambda **_: discovered_raw,
    )
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(continuation.subprocess, "run", fake_run)
    refreshed = {"manifest_hash": "sha256:" + "d" * 64}
    monkeypatch.setattr(
        continuation,
        "_validated_store_manifest",
        lambda *_args, **_kwargs: (tmp_path / "v4.json", refreshed),
    )

    path, result = continuation._ensure_current_direct_schema(
        output_root=output_root,
        manifest_path=tmp_path / "current.json",
        manifest=manifest,
        status_path=status_path,
        batch_size=8192,
        workers=2,
        memory_budget_mb=4096,
    )

    assert path == tmp_path / "v4.json"
    assert result == refreshed
    assert len(calls) == 1
    assert "--sector-membership" in calls[0]
    assert str(sidecar.resolve()) in calls[0]
