from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import scripts.maintain_ml_direct_v3_refresh_chain as maintenance
import scripts.continue_ml_direct_v3_refresh_chain as chain_continuation
from data_module.ml_storage_capacity import (
    SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET,
    SCHEDULED_SAFETY_RESERVE_BYTES,
    SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET,
    MLStorageCapacityBudget,
    acquire_heavy_chain_reservation,
    evaluate_capacity,
    heavy_chain_lock_path,
    release_heavy_chain_reservation,
)


def _args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        raw_manifest=tmp_path / "raw.json",
        store_output_dir=tmp_path / "store",
        training_output_dir=tmp_path / "training",
        output_root=tmp_path / "output",
        database=tmp_path / "twstock.db",
        training_as_of="2026-08-11T08:30:00+08:00",
        benchmark_entity="TAIEX",
        sector_membership=None,
        corporate_action_manifest=tmp_path / "events.json",
        formal_portfolio_ledger=None,
        formal_rule_champion_history=None,
        minimum_train_dates=252,
        test_date_count=63,
        purge_trading_days=60,
        embargo_trading_days=5,
        batch_size=8192,
        workers=2,
        memory_budget_mb=4096,
        persistent_storage_budget_bytes=SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET,
        temporary_storage_budget_bytes=SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET,
        safety_reserve_bytes=SCHEDULED_SAFETY_RESERVE_BYTES,
        poll_seconds=15,
        retry_delay_seconds=30,
        watch_formal_inputs=False,
        max_restarts=0,
    )


