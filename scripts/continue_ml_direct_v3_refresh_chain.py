"""Hand off the active legacy direct-store chain to the current contract.

The supervisor is intentionally one-shot.  It observes the already-running
legacy direct/OOC/release processes, waits for them to finish, then starts an
immutable current-schema direct-store build and its fail-closed downstream gates.  It does
not terminate, mutate, or reuse an in-flight run.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCHEMA_VERSION = "portfolio-ml-direct-v3-refresh-chain.v1"
_HEARTBEAT_SCHEMA_VERSION = "portfolio-ml-direct-v3-refresh-chain-heartbeat.v1"
# Allow normal Windows scan/indexer locks to clear without abandoning a long
# running custody chain; exhaustion remains fail-closed.
_ATOMIC_REPLACE_RETRY_COUNT = 120
_ATOMIC_REPLACE_RETRY_DELAY_SECONDS = 0.5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-direct-process-id", type=int, required=True)
    parser.add_argument("--legacy-ooc-helper-process-id", type=int, required=True)
    parser.add_argument("--legacy-release-process-id", type=int, required=True)
    parser.add_argument(
        "--resume-after-legacy-chain",
        action="store_true",
        help=(
            "resume after a previously observed legacy chain has stopped; "
            "the command fails closed if any matching target process is "
            "still active"
        ),
    )
    parser.add_argument("--raw-manifest", type=Path, required=True)
    parser.add_argument("--store-output-dir", type=Path, required=True)
    parser.add_argument("--training-output-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--benchmark-entity", required=True)
    parser.add_argument("--sector-membership", type=Path)
    parser.add_argument("--corporate-action-manifest", type=Path)
    parser.add_argument("--formal-portfolio-ledger", type=Path)
    parser.add_argument("--formal-rule-champion-history", type=Path)
    parser.add_argument("--minimum-train-dates", type=int, default=252)
    parser.add_argument("--test-date-count", type=int, default=63)
    parser.add_argument("--purge-trading-days", type=int, default=60)
    parser.add_argument("--embargo-trading-days", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument(
        "--temporary-storage-budget-bytes",
        "--temporary-peak-bytes-budget",
        dest="temporary_storage_budget_bytes",
        type=int,
    )
    parser.add_argument(
        "--persistent-storage-budget-bytes",
        "--persistent-new-bytes-budget",
        dest="persistent_storage_budget_bytes",
        type=int,
    )
    parser.add_argument("--safety-reserve-bytes", type=int)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--status-path", type=Path)
    parser.add_argument(
        "--operational-log-dir",
        type=Path,
        help=(
            "directory for supervisor child-process logs; when omitted, a "
            "custom --status-path uses its parent logs directory"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = build_parser().parse_args(argv)
    store_output_dir = args.store_output_dir.resolve()
    training_output_dir = args.training_output_dir.resolve()
    output_root = args.output_root.resolve()
    primary_status_path = (
        args.status_path.resolve()
        if args.status_path is not None
        else training_output_dir / "v3_refresh_chain_status.json"
    )
    status_path = (
        training_output_dir / "v3_refresh_chain_recovery_status.json"
        if args.resume_after_legacy_chain and args.status_path is None
        else primary_status_path
    )
    operational_log_dir = _operational_log_dir(
        args=args,
        primary_status_path=primary_status_path,
        store_output_dir=store_output_dir,
    )
    direct_process: subprocess.Popen[Any] | None = None
    ooc_process: subprocess.Popen[Any] | None = None
    release_process: subprocess.Popen[Any] | None = None
    try:
        _atomic_write_json(
            status_path,
            {
                "schema_version": SCHEMA_VERSION,
                "status": (
                    "resuming_after_legacy_chain"
                    if args.resume_after_legacy_chain
                    else "waiting_for_legacy_chain"
                ),
                "legacy_process_ids": {
                    "direct": args.legacy_direct_process_id,
                    "ooc_helper": args.legacy_ooc_helper_process_id,
                    "release": args.legacy_release_process_id,
                },
                "store_output_dir": str(store_output_dir),
                "training_output_dir": str(training_output_dir),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        legacy_process_specs = (
            (
                args.legacy_direct_process_id,
                (
                    "build_portfolio_ml_direct_numeric_store.py",
                    str(store_output_dir),
                ),
            ),
            (
                args.legacy_ooc_helper_process_id,
                (
                    "continue_ml_direct_ooc_after_store.py",
                    str(training_output_dir),
                ),
            ),
            (
                args.legacy_release_process_id,
                (
                    "continue_ml_release_after_ooc.py",
                    str(training_output_dir),
                ),
            ),
        )
        if args.resume_after_legacy_chain:
            _assert_no_active_target_processes(
                expected_specs=tuple(
                    (fragments, label)
                    for _process_id, fragments in legacy_process_specs
                    for label in (fragments[0],)
                )
            )
            # Do not claim the primary chain until the collision scan has
            # passed.  A failed recovery therefore cannot mask a still-live
            # supervisor that owns the primary status file.
            status_path = primary_status_path
        else:
            # Capture all three command lines before waiting sequentially.
            # The OOC/release helpers may exit immediately after the direct
            # process fails; validating them only after the direct wait would
            # turn an already-observed process into a false custody failure.
            for process_id, expected_fragments in legacy_process_specs:
                _assert_expected_process(
                    process_id=process_id,
                    expected_fragments=expected_fragments,
                )
            for process_id, expected_fragments in legacy_process_specs:
                _wait_for_expected_process(
                    process_id=process_id,
                    expected_fragments=expected_fragments,
                    poll_seconds=args.poll_seconds,
                    already_observed=True,
                    status_path=status_path,
                    wait_phase=f"legacy_{expected_fragments[0]}",
                )
        _atomic_write_json(
            status_path,
            {
                "schema_version": SCHEMA_VERSION,
                "status": "direct_v3_build_starting",
                "store_output_dir": str(store_output_dir),
                "training_output_dir": str(training_output_dir),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        direct_command = _direct_build_command(args)
        direct_log = operational_log_dir / "direct_v3_refresh.log"
        direct_process = _start_logged(direct_command, direct_log)
        _atomic_write_json(
            status_path,
            {
                "schema_version": SCHEMA_VERSION,
                "status": "direct_v3_build_running",
                "direct_process_id": direct_process.pid,
                "store_output_dir": str(store_output_dir),
                "training_output_dir": str(training_output_dir),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        ooc_command = _ooc_helper_command(
            direct_process_id=direct_process.pid,
            store_output_dir=store_output_dir,
            training_output_dir=training_output_dir,
            args=args,
        )
        ooc_log = operational_log_dir / "ooc_v3_refresh.log"
        ooc_process = _start_logged(ooc_command, ooc_log)
        release_command = _release_command(
            ooc_process_id=ooc_process.pid,
            training_output_dir=training_output_dir,
            output_root=output_root,
            database=args.database.resolve(),
        )
        release_log = operational_log_dir / "release_v3_refresh.log"
        release_process = _start_logged(release_command, release_log)
        _atomic_write_json(
            status_path,
            {
                "schema_version": SCHEMA_VERSION,
                "status": "v3_downstream_started",
                "direct_process_id": direct_process.pid,
                "ooc_process_id": ooc_process.pid,
                "release_process_id": release_process.pid,
                "store_output_dir": str(store_output_dir),
                "training_output_dir": str(training_output_dir),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        _wait_for_expected_process(
            process_id=direct_process.pid,
            expected_fragments=(
                "build_portfolio_ml_direct_numeric_store.py",
                str(store_output_dir),
            ),
            poll_seconds=args.poll_seconds,
            status_path=status_path,
            wait_phase="direct_v3_build",
        )
        direct_returncode = direct_process.wait()
        if direct_returncode != 0:
            raise RuntimeError(
                "current direct-store build failed with exit code "
                f"{direct_returncode}"
            )
        direct_manifest_path, direct_manifest = _latest_direct_manifest(
            store_output_dir
        )
        _wait_for_expected_process(
            process_id=ooc_process.pid,
            expected_fragments=(
                "continue_ml_direct_ooc_after_store.py",
                str(training_output_dir),
            ),
            poll_seconds=args.poll_seconds,
            status_path=status_path,
            wait_phase="ooc_helper",
        )
        _wait_for_expected_process(
            process_id=release_process.pid,
            expected_fragments=(
                "continue_ml_release_after_ooc.py",
                str(training_output_dir),
            ),
            poll_seconds=args.poll_seconds,
            status_path=status_path,
            wait_phase="release_helper",
        )
        ooc_status = _read_json(
            training_output_dir / "continuation_status.json"
        )
        release_status = _read_json(
            training_output_dir / "post_ooc_followup_status.json"
        )
        complete = (
            ooc_status.get("status") == "complete"
            and release_status.get("status") == "complete"
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "complete" if complete else "blocked",
            "direct_manifest_path": str(direct_manifest_path),
            "direct_manifest_hash": direct_manifest.get("manifest_hash"),
            "ooc_status": ooc_status,
            "release_status": release_status,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        }
        _atomic_write_json(status_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if complete else 2
    except Exception as exc:  # noqa: BLE001 - preserve machine-readable state
        _cleanup_spawned_processes(
            release_process,
            ooc_process,
            direct_process,
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        }
        _atomic_write_json(status_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2


def _direct_build_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_portfolio_ml_direct_numeric_store.py"),
        "--raw-manifest",
        str(args.raw_manifest.resolve()),
        "--output-dir",
        str(args.store_output_dir.resolve()),
        "--training-as-of",
        str(args.training_as_of),
        "--benchmark-entity",
        str(args.benchmark_entity),
        "--minimum-train-dates",
        str(args.minimum_train_dates),
        "--test-date-count",
        str(args.test_date_count),
        "--purge-trading-days",
        str(args.purge_trading_days),
        "--embargo-trading-days",
        str(args.embargo_trading_days),
        "--batch-size",
        str(args.batch_size),
        "--workers",
        str(args.workers),
        "--memory-budget-mb",
        str(args.memory_budget_mb),
    ]
    if args.sector_membership is not None:
        command.extend(
            ["--sector-membership", str(args.sector_membership.resolve())]
        )
    if args.corporate_action_manifest is not None:
        command.extend(
            [
                "--corporate-action-manifest",
                str(args.corporate_action_manifest.resolve()),
            ]
        )
    if getattr(args, "formal_portfolio_ledger", None) is not None:
        command.extend(
            [
                "--formal-portfolio-ledger",
                str(args.formal_portfolio_ledger.resolve()),
            ]
        )
    if getattr(args, "formal_rule_champion_history", None) is not None:
        command.extend(
            [
                "--formal-rule-champion-history",
                str(args.formal_rule_champion_history.resolve()),
            ]
        )
    if args.temporary_storage_budget_bytes is not None:
        command.extend(
            [
                "--temporary-storage-budget-bytes",
                str(args.temporary_storage_budget_bytes),
            ]
        )
    if getattr(args, "persistent_storage_budget_bytes", None) is not None:
        command.extend(
            [
                "--persistent-storage-budget-bytes",
                str(args.persistent_storage_budget_bytes),
            ]
        )
    if getattr(args, "safety_reserve_bytes", None) is not None:
        command.extend(
            ["--safety-reserve-bytes", str(args.safety_reserve_bytes)]
        )
    return command


def _ooc_helper_command(
    *,
    direct_process_id: int,
    store_output_dir: Path,
    training_output_dir: Path,
    args: argparse.Namespace,
) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts" / "continue_ml_direct_ooc_after_store.py"),
        "--direct-process-id",
        str(direct_process_id),
        "--store-output-dir",
        str(store_output_dir),
        "--training-output-dir",
        str(training_output_dir),
        "--batch-size",
        str(args.batch_size),
        "--workers",
        str(args.workers),
        "--memory-budget-mb",
        str(args.memory_budget_mb),
        "--poll-seconds",
        str(args.poll_seconds),
    ]


def _release_command(
    *,
    ooc_process_id: int,
    training_output_dir: Path,
    output_root: Path,
    database: Path,
) -> list[str]:
    # Direct/OOC artifacts intentionally live below output/release_v4, while
    # downstream scheduled contracts (upstream proof, promotion evidence,
    # authority and daily orchestration) take the shared output root. Pass the
    # normalized root at this process boundary as well as inside the release
    # coordinator, so a long-lived maintainer cannot retain a stale legacy
    # command line after a code upgrade.
    resolved_output_root = output_root.resolve()
    resolved_training_root = training_output_dir.resolve()
    if (
        resolved_training_root.parent == resolved_output_root
        and resolved_output_root.name.casefold() == "release_v4"
    ):
        resolved_output_root = resolved_output_root.parent
    return [
        sys.executable,
        str(ROOT / "scripts" / "continue_ml_release_after_ooc.py"),
        "--ooc-helper-process-id",
        str(ooc_process_id),
        "--training-output-dir",
        str(training_output_dir),
        "--output-root",
        str(resolved_output_root),
        "--database",
        str(database),
        "--poll-seconds",
        "15",
    ]


def _wait_for_expected_process(
    *,
    process_id: int,
    expected_fragments: Sequence[str],
    poll_seconds: int,
    already_observed: bool = False,
    status_path: Path | None = None,
    wait_phase: str | None = None,
) -> None:
    if process_id <= 0 or poll_seconds <= 0:
        raise ValueError("process_id and poll_seconds must be positive")
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required for process custody") from exc
    expected = tuple(fragment.casefold() for fragment in expected_fragments)
    observed = already_observed
    while True:
        try:
            process = psutil.Process(process_id)
            command = " ".join(process.cmdline()).casefold()
            if any(fragment not in command for fragment in expected):
                raise RuntimeError(
                    f"process custody mismatch for pid {process_id}"
                )
            observed = True
            if status_path is not None:
                _publish_chain_heartbeat(
                    status_path=status_path,
                    process_id=process_id,
                    wait_phase=wait_phase or "process_wait",
                    command=command,
                )
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            if not observed:
                raise RuntimeError(
                    f"process {process_id} was not observed under custody"
                )
            return
        time.sleep(poll_seconds)


def _publish_chain_heartbeat(
    *,
    status_path: Path,
    process_id: int,
    wait_phase: str,
    command: str,
) -> None:
    payload = _read_json(status_path)
    payload.update(
        {
            "heartbeat_schema_version": _HEARTBEAT_SCHEMA_VERSION,
            "heartbeat_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "heartbeat_process_id": process_id,
            "heartbeat_phase": wait_phase,
            "heartbeat_command": command,
        }
    )
    _atomic_write_json(status_path, payload)


def _assert_expected_process(
    *,
    process_id: int,
    expected_fragments: Sequence[str],
) -> None:
    """Validate one PID before any sequential wait begins."""

    if process_id <= 0:
        raise ValueError("process_id must be positive")
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required for process custody") from exc
    expected = tuple(fragment.casefold() for fragment in expected_fragments)
    try:
        process = psutil.Process(process_id)
        command = " ".join(process.cmdline()).casefold()
    except (psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        raise RuntimeError(
            f"process {process_id} was not observed under custody"
        ) from exc
    if any(fragment not in command for fragment in expected):
        raise RuntimeError(f"process custody mismatch for pid {process_id}")


def _assert_no_active_target_processes(
    *,
    expected_specs: Sequence[tuple[Sequence[str], str]],
) -> None:
    """Fail closed before recovering a stopped chain.

    This recovery path is used only after the original supervisor itself was
    interrupted.  It may not start another builder while a matching target
    process is still active.
    """

    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required for process custody") from exc
    normalized_specs = tuple(
        (
            tuple(fragment.casefold() for fragment in fragments),
            label,
        )
        for fragments, label in expected_specs
    )
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            command = " ".join(process.info.get("cmdline") or []).casefold()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        for fragments, label in normalized_specs:
            if fragments and all(fragment in command for fragment in fragments):
                raise RuntimeError(
                    "cannot resume legacy chain while target process "
                    f"{label} (pid {process.pid}) is active"
                )


def _start_logged(command: Sequence[str], log_path: Path) -> subprocess.Popen[Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    try:
        return subprocess.Popen(
            list(command),
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        log.close()


def _cleanup_spawned_processes(
    *processes: subprocess.Popen[Any] | None,
) -> None:
    """Stop only child processes created by this supervisor after failure."""
    for process in processes:
        if process is None or process.poll() is not None:
            continue
        try:
            process.terminate()
        except OSError:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                continue
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


def _operational_log_dir(
    *,
    args: Any,
    primary_status_path: Path,
    store_output_dir: Path,
) -> Path:
    if args.operational_log_dir is not None:
        return args.operational_log_dir.resolve()
    if args.status_path is not None:
        return primary_status_path.parent / "logs"
    return store_output_dir / "logs"


def _latest_direct_manifest(
    output_root: Path,
) -> tuple[Path, dict[str, Any]]:
    from data_module import portfolio_ml_direct_numeric_store as direct_store

    pointer = _read_json(output_root / "latest_manifest.json")
    relative = pointer.get("manifest_path")
    if not isinstance(relative, str) or not relative:
        raise TypeError("direct latest pointer manifest_path is invalid")
    manifest_path = (output_root / relative).resolve()
    if not manifest_path.is_relative_to(output_root):
        raise ValueError("direct latest pointer escapes output root")
    manifest = _read_json(manifest_path)
    if pointer.get("manifest_hash") != manifest.get("manifest_hash"):
        raise ValueError("direct latest pointer hash mismatch")
    if manifest.get("status") != "complete":
        raise RuntimeError("direct manifest is not complete")
    execution = _mapping(manifest.get("execution"), "execution")
    if execution.get("direct_numeric_store") is not True:
        raise RuntimeError("latest manifest is not a direct numeric store")
    identity = _mapping(manifest.get("store_identity"), "store_identity")
    if identity.get("direct_builder_schema_version") != (
        direct_store.DIRECT_SCHEMA_VERSION
    ):
        raise RuntimeError(
            "latest direct store is not the current direct builder schema"
        )
    return manifest_path, manifest


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
            try:
                os.replace(temporary_path, path)
                break
            except PermissionError:
                if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                    raise
                time.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
