from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

import scripts.continue_ml_direct_v3_refresh_chain as chain


def _args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        raw_manifest=tmp_path / "raw.json",
        store_output_dir=tmp_path / "store",
        training_output_dir=tmp_path / "training",
        output_root=tmp_path / "output",
        database=tmp_path / "twstock.db",
        training_as_of="2026-07-30T08:30:00+08:00",
        benchmark_entity="TAIEX",
        sector_membership=tmp_path / "sector.json",
        corporate_action_manifest=tmp_path / "events.json",
        minimum_train_dates=252,
        test_date_count=63,
        purge_trading_days=60,
        embargo_trading_days=5,
        batch_size=8192,
        workers=2,
        memory_budget_mb=4096,
        temporary_storage_budget_bytes=214748364800,
        poll_seconds=15,
        legacy_direct_process_id=20688,
        status_path=None,
        operational_log_dir=None,
    )


def test_direct_and_downstream_commands_use_fresh_process_custody(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    direct = chain._direct_build_command(args)
    assert "build_portfolio_ml_direct_numeric_store.py" in direct[1]
    assert "--corporate-action-manifest" in direct
    assert str(args.corporate_action_manifest.resolve()) in direct
    assert "--temporary-storage-budget-bytes" in direct

    ooc = chain._ooc_helper_command(
        direct_process_id=31415,
        store_output_dir=args.store_output_dir,
        training_output_dir=args.training_output_dir,
        args=args,
    )
    assert "--direct-process-id" in ooc
    assert ooc[ooc.index("--direct-process-id") + 1] == "31415"

    release = chain._release_command(
        ooc_process_id=27182,
        training_output_dir=args.training_output_dir,
        output_root=args.output_root,
        database=args.database,
    )
    assert release[release.index("--ooc-helper-process-id") + 1] == "27182"


def test_latest_direct_manifest_requires_current_v4(tmp_path: Path) -> None:
    output_root = tmp_path / "store"
    run = output_root / "runs" / "direct-v3"
    run.mkdir(parents=True)
    manifest_hash = "sha256:" + "a" * 64
    manifest = {
        "manifest_hash": manifest_hash,
        "status": "complete",
        "execution": {"direct_numeric_store": True},
        "store_identity": {
            "direct_builder_schema_version": (
                "portfolio-ml-direct-numeric.v4"
            )
        },
    }
    (run / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (output_root / "latest_manifest.json").write_text(
        json.dumps(
            {
                "manifest_hash": manifest_hash,
                "manifest_path": "runs/direct-v3/manifest.json",
            }
        ),
        encoding="utf-8",
    )

    path, result = chain._latest_direct_manifest(output_root)

    assert path == run / "manifest.json"
    assert result == manifest


def test_latest_direct_manifest_rejects_legacy_schema(tmp_path: Path) -> None:
    output_root = tmp_path / "store"
    run = output_root / "runs" / "direct-v2"
    run.mkdir(parents=True)
    manifest_hash = "sha256:" + "b" * 64
    manifest = {
        "manifest_hash": manifest_hash,
        "status": "complete",
        "execution": {"direct_numeric_store": True},
        "store_identity": {
            "direct_builder_schema_version": (
                "portfolio-ml-direct-numeric.v2"
            )
        },
    }
    (run / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (output_root / "latest_manifest.json").write_text(
        json.dumps(
            {
                "manifest_hash": manifest_hash,
                "manifest_path": "runs/direct-v2/manifest.json",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="current direct builder schema",
    ):
        chain._latest_direct_manifest(output_root)


def test_sequential_wait_accepts_prevalidated_process_that_already_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing(_process_id: int) -> object:
        raise psutil.NoSuchProcess(_process_id)

    monkeypatch.setattr(psutil, "Process", _missing)

    chain._wait_for_expected_process(
        process_id=31415,
        expected_fragments=("target.py",),
        poll_seconds=1,
        already_observed=True,
    )


def test_sequential_wait_rejects_unobserved_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing(_process_id: int) -> object:
        raise psutil.NoSuchProcess(_process_id)

    monkeypatch.setattr(psutil, "Process", _missing)

    with pytest.raises(RuntimeError, match="not observed"):
        chain._wait_for_expected_process(
            process_id=31415,
            expected_fragments=("target.py",),
            poll_seconds=1,
        )


def test_chain_heartbeat_preserves_status_and_records_process_custody(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "training" / "v3_refresh_chain_status.json"
    status_path.parent.mkdir()
    status_path.write_text(
        json.dumps(
            {
                "schema_version": chain.SCHEMA_VERSION,
                "status": "waiting_for_legacy_chain",
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            }
        ),
        encoding="utf-8",
    )

    chain._publish_chain_heartbeat(
        status_path=status_path,
        process_id=31415,
        wait_phase="legacy_ooc_helper",
        command="python continue_ml_direct_ooc_after_store.py --training-output-dir C:\\training",
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "waiting_for_legacy_chain"
    assert payload["heartbeat_schema_version"] == (
        "portfolio-ml-direct-v3-refresh-chain-heartbeat.v1"
    )
    assert payload["heartbeat_process_id"] == 31415
    assert payload["heartbeat_phase"] == "legacy_ooc_helper"
    assert payload["formal_oos_allowed"] is False


def test_parser_supports_stopped_chain_recovery_mode() -> None:
    args = chain.build_parser().parse_args(
        [
            "--legacy-direct-process-id",
            "0",
            "--legacy-ooc-helper-process-id",
            "0",
            "--legacy-release-process-id",
            "0",
            "--raw-manifest",
            "raw.json",
            "--store-output-dir",
            "store",
            "--training-output-dir",
            "training",
            "--output-root",
            "output",
            "--database",
            "twstock.db",
            "--training-as-of",
            "2026-07-30T08:30:00+08:00",
            "--benchmark-entity",
            "TAIEX",
            "--resume-after-legacy-chain",
        ]
    )

    assert args.resume_after_legacy_chain is True


def test_custom_status_path_routes_operational_logs_next_to_status(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    args.status_path = tmp_path / "runtime" / "chain.json"
    store_output_dir = args.store_output_dir.resolve()
    primary_status_path = args.status_path.resolve()
    log_dir = chain._operational_log_dir(
        args=args,
        primary_status_path=primary_status_path,
        store_output_dir=store_output_dir,
    )

    assert log_dir == tmp_path / "runtime" / "logs"
    assert log_dir != store_output_dir / "logs"


def test_explicit_operational_log_dir_overrides_status_location(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    args.status_path = tmp_path / "runtime" / "chain.json"
    args.operational_log_dir = tmp_path / "logs"

    assert chain._operational_log_dir(
        args=args,
        primary_status_path=args.status_path.resolve(),
        store_output_dir=args.store_output_dir.resolve(),
    ) == args.operational_log_dir.resolve()


def test_cleanup_stops_only_live_spawned_processes() -> None:
    events: list[str] = []

    class _FakeProcess:
        def __init__(self, *, live: bool) -> None:
            self.live = live

        def poll(self) -> int | None:
            return None if self.live else 0

        def terminate(self) -> None:
            events.append("terminate")
            self.live = False

        def wait(self, *, timeout: int) -> int:
            del timeout
            events.append("wait")
            return 0

        def kill(self) -> None:
            events.append("kill")
            self.live = False

    live = _FakeProcess(live=True)
    exited = _FakeProcess(live=False)

    chain._cleanup_spawned_processes(exited, live, None)

    assert events == ["terminate", "wait"]


def test_recovery_collision_does_not_overwrite_primary_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_collision(**_kwargs: object) -> None:
        raise RuntimeError("active target process")

    monkeypatch.setattr(
        chain,
        "_assert_no_active_target_processes",
        _raise_collision,
    )
    training = tmp_path / "training"
    argv = [
        "--legacy-direct-process-id",
        "0",
        "--legacy-ooc-helper-process-id",
        "0",
        "--legacy-release-process-id",
        "0",
        "--resume-after-legacy-chain",
        "--raw-manifest",
        str(tmp_path / "raw.json"),
        "--store-output-dir",
        str(tmp_path / "store"),
        "--training-output-dir",
        str(training),
        "--output-root",
        str(tmp_path / "output"),
        "--database",
        str(tmp_path / "twstock.db"),
        "--training-as-of",
        "2026-07-30T08:30:00+08:00",
        "--benchmark-entity",
        "TAIEX",
    ]

    assert chain.main(argv) == 2
    assert not (
        training / "v3_refresh_chain_status.json"
    ).exists()
    recovery_status = json.loads(
        (training / "v3_refresh_chain_recovery_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert recovery_status["status"] == "blocked"