def test_legacy_watcher_detects_prospective_wrapper_without_exposing_path(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    prospective = tmp_path / "prospective-ledger.json"
    prospective.write_text(
        json.dumps(
            {
                "schema_version": "prospective-formal-simulated-portfolio-ledger-manifest.v1",
                "mode": "prospective_formal_simulation",
            }
        ),
        encoding="utf-8",
    )
    args.formal_portfolio_ledger = prospective

    reasons = maintenance._legacy_watcher_prospective_guard(args)

    assert reasons == ("formal_portfolio_ledger:mode=prospective_formal_simulation",)
    assert str(prospective) not in " ".join(reasons)


def test_legacy_watcher_does_not_let_explicit_legacy_path_hide_prospective_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    legacy = tmp_path / "legacy-ledger.json"
    legacy.write_text("{}", encoding="utf-8")
    prospective = tmp_path / "prospective-ledger.json"
    prospective.write_text(
        json.dumps(
            {
                "schema_version": "prospective-formal-simulated-portfolio-ledger-manifest.v1",
                "mode": "prospective_formal_simulation",
            }
        ),
        encoding="utf-8",
    )
    args.formal_portfolio_ledger = legacy
    monkeypatch.setenv(maintenance.FORMAL_PORTFOLIO_LEDGER_ENV, str(prospective))

    assert maintenance._legacy_watcher_prospective_guard(args) == (
        "formal_portfolio_ledger:mode=prospective_formal_simulation",
    )


def test_legacy_watcher_detects_nested_prospective_pit_manifest(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    prospective = tmp_path / "pit-sidecar.json"
    prospective.write_text(
        json.dumps(
            {
                "schema_version": "pit-sector-membership-sidecar-v1",
                "manifest": {
                    "scope": "prospective_only",
                },
                "rows": [],
            }
        ),
        encoding="utf-8",
    )
    args.sector_membership = prospective

    assert maintenance._legacy_watcher_prospective_guard(args) == (
        "pit_sector_membership:scope=prospective_only",
    )


def test_legacy_watcher_detects_compressed_prospective_pit_sidecar(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    prospective = tmp_path / "pit-sidecar.jsonl.gz"
    header = {
        "record_type": "manifest",
        "schema_version": "pit-sector-membership-sidecar-v1",
        "manifest": {"scope": "prospective_only"},
    }
    with gzip.open(prospective, "wt", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(header, separators=(",", ":")) + "\n")
    args.sector_membership = prospective

    assert maintenance._legacy_watcher_prospective_guard(args) == (
        "pit_sector_membership:scope=prospective_only",
    )


def test_legacy_watcher_bounded_reads_large_json_sidecar(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    prospective = tmp_path / "large-pit-sidecar.json"
    prefix = b'{"manifest":{"scope":"prospective_only"},"rows":['
    prospective.write_bytes(prefix + (b"0," * 1_100_000) + b"0]}")
    args.sector_membership = prospective

    assert prospective.stat().st_size > 2_000_000
    assert maintenance._legacy_watcher_prospective_guard(args) == (
        "pit_sector_membership:scope=prospective_only",
    )


def test_one_shot_legacy_watcher_blocks_prospective_input_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    args.training_output_dir.mkdir()
    prospective = tmp_path / "prospective-rule-history.json"
    prospective.write_text(
        json.dumps(
            {
                "schema_version": "prospective-formal-rule-champion-snapshot-history.v1",
                "mode": "prospective_formal_simulation",
            }
        ),
        encoding="utf-8",
    )
    args.formal_rule_champion_history = prospective
    monkeypatch.setattr(
        maintenance,
        "_parser",
        lambda: SimpleNamespace(parse_args=lambda _argv: args),
    )
    monkeypatch.setattr(maintenance, "_refresh_controlled_runtime_environment", lambda: ())
    monkeypatch.setattr(
        maintenance,
        "_capacity_recheck_after_reservation",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        maintenance,
        "_target_processes",
        lambda _output: (_ for _ in ()).throw(AssertionError("legacy process inspection must not run")),
    )
    monkeypatch.setattr(
        maintenance,
        "_start_continuation",
        lambda *_args: (_ for _ in ()).throw(AssertionError("legacy continuation must not start")),
    )

    assert maintenance.main([]) == 2
    log_path = args.training_output_dir / "logs" / "ml_direct_chain_maintenance.log"
    payload = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["message"] == "prospective_only_inputs_detected_legacy_watcher_blocked"
    assert payload["formal_oos_allowed"] is False
    assert payload["secret_values_emitted"] is False


def test_maintainer_rechecks_capacity_after_claiming_shared_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    args.output_root.mkdir()
    args.persistent_storage_budget_bytes = SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET
    args.temporary_storage_budget_bytes = SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET
    args.safety_reserve_bytes = SCHEDULED_SAFETY_RESERVE_BYTES
    monkeypatch.setattr(
        maintenance,
        "_parser",
        lambda: SimpleNamespace(parse_args=lambda _argv: args),
    )
    fake_capacity = evaluate_capacity(
        budget=MLStorageCapacityBudget(
            persistent_new_bytes_budget=SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET,
            temporary_peak_bytes_budget=SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET,
            safety_reserve_bytes=SCHEDULED_SAFETY_RESERVE_BYTES,
        ),
        usage={
            "probe_path": str(args.output_root),
            "total_bytes": SCHEDULED_SAFETY_RESERVE_BYTES,
            "used_bytes": SCHEDULED_SAFETY_RESERVE_BYTES,
            "free_bytes": 0,
        },
        stage="fixture_locked_recheck",
        persistent_new_bytes_estimate=SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET,
        temporary_peak_bytes_observed=SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET,
    )
    monkeypatch.setattr(
        maintenance,
        "preflight_capacity",
        lambda **_kwargs: fake_capacity,
    )

    assert maintenance.main([]) == 2
    log_path = args.training_output_dir / "logs" / "ml_direct_chain_maintenance.log"
    messages = [
        json.loads(line)["message"]
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert "storage_capacity_blocked" in messages
    recovered = acquire_heavy_chain_reservation(
        heavy_chain_lock_path(args.output_root)
    )
    assert recovered is not None
    release_heavy_chain_reservation(recovered)


def test_maintainer_reports_shared_reservation_competition(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    args.output_root.mkdir()
    lock_path = heavy_chain_lock_path(args.output_root)
    holder = acquire_heavy_chain_reservation(lock_path)
    assert holder is not None
    try:
        command = [
            sys.executable,
            str(Path(maintenance.__file__).resolve()),
            "--raw-manifest",
            str(args.raw_manifest),
            "--store-output-dir",
            str(args.store_output_dir),
            "--training-output-dir",
            str(args.training_output_dir),
            "--output-root",
            str(args.output_root),
            "--database",
            str(args.database),
            "--training-as-of",
            args.training_as_of,
            "--benchmark-entity",
            args.benchmark_entity,
            "--poll-seconds",
            "1",
            "--retry-delay-seconds",
            "1",
        ]
        completed = subprocess.run(
            command,
            cwd=Path(maintenance.__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == (
            maintenance._HEAVY_CHAIN_RESERVATION_UNAVAILABLE_RETURN_CODE
        )
    finally:
        release_heavy_chain_reservation(holder)


def test_recovery_command_is_hash_bound_and_fail_closed(tmp_path: Path) -> None:
    command = maintenance._continuation_command(_args(tmp_path))

    assert "--resume-after-legacy-chain" in command
    assert command[command.index("--legacy-direct-process-id") + 1] == "0"
    assert command[command.index("--corporate-action-manifest") + 1] == str(
        (tmp_path / "events.json").resolve()
    )
    assert "--no-resume" not in command


def test_recovery_command_can_bind_detected_sector_sidecar(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    detected = tmp_path / "sidecars" / "pit_sector_membership.json"
    command = maintenance._continuation_command(
        args,
        sector_membership=detected,
    )

    assert command[command.index("--sector-membership") + 1] == str(
        detected.resolve()
    )


def test_release_command_normalizes_legacy_release_root(
    tmp_path: Path,
) -> None:
    shared_output = tmp_path / "output"
    release_root = shared_output / "release_v4"
    training_root = release_root / "portfolio_ml_direct_ooc_training_production_v4_v5"

    command = chain_continuation._release_command(
        ooc_process_id=123,
        training_output_dir=training_root,
        output_root=release_root,
        database=tmp_path / "twstock.db",
    )

    assert command[command.index("--output-root") + 1] == str(
        shared_output.resolve()
    )


def test_target_process_scan_matches_only_known_chain_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "store"
    output_dir.mkdir()

    class _Process:
        def __init__(self, pid: int, command: list[str]) -> None:
            self.info = {"pid": pid, "cmdline": command}

    monkeypatch.setattr(
        maintenance.psutil,
        "process_iter",
        lambda **_: iter(
            (
                _Process(
                    11,
                    [
                        "python",
                        "build_portfolio_ml_direct_numeric_store.py",
                        str(output_dir),
                    ],
                ),
                _Process(12, ["python", "unrelated.py", str(output_dir)]),
            )
        ),
    )

    found = maintenance._target_processes(output_dir)

    assert [pid for pid, _ in found] == [11]


def test_chain_complete_requires_machine_status(tmp_path: Path) -> None:
    training = tmp_path / "training"
    training.mkdir()
    status_path = training / "v3_refresh_chain_status.json"
    status_path.write_text(
        json.dumps({"status": "v3_downstream_started"}),
        encoding="utf-8",
    )
    assert maintenance._chain_complete(training) is False

    status_path.write_text(json.dumps({"status": "complete"}), encoding="utf-8")
    assert maintenance._chain_complete(training) is True


def test_watch_mode_stays_alive_after_successful_continuation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed refresh must return the watcher to formal-input polling."""

    args = _args(tmp_path)
    args.training_output_dir.mkdir()
    args.watch_formal_inputs = True
    candidate = maintenance._RefreshCandidate(
        raw_manifest=tmp_path / "raw.json",
        training_as_of=args.training_as_of,
        sector_membership=None,
        corporate_action_manifest=None,
        formal_portfolio_ledger=None,
        formal_rule_champion_history=None,
        reasons=("new_validated_official_market_event_publication",),
    )

    monkeypatch.setattr(
        maintenance,
        "_parser",
        lambda: SimpleNamespace(parse_args=lambda _argv: args),
    )
    monkeypatch.setattr(maintenance, "_refresh_controlled_runtime_environment", lambda: ())
    monkeypatch.setattr(
        maintenance,
        "_capacity_recheck_after_reservation",
        lambda *_args: None,
    )
    monkeypatch.setattr(maintenance, "_target_processes", lambda _output: [])
    monkeypatch.setattr(maintenance, "_chain_complete", lambda _training: True)
    monkeypatch.setattr(
        maintenance,
        "_auto_refresh_candidate",
        lambda _args: candidate,
    )
    monkeypatch.setattr(
        maintenance,
        "_continuation_command",
        lambda _args, **_kwargs: ["safe-test-command"],
    )
    monkeypatch.setattr(
        maintenance,
        "_start_continuation",
        lambda _command, _log: SimpleNamespace(wait=lambda: 0),
    )

    class _StopPolling(Exception):
        pass

    def _stop_after_first_watch_sleep(_seconds: int) -> None:
        raise _StopPolling

    monkeypatch.setattr(maintenance.time, "sleep", _stop_after_first_watch_sleep)

    with pytest.raises(_StopPolling):
        maintenance.main([])

    log_path = args.training_output_dir / "logs" / "ml_direct_chain_maintenance.log"
    messages = [
        json.loads(line)["message"]
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert "continuation_exited" in messages
    assert "chain_complete_watching_formal_inputs" in messages
    assert not (args.training_output_dir / ".ml_direct_chain_maintenance.lock").exists()


def test_maintainer_child_keeps_heavy_reservation_after_wrapper_exit(
    tmp_path: Path,
) -> None:
    """真正 maintainer child 持有 lock 時 wrapper 離開不會製造空窗。"""

    repository_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "output"
    output_root.mkdir()
    training_output_dir = output_root / "training"
    store_output_dir = output_root / "store"
    ready_path = tmp_path / "child-ready"
    done_path = tmp_path / "child-done"
    child_pid_path = tmp_path / "child-pid"
    stop_path = tmp_path / "stop-child"

    child_bootstrap = tmp_path / "maintainer-child.py"
    child_bootstrap.write_text(
        """
import os
from pathlib import Path
import sys
import threading

from scripts import maintain_ml_direct_v3_refresh_chain as maintenance

ready = Path(os.environ["BALDR_TEST_READY"])
done = Path(os.environ["BALDR_TEST_DONE"])
stop = Path(os.environ["BALDR_TEST_STOP"])
original_acquire = maintenance._acquire_instance_lock


def acquire(training_output_dir):
    result = original_acquire(training_output_dir)
    if result is not None:
        ready.write_text("ready", encoding="utf-8")
    return result


def wait_for_parent(_seconds):
    event = threading.Event()
    while not stop.exists():
        event.wait(0.05)
    raise SystemExit(0)


maintenance._acquire_instance_lock = acquire
maintenance._refresh_controlled_runtime_environment = lambda: ()
maintenance._legacy_watcher_prospective_guard = lambda _args: ()
maintenance._target_processes = lambda _output: []
maintenance._chain_complete = lambda _training: True
maintenance._auto_refresh_candidate = lambda _args: None
maintenance._capacity_recheck_after_reservation = lambda *_args: None
maintenance.time.sleep = wait_for_parent
try:
    raise SystemExit(maintenance.main(sys.argv[1:]))
finally:
    done.write_text("done", encoding="utf-8")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    parent_bootstrap = tmp_path / "wrapper-parent.py"
    parent_bootstrap.write_text(
        """
import json
import os
from pathlib import Path
import subprocess
import sys
import time

child_args = json.loads(os.environ["BALDR_TEST_CHILD_ARGS"])
child = subprocess.Popen(
    [sys.executable, os.environ["BALDR_TEST_CHILD_SCRIPT"], *child_args],
    cwd=os.environ["BALDR_TEST_ROOT"],
)
Path(os.environ["BALDR_TEST_CHILD_PID"]).write_text(
    str(child.pid), encoding="utf-8"
)
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    if Path(os.environ["BALDR_TEST_READY"]).exists():
        os._exit(0)
    if child.poll() is not None:
        os._exit(4)
    time.sleep(0.05)
os._exit(5)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    child_args = [
        "--raw-manifest",
        str(tmp_path / "raw.json"),
        "--store-output-dir",
        str(store_output_dir),
        "--training-output-dir",
        str(training_output_dir),
        "--output-root",
        str(output_root),
        "--database",
        str(tmp_path / "twstock.db"),
        "--training-as-of",
        "2026-08-11T08:30:00+08:00",
        "--benchmark-entity",
        "TAIEX",
        "--persistent-storage-budget-bytes",
            str(SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET),
        "--temporary-storage-budget-bytes",
            str(SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET),
        "--safety-reserve-bytes",
            str(SCHEDULED_SAFETY_RESERVE_BYTES),
        "--poll-seconds",
        "1",
        "--retry-delay-seconds",
        "1",
        "--watch-formal-inputs",
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "BALDR_TEST_CHILD_ARGS": json.dumps(child_args),
            "BALDR_TEST_CHILD_SCRIPT": str(child_bootstrap),
            "BALDR_TEST_CHILD_PID": str(child_pid_path),
            "BALDR_TEST_DONE": str(done_path),
            "BALDR_TEST_READY": str(ready_path),
            "BALDR_TEST_ROOT": str(repository_root),
            "BALDR_TEST_STOP": str(stop_path),
            "PYTHONPATH": os.pathsep.join(
                value
                for value in (
                    str(repository_root),
                    environment.get("PYTHONPATH", ""),
                )
                if value
            ),
        }
    )
    parent = subprocess.Popen(
        [sys.executable, str(parent_bootstrap)],
        cwd=repository_root,
        env=environment,
    )
    try:
        assert parent.wait(timeout=25) == 0
        assert child_pid_path.is_file()
        assert ready_path.read_text(encoding="utf-8") == "ready"

        lock_path = heavy_chain_lock_path(output_root)
        blocked = acquire_heavy_chain_reservation(lock_path)
        assert blocked is None

        stop_path.write_text("stop", encoding="utf-8")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not done_path.exists():
            time.sleep(0.05)
        assert done_path.is_file()

        recovered = acquire_heavy_chain_reservation(lock_path)
        assert recovered is not None
        release_heavy_chain_reservation(recovered)
    finally:
        stop_path.write_text("stop", encoding="utf-8")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not done_path.exists():
            time.sleep(0.05)


def test_auto_refresh_candidate_requires_current_v4_without_sector_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    manifest = {
        "store_identity": {
            "direct_identity": {
                "schema_version": "portfolio-ml-direct-numeric.v4",
                "sector_membership_file_hash": None,
                "training_as_of": "2026-08-11T08:30:00+08:00",
            }
        }
    }
    candidate = tmp_path / "sector.json"
    monkeypatch.setattr(
        maintenance.ooc_continuation,
        "_latest_manifest",
        lambda _root: (tmp_path / "manifest.json", manifest),
    )
    observed: dict[str, object] = {}

    def discover(**kwargs: object) -> Path:
        observed.update(kwargs)
        return candidate

    monkeypatch.setattr(
        maintenance.ooc_continuation,
        "discover_valid_sector_membership",
        discover,
    )

    assert maintenance._auto_sector_refresh_candidate(args) == candidate
    assert observed["training_as_of"] == "2026-08-11T08:30:00+08:00"


def test_auto_refresh_candidate_ignores_current_v4_with_sector_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    manifest = {
        "store_identity": {
            "direct_identity": {
                "schema_version": "portfolio-ml-direct-numeric.v4",
                "sector_membership_file_hash": "sha256:" + "a" * 64,
                "training_as_of": "2026-08-11T08:30:00+08:00",
            }
        }
    }
    monkeypatch.setattr(
        maintenance.ooc_continuation,
        "_latest_manifest",
        lambda _root: (tmp_path / "manifest.json", manifest),
    )
    assert maintenance._auto_sector_refresh_candidate(args) is None


def test_instance_lock_rejects_live_owner(tmp_path: Path, monkeypatch) -> None:
    training = tmp_path / "training"
    training.mkdir()
    lock_path = training / ".ml_direct_chain_maintenance.lock"
    lock_path.write_text("123\n", encoding="utf-8")
    monkeypatch.setattr(maintenance.psutil, "pid_exists", lambda pid: pid == 123)
    monkeypatch.setattr(
        maintenance.psutil,
        "Process",
        lambda _pid: SimpleNamespace(
            cmdline=lambda: [
                "python",
                "maintain_ml_direct_v3_refresh_chain.py",
                "--training-output-dir",
                str(training),
            ]
        ),
    )

    assert maintenance._acquire_instance_lock(training) is None


def test_instance_lock_replaces_live_owner_for_different_training_lineage(
    tmp_path: Path, monkeypatch
) -> None:
    training = tmp_path / "training"
    other_training = tmp_path / "other-training"
    training.mkdir()
    other_training.mkdir()
    lock_path = training / ".ml_direct_chain_maintenance.lock"
    lock_path.write_text("123\n", encoding="utf-8")
    monkeypatch.setattr(maintenance.psutil, "pid_exists", lambda pid: pid == 123)
    monkeypatch.setattr(
        maintenance.psutil,
        "Process",
        lambda _pid: SimpleNamespace(
            cmdline=lambda: [
                "python",
                "maintain_ml_direct_v3_refresh_chain.py",
                "--training-output-dir",
                str(other_training),
            ]
        ),
    )

    lock = maintenance._acquire_instance_lock(training)

    assert lock is not None
    try:
        assert lock_path.read_text(encoding="utf-8") == f"{maintenance.os.getpid()}\n"
    finally:
        maintenance._release_instance_lock(lock)


def test_instance_lock_preserves_live_owner_when_commandline_is_inaccessible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    training = tmp_path / "training"
    training.mkdir()
    lock_path = training / ".ml_direct_chain_maintenance.lock"
    lock_path.write_text("123\n", encoding="utf-8")
    monkeypatch.setattr(maintenance.psutil, "pid_exists", lambda pid: pid == 123)

    class _Process:
        def cmdline(self) -> list[str]:
            raise maintenance.psutil.AccessDenied(pid=123)

    monkeypatch.setattr(maintenance.psutil, "Process", lambda _pid: _Process())

    assert maintenance._acquire_instance_lock(training) is None
    assert lock_path.read_text(encoding="utf-8") == "123\n"


def test_instance_lock_recovers_dead_owner_without_parallel_chain(
    tmp_path: Path, monkeypatch
) -> None:
    training = tmp_path / "training"
    training.mkdir()
    lock_path = training / ".ml_direct_chain_maintenance.lock"
    lock_path.write_text("29504\n", encoding="utf-8")
    monkeypatch.setattr(maintenance.psutil, "pid_exists", lambda _pid: False)

    lock = maintenance._acquire_instance_lock(training)

    assert lock is not None
    try:
        assert lock_path.read_text(encoding="utf-8") == f"{maintenance.os.getpid()}\n"
    finally:
        maintenance._release_instance_lock(lock)
    assert not lock_path.exists()


def _write_pointer_bound_raw_publication(
    output_root: Path,
    *,
    decision_at: str = "2026-08-12T08:30:00+08:00",
) -> Path:
    publication_root = output_root / "ml_pit_year_shards"
    publication_dir = publication_root / "runs" / "pit-new"
    dataset_dir = publication_dir / "all_field_enriched"
    dataset_dir.mkdir(parents=True)
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
    dataset["manifest_hash"] = maintenance.dataset_assembler._sha256_json(
        dataset
    )
    dataset_path = dataset_dir / "manifest.json"
    dataset_path.write_text(
        json.dumps(dataset),
        encoding="utf-8",
    )
    publication = {
        "schema_version": "ml-pit-year-shards.v1",
        "stage": "raw_pit_observations",
        "publication_id": "pit-new",
        "decision_at": decision_at,
        "history_start_date": "2014-01-01",
        "datasets": {
            "all_field_enriched": {
                "manifest_path": "all_field_enriched/manifest.json",
                "manifest_hash": dataset["manifest_hash"],
            }
        },
    }
    publication["manifest_hash"] = maintenance._canonical_sha256(publication)
    publication_path = publication_dir / "manifest.json"
    publication_path.write_text(
        json.dumps(publication),
        encoding="utf-8",
    )
    pointer = {
        "schema_version": "ml-pit-year-shards-pointer.v1",
        "publication_id": "pit-new",
        "manifest_path": "runs/pit-new/manifest.json",
        "manifest_hash": publication["manifest_hash"],
    }
    pointer_path = publication_root / "latest_manifest.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(
        json.dumps(pointer),
        encoding="utf-8",
    )
    return dataset_path


def test_validated_latest_raw_dataset_requires_newer_pointer_bound_publication(
    tmp_path: Path,
) -> None:
    dataset_path = _write_pointer_bound_raw_publication(tmp_path)
    direct_identity = {
        "raw_manifest_hash": "sha256:" + "a" * 64,
        "training_as_of": "2026-08-11T08:30:00+08:00",
    }
    args = _args(tmp_path)
    args.output_root = tmp_path

    assert maintenance._validated_latest_raw_dataset(
        args,
        direct_identity=direct_identity,
    ) == (dataset_path.resolve(), "2026-08-12T08:30:00+08:00")


def test_validated_latest_raw_dataset_rejects_tampered_pointer_manifest(
    tmp_path: Path,
) -> None:
    _write_pointer_bound_raw_publication(tmp_path)
    pointer_path = tmp_path / "ml_pit_year_shards" / "latest_manifest.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["manifest_hash"] = "sha256:" + "b" * 64
    pointer_path.write_text(
        json.dumps(pointer),
        encoding="utf-8",
    )
    args = _args(tmp_path)
    args.output_root = tmp_path

    assert maintenance._validated_latest_raw_dataset(
        args,
        direct_identity={
            "raw_manifest_hash": "sha256:" + "a" * 64,
            "training_as_of": "2026-08-11T08:30:00+08:00",
        },
    ) is None


def test_refresh_candidate_binds_new_raw_and_preserves_override_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    args.corporate_action_manifest = tmp_path / "old-events.json"
    new_raw = tmp_path / "new-raw.json"
    new_events = tmp_path / "new-events.json"
    sector = tmp_path / "sector.json"
    identity = {
        "schema_version": "portfolio-ml-direct-numeric.v4",
        "raw_manifest_hash": "sha256:" + "a" * 64,
        "training_as_of": "2026-08-11T08:30:00+08:00",
        "sector_membership_file_hash": "sha256:" + "0" * 64,
        "corporate_action_manifest_file_hash": "sha256:" + "c" * 64,
    }
    monkeypatch.setattr(
        maintenance,
        "_current_direct_identity",
        lambda _args: identity,
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_raw_dataset",
        lambda _args, direct_identity: (
            new_raw,
            "2026-08-12T08:30:00+08:00",
        ),
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_corporate_action_manifest",
        lambda _args, training_as_of: (
            new_events,
            "sha256:" + "d" * 64,
            "sha256:" + "e" * 64,
        ),
    )
    monkeypatch.setattr(
        maintenance,
        "_auto_sector_refresh_candidate",
        lambda _args, training_as_of: sector,
    )

    candidate = maintenance._auto_refresh_candidate(args)

    assert candidate is not None
    assert candidate.raw_manifest == new_raw
    assert candidate.training_as_of == "2026-08-12T08:30:00+08:00"
    assert candidate.sector_membership == sector
    assert candidate.corporate_action_manifest == new_events.resolve()
    assert candidate.reasons == (
        "new_validated_raw_pit_publication",
        "new_validated_official_market_event_publication",
        "new_validated_pit_sector_sidecar",
    )


def test_refresh_candidate_treats_null_sector_hash_as_no_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    args.corporate_action_manifest = None
    identity = {
        "schema_version": "portfolio-ml-direct-numeric.v4",
        "raw_manifest_hash": "sha256:" + "a" * 64,
        "training_as_of": "2026-08-11T08:30:00+08:00",
        "sector_membership_file_hash": None,
    }
    raw = tmp_path / "new-raw.json"
    monkeypatch.setattr(
        maintenance,
        "_current_direct_identity",
        lambda _args: identity,
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_raw_dataset",
        lambda _args, direct_identity: (
            raw,
            "2026-08-12T08:30:00+08:00",
        ),
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_corporate_action_manifest",
        lambda _args, training_as_of: None,
    )
    monkeypatch.setattr(
        maintenance,
        "_auto_sector_refresh_candidate",
        lambda _args, training_as_of: None,
    )

    candidate = maintenance._auto_refresh_candidate(args)

    assert candidate is not None
    assert candidate.raw_manifest == raw
    assert candidate.sector_membership is None
    assert candidate.reasons == ("new_validated_raw_pit_publication",)


def test_controlled_environment_refresh_adopts_late_windows_owner_deposit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "formal-ledger.json"
    history = tmp_path / "formal-history.json"
    sector = tmp_path / "sector.json"
    ledger.write_text("{}", encoding="utf-8")
    history.write_text("{}", encoding="utf-8")
    sector.write_text("{}", encoding="utf-8")

    class _FakeKey:
        def __init__(self, values: dict[str, str]) -> None:
            self.values = values

        def __enter__(self) -> "_FakeKey":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class _FakeWinreg:
        HKEY_CURRENT_USER = "user"
        HKEY_LOCAL_MACHINE = "machine"
        REG_EXPAND_SZ = 2

        def __init__(self) -> None:
            self.values = {
                self.HKEY_CURRENT_USER: {
                    maintenance.FORMAL_PORTFOLIO_LEDGER_ENV: str(
                        ledger.resolve()
                    ),
                    maintenance.FORMAL_RULE_CHAMPION_HISTORY_ENV: str(
                        history.resolve()
                    ),
                    maintenance.PIT_SECTOR_MEMBERSHIP_ENV: str(
                        sector.resolve()
                    ),
                    maintenance.RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY_ENV: (
                        "late-secret"
                    ),
                    maintenance.RULE_CHAMPION_CONTROLLED_STORE_ID_ENV: (
                        "late-store"
                    ),
                }
            }

        def OpenKey(self, hive: str, _subkey: str) -> _FakeKey:
            if hive not in self.values:
                raise OSError("registry key missing")
            return _FakeKey(self.values[hive])

        def QueryValueEx(
            self,
            key: _FakeKey,
            name: str,
        ) -> tuple[str, int]:
            try:
                return key.values[name], 1
            except KeyError as exc:
                raise OSError("registry value missing") from exc

        def ExpandEnvironmentStrings(self, value: str) -> str:
            return value

    fake_winreg = _FakeWinreg()
    monkeypatch.setattr(maintenance.os, "name", "nt")
    monkeypatch.setattr(maintenance, "winreg", fake_winreg)
    monkeypatch.setattr(
        maintenance,
        "_INITIAL_CONTROLLED_RUNTIME_ENVIRONMENT",
        {name: None for name in maintenance._CONTROLLED_RUNTIME_ENVIRONMENT_NAMES},
    )
    monkeypatch.setattr(
        maintenance,
        "_ADOPTED_CONTROLLED_RUNTIME_ENVIRONMENT",
        {},
    )
    for name in maintenance._CONTROLLED_RUNTIME_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    refreshed = maintenance._refresh_controlled_runtime_environment()

    assert set(refreshed) == set(maintenance._CONTROLLED_RUNTIME_ENVIRONMENT_NAMES)
    assert maintenance._environment_path(
        maintenance.FORMAL_PORTFOLIO_LEDGER_ENV
    ) == ledger.resolve()
    assert maintenance._environment_path(
        maintenance.FORMAL_RULE_CHAMPION_HISTORY_ENV
    ) == history.resolve()
    assert os.environ[
        maintenance.RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY_ENV
    ] == "late-secret"
    assert os.environ[maintenance.RULE_CHAMPION_CONTROLLED_STORE_ID_ENV] == (
        "late-store"
    )

    replacement_ledger = tmp_path / "replacement-ledger.json"
    replacement_ledger.write_text("{}", encoding="utf-8")
    fake_winreg.values[fake_winreg.HKEY_CURRENT_USER][
        maintenance.FORMAL_PORTFOLIO_LEDGER_ENV
    ] = str(replacement_ledger.resolve())
    maintenance._refresh_controlled_runtime_environment()
    assert os.environ[maintenance.FORMAL_PORTFOLIO_LEDGER_ENV] == str(
        replacement_ledger.resolve()
    )

    del fake_winreg.values[fake_winreg.HKEY_CURRENT_USER][
        maintenance.FORMAL_PORTFOLIO_LEDGER_ENV
    ]
    maintenance._refresh_controlled_runtime_environment()
    assert maintenance.FORMAL_PORTFOLIO_LEDGER_ENV not in os.environ


def test_refresh_candidate_discovers_all_formal_inputs_from_controlled_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    sector = tmp_path / "sector.json"
    ledger = tmp_path / "formal-ledger.json"
    history = tmp_path / "formal-history.json"
    for path in (sector, ledger, history):
        path.write_text("{}", encoding="utf-8")
    identity = {
        "schema_version": "portfolio-ml-direct-numeric.v4",
        "raw_manifest_hash": "sha256:" + "a" * 64,
        "training_as_of": "2026-08-11T08:30:00+08:00",
        "sector_membership_file_hash": "sha256:" + "0" * 64,
    }
    monkeypatch.setattr(
        maintenance,
        "_current_direct_identity",
        lambda _args: identity,
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_raw_dataset",
        lambda _args, direct_identity: None,
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_corporate_action_manifest",
        lambda _args, training_as_of: None,
    )
    monkeypatch.setattr(
        maintenance,
        "_auto_sector_refresh_candidate",
        lambda _args, training_as_of: sector,
    )
    monkeypatch.setattr(
        maintenance,
        "load_formal_portfolio_state_ledger",
        lambda _path: SimpleNamespace(decision_dates=("2026-08-10",)),
    )
    monkeypatch.setattr(
        maintenance,
        "load_verified_rule_champion_snapshot_history",
        lambda _path, training_as_of: SimpleNamespace(
            decision_dates=("2026-08-10",)
        ),
    )
    monkeypatch.setenv(
        maintenance.FORMAL_PORTFOLIO_LEDGER_ENV,
        str(ledger),
    )
    monkeypatch.setenv(
        maintenance.FORMAL_RULE_CHAMPION_HISTORY_ENV,
        str(history),
    )

    candidate = maintenance._auto_refresh_candidate(args)

    assert candidate is not None
    assert candidate.sector_membership == sector
    assert candidate.formal_portfolio_ledger == ledger.resolve()
    assert candidate.formal_rule_champion_history == history.resolve()
    assert candidate.reasons == (
        "new_validated_pit_sector_sidecar",
        "new_validated_formal_portfolio_ledger",
        "new_validated_formal_rule_champion_history",
    )


def test_formal_only_refresh_waits_until_all_three_inputs_are_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    ledger = tmp_path / "formal-ledger.json"
    ledger.write_text("{}", encoding="utf-8")
    identity = {
        "schema_version": "portfolio-ml-direct-numeric.v4",
        "raw_manifest_hash": "sha256:" + "a" * 64,
        "training_as_of": "2026-08-11T08:30:00+08:00",
        "sector_membership_file_hash": "sha256:" + "0" * 64,
    }
    monkeypatch.setattr(
        maintenance,
        "_current_direct_identity",
        lambda _args: identity,
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_raw_dataset",
        lambda _args, direct_identity: None,
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_corporate_action_manifest",
        lambda _args, training_as_of: None,
    )
    monkeypatch.setattr(
        maintenance,
        "_auto_sector_refresh_candidate",
        lambda _args, training_as_of: None,
    )
    monkeypatch.setattr(
        maintenance,
        "load_formal_portfolio_state_ledger",
        lambda _path: SimpleNamespace(decision_dates=("2026-08-10",)),
    )
    monkeypatch.setenv(
        maintenance.FORMAL_PORTFOLIO_LEDGER_ENV,
        str(ledger),
    )
    monkeypatch.delenv(
        maintenance.FORMAL_RULE_CHAMPION_HISTORY_ENV,
        raising=False,
    )

    assert maintenance._auto_refresh_candidate(args) is None


def test_refresh_ignores_official_wrapper_republish_with_same_canonical_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path)
    current_events = tmp_path / "current-events.json"
    canonical_hash = "sha256:" + "e" * 64
    current_events.write_text(
        json.dumps({"canonical_events": {"file_hash": canonical_hash}}),
        encoding="utf-8",
    )
    args.corporate_action_manifest = current_events
    identity = {
        "schema_version": "portfolio-ml-direct-numeric.v4",
        "raw_manifest_hash": "sha256:" + "a" * 64,
        "training_as_of": "2026-08-11T08:30:00+08:00",
        "sector_membership_file_hash": "sha256:" + "0" * 64,
        "corporate_action_manifest_file_hash": "sha256:" + "c" * 64,
    }
    monkeypatch.setattr(
        maintenance,
        "_current_direct_identity",
        lambda _args: identity,
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_raw_dataset",
        lambda _args, direct_identity: None,
    )
    monkeypatch.setattr(
        maintenance,
        "_validated_latest_corporate_action_manifest",
        lambda _args, training_as_of: (
            tmp_path / "republished-events.json",
            "sha256:" + "d" * 64,
            canonical_hash,
        ),
    )
    monkeypatch.setattr(
        maintenance,
        "_auto_sector_refresh_candidate",
        lambda _args, training_as_of: None,
    )

    assert maintenance._auto_refresh_candidate(args) is None


def test_continuation_command_accepts_refresh_input_overrides(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    raw = tmp_path / "new-raw.json"
    events = tmp_path / "new-events.json"
    sector = tmp_path / "sector.json"

    command = maintenance._continuation_command(
        args,
        raw_manifest=raw,
        training_as_of="2026-08-12T08:30:00+08:00",
        sector_membership=sector,
        corporate_action_manifest=events,
    )

    assert command[command.index("--raw-manifest") + 1] == str(raw.resolve())
    assert command[command.index("--training-as-of") + 1] == (
        "2026-08-12T08:30:00+08:00"
    )
    assert command[command.index("--sector-membership") + 1] == str(
        sector.resolve()
    )
    assert command[command.index("--corporate-action-manifest") + 1] == str(
        events.resolve()
    )
