"""等待 direct numeric store 完成，驗證 custody 後自動啟動 OOC v5 訓練。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from data_module import portfolio_ml_out_of_core_store as store_module
from data_module.ml_storage_capacity import (  # noqa: E402
    authorize_heavy_chain_reservation_handoff_child,
    HEAVY_CHAIN_RESERVATION_HELD_ENV,
    MLStorageChainReservationHandoff,
    StorageCapacityError,
    heavy_chain_lock_path,
    resolve_heavy_chain_lock_path,
    forward_heavy_chain_reservation_handoff_environment,
    validate_heavy_chain_reservation_handoff,
)


_DIRECT_HEARTBEAT_SCHEMA_VERSION = "portfolio-ml-direct-heartbeat.v1"
_OOC_HEARTBEAT_SCHEMA_VERSION = "portfolio-ml-ooc-heartbeat.v1"
# OOC status/heartbeat writes are operational custody, but a transient
# Windows lock must not terminate a multi-hour training handoff.
_ATOMIC_REPLACE_RETRY_COUNT = 120
_ATOMIC_REPLACE_RETRY_DELAY_SECONDS = 0.5
_SECTOR_AUTO_DISCOVERY_DIRECTORY_NAMES = (
    "pit_sector_membership",
    "sector_membership",
    "sector_memberships",
    "ml_pit_sector_membership",
    "official_sector_membership",
    "formal_sector_membership",
    "sidecars",
)
_SECTOR_AUTO_DISCOVERY_FILE_NAMES = (
    "pit_sector_membership.json",
    "pit_sector_membership.jsonl",
    "pit_sector_membership.jsonl.gz",
    "sector_membership.json",
    "sector_membership.jsonl",
    "sector_membership.jsonl.gz",
)
_SECTOR_AUTO_DISCOVERY_SUFFIXES = frozenset({".json", ".jsonl", ".gz"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-process-id", type=int)
    parser.add_argument(
        "--resume-after-direct-store",
        action="store_true",
        help=(
            "resume an interrupted OOC run after the immutable direct store "
            "has already completed; revalidates the store without inventing "
            "live-process custody"
        ),
    )
    parser.add_argument("--store-output-dir", type=Path, required=True)
    parser.add_argument("--training-output-dir", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        help="shared release root used to verify the heavy-chain handoff",
    )
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument("--formal-portfolio-ledger", type=Path)
    parser.add_argument("--formal-rule-champion-history", type=Path)
    parser.add_argument("--ridge-alpha-bp", type=int, default=100)
    parser.add_argument("--logistic-iterations", type=int, default=6)
    parser.add_argument("--hgb-max-iter", type=int, default=100)
    parser.add_argument("--hgb-max-fit-rows", type=int, default=250_000)
    parser.add_argument("--poll-seconds", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.resume_after_direct_store and args.direct_process_id is None:
        parser.error(
            "--direct-process-id is required unless "
            "--resume-after-direct-store is set"
        )
    status_path = args.training_output_dir.resolve() / "continuation_status.json"
    store_output_dir = args.store_output_dir.resolve()
    training_output_dir = args.training_output_dir.resolve()
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else training_output_dir.parent.resolve()
    )
    handoff: MLStorageChainReservationHandoff | None = None
    handoff_lock_path = resolve_heavy_chain_lock_path(output_root)
    if handoff_lock_path is None:
        handoff_lock_path = heavy_chain_lock_path(output_root)
    try:
        handoff = validate_heavy_chain_reservation_handoff(handoff_lock_path)
    except (StorageCapacityError, TypeError, ValueError) as exc:
        _atomic_write_json(
            status_path,
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        print(
            json.dumps(_read_json(status_path), ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    # Publish a live, fail-closed state before waiting.  Without this write, a
    # previous run's terminal ``blocked`` payload can look current while the
    # helper is still legitimately waiting for the direct store process.
    if args.resume_after_direct_store:
        payload: dict[str, Any] = {
            "status": "resuming_after_direct_store",
            "store_output_dir": str(store_output_dir),
            "training_output_dir": str(training_output_dir),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        }
        heartbeat = _latest_direct_heartbeat(store_output_dir)
        if heartbeat is not None:
            payload["direct_store_heartbeat"] = heartbeat
        _atomic_write_json(status_path, payload)
    else:
        assert args.direct_process_id is not None
        _publish_waiting_status(
            status_path=status_path,
            direct_process_id=args.direct_process_id,
            store_output_dir=store_output_dir,
            training_output_dir=training_output_dir,
        )
    try:
        supervised_wait_started_ns: int | None = None
        if not args.resume_after_direct_store:
            assert args.direct_process_id is not None
            supervised_wait_started_ns = time.time_ns()
            _wait_for_expected_process(
                process_id=args.direct_process_id,
                expected_text=str(store_output_dir),
                poll_seconds=args.poll_seconds,
                status_path=status_path,
                store_output_dir=store_output_dir,
                training_output_dir=training_output_dir,
            )
        _atomic_write_json(
            status_path,
            {
                "status": "store_custody_validation_starting",
                "direct_process_id": args.direct_process_id,
                "store_output_dir": str(store_output_dir),
                "training_output_dir": str(training_output_dir),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        store_manifest_path, store_manifest = _validated_store_manifest(
            store_output_dir,
            minimum_pointer_mtime_ns=supervised_wait_started_ns,
        )
        store_manifest_path, store_manifest = _ensure_current_direct_schema(
            output_root=store_output_dir,
            manifest_path=store_manifest_path,
            manifest=store_manifest,
            status_path=status_path,
            batch_size=args.batch_size,
            workers=args.workers,
            memory_budget_mb=args.memory_budget_mb,
            formal_portfolio_ledger_path=args.formal_portfolio_ledger,
            formal_rule_champion_history_path=(
                args.formal_rule_champion_history
            ),
        )
        _atomic_write_json(
            status_path,
            {
                "status": "store_validated_training_starting",
                "store_manifest_path": str(store_manifest_path),
                "store_manifest_hash": store_manifest["manifest_hash"],
                "direct_store_complete": True,
                "full_market_ready": store_manifest["execution"][
                    "full_market_ready"
                ],
                "readiness_failed_checks": store_manifest["execution"][
                    "readiness_failed_checks"
                ],
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        command = [
            sys.executable,
            str(ROOT / "scripts" / "train_ml_allocation_out_of_core.py"),
            "--store-manifest",
            str(store_manifest_path),
            "--output-dir",
            str(args.training_output_dir.resolve()),
            "--batch-size",
            str(args.batch_size),
            "--workers",
            str(args.workers),
            "--memory-budget-mb",
            str(args.memory_budget_mb),
            "--ridge-alpha-bp",
            str(args.ridge_alpha_bp),
            "--logistic-iterations",
            str(args.logistic_iterations),
            "--hgb-max-iter",
            str(args.hgb_max_iter),
            "--hgb-max-fit-rows",
            str(args.hgb_max_fit_rows),
        ]
        completed_returncode = _run_training_with_heartbeat(
            command=command,
            status_path=status_path,
            training_output_dir=training_output_dir,
            store_manifest_path=store_manifest_path,
            store_manifest=store_manifest,
            poll_seconds=args.poll_seconds,
        )
        if completed_returncode != 0:
            raise RuntimeError(
                "OOC training command failed with exit code "
                f"{completed_returncode}"
            )
        training_path, training = _latest_manifest(
            args.training_output_dir.resolve()
        )
        replay_status_path = (
            training_path.parent
            / "artifacts"
            / "oos_portfolio_replay_inputs"
            / "build_status.json"
        )
        replay_status = (
            _read_json(replay_status_path)
            if replay_status_path.is_file()
            else {
                "status": "blocked",
                "blockers": ["replay_input_build_status_missing"],
            }
        )
        _atomic_write_json(
            status_path,
            {
                "status": "complete",
                "store_manifest_path": str(store_manifest_path),
                "store_manifest_hash": store_manifest["manifest_hash"],
                "training_manifest_path": str(training_path),
                "training_manifest_hash": training["manifest_hash"],
                "training_schema_version": training["schema_version"],
                "base_expert_count": training["base_expert_count"],
                "meta_fold_count": training["meta_fold_count"],
                "replay_input_status": replay_status["status"],
                "replay_input_blockers": replay_status.get(
                    "blockers",
                    [],
                ),
                "replay_input_manifest_path": replay_status.get(
                    "manifest_path"
                ),
                "replay_input_manifest_hash": replay_status.get(
                    "manifest_hash"
                ),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        print(
            json.dumps(
                _read_json(status_path),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (
        FileNotFoundError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        _atomic_write_json(
            status_path,
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            },
        )
        print(
            json.dumps(
                _read_json(status_path),
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if handoff is not None:
            handoff.close()


def _run_training_with_heartbeat(
    *,
    command: Sequence[str],
    status_path: Path,
    training_output_dir: Path,
    store_manifest_path: Path,
    store_manifest: Mapping[str, Any],
    poll_seconds: int,
) -> int:
    """Run OOC training while publishing live process custody.

    The release supervisor intentionally waits for this helper to exit before
    consuming the continuation status.  Polling a long-running child keeps the
    status file current for operators and recovery logic while preserving the
    immutable training artifacts; only process/lineage metadata is published
    until training exits.
    """
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    environment = forward_heavy_chain_reservation_handoff_environment(
        environment=os.environ
    )
    process = subprocess.Popen(command, cwd=ROOT, env=environment)
    if os.environ.get(HEAVY_CHAIN_RESERVATION_HELD_ENV) is not None:
        try:
            authorize_heavy_chain_reservation_handoff_child(
                process.pid,
                environment=environment,
            )
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
            raise
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        while True:
            returncode = process.poll()
            if returncode is not None:
                return returncode
            _atomic_write_json(
                status_path,
                {
                    "schema_version": _OOC_HEARTBEAT_SCHEMA_VERSION,
                    "status": "training_running",
                    "training_process_id": process.pid,
                    "training_started_at": started_at,
                    "training_heartbeat_at": datetime.now(
                        timezone.utc
                    ).isoformat(timespec="seconds"),
                    "training_command": list(command),
                    "store_manifest_path": str(store_manifest_path),
                    "store_manifest_hash": store_manifest["manifest_hash"],
                    "training_output_dir": str(training_output_dir),
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
            )
            time.sleep(poll_seconds)
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise


def _wait_for_expected_process(
    *,
    process_id: int,
    expected_text: str,
    poll_seconds: int,
    status_path: Path | None = None,
    store_output_dir: Path | None = None,
    training_output_dir: Path | None = None,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError(
            "psutil is required for process custody"
        ) from exc
    observed_expected_process = False
    while True:
        try:
            process = psutil.Process(process_id)
            command = " ".join(process.cmdline())
            _assert_expected_process_command(command, expected_text)
            observed_expected_process = True
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            if not observed_expected_process:
                raise RuntimeError(
                    "direct process was not observed under expected custody"
                )
            return
        if (
            status_path is not None
            and store_output_dir is not None
            and training_output_dir is not None
        ):
            _publish_waiting_status(
                status_path=status_path,
                direct_process_id=process_id,
                store_output_dir=store_output_dir,
                training_output_dir=training_output_dir,
            )
        time.sleep(poll_seconds)


def _assert_expected_process_command(
    command: str,
    expected_text: str,
) -> None:
    if expected_text.casefold() not in command.casefold():
        raise RuntimeError("direct process custody mismatch")


def _publish_waiting_status(
    *,
    status_path: Path,
    direct_process_id: int,
    store_output_dir: Path,
    training_output_dir: Path,
) -> None:
    payload: dict[str, Any] = {
        "status": "waiting_for_direct_store",
        "direct_process_id": direct_process_id,
        "store_output_dir": str(store_output_dir),
        "training_output_dir": str(training_output_dir),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    heartbeat = _latest_direct_heartbeat(
        store_output_dir,
        direct_process_id=direct_process_id,
    )
    if heartbeat is not None:
        payload["direct_store_heartbeat"] = heartbeat
    _atomic_write_json(status_path, payload)


def _latest_direct_heartbeat(
    output_root: Path,
    *,
    direct_process_id: int | None = None,
) -> dict[str, Any] | None:
    runs_root = output_root / "runs"
    if not runs_root.is_dir():
        return None
    candidates = sorted(
        (
            path
            for path in runs_root.glob("*/heartbeat.json")
            if path.is_file()
        ),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for path in candidates:
        try:
            payload = _read_json(path)
        except (OSError, TypeError, ValueError):
            continue
        if payload.get("schema_version") != (
            _DIRECT_HEARTBEAT_SCHEMA_VERSION
        ):
            continue
        if payload.get("run_id") != path.parent.name:
            continue
        if (
            direct_process_id is not None
            and not _heartbeat_pid_matches_custody(
                payload.get("pid"),
                direct_process_id,
            )
        ):
            continue
        return payload
    return None


def _heartbeat_pid_matches_custody(
    heartbeat_pid: object,
    supervised_process_id: int,
) -> bool:
    """Accept an exact PID or a live Python child under the supervised PID.

    On Windows, invoking a venv interpreter can leave a launcher PID in the
    supervisor while the actual interpreter records its own PID in the direct
    heartbeat.  Require the recorded process to be alive and in the launcher
    ancestry before mirroring it; a stale or unrelated heartbeat is ignored.
    The exact-PID path remains available for test doubles and environments
    where the launcher and worker are the same process.
    """
    if isinstance(heartbeat_pid, bool) or not isinstance(heartbeat_pid, int):
        return False
    if heartbeat_pid == supervised_process_id:
        return True
    try:
        import psutil
    except ImportError:
        return False
    try:
        process = psutil.Process(heartbeat_pid)
        seen: set[int] = set()
        while process.pid not in seen:
            seen.add(process.pid)
            parent = process.parent()
            if parent is None:
                return False
            if parent.pid == supervised_process_id:
                return True
            process = parent
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    return False


def _ensure_current_direct_schema(
    *,
    output_root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    status_path: Path,
    batch_size: int,
    workers: int,
    memory_budget_mb: int,
    formal_portfolio_ledger_path: Path | None = None,
    formal_rule_champion_history_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Automatically refresh a direct store when its immutable inputs change.

    A direct store is immutable once published.  When the builder contract
    advances, rebuild into a new run under the same output root instead of
    mutating the old run or pretending its artifacts satisfy the new schema.
    The raw and official manifests are discovered by their recorded hashes.
    A current v4 store with no sector sidecar is also probed for a newly
    deposited, canonical PIT sidecar; an accepted sidecar triggers a new
    immutable v4 run, while missing, invalid, or ambiguous candidates leave
    the current publication untouched.
    """

    from data_module import portfolio_ml_direct_numeric_store as direct_store

    store_identity = _mapping(
        manifest.get("store_identity"),
        field_name="store_identity",
    )
    direct_identity = _mapping(
        store_identity.get("direct_identity"),
        field_name="store_identity.direct_identity",
    )
    current_schema = direct_identity.get(
        "schema_version",
        store_identity.get("direct_builder_schema_version"),
    )
    sector_membership_path: Path | None = None
    formal_portfolio_ledger_path = _hash_bound_optional_input(
        direct_identity,
        path_field="formal_portfolio_ledger_path",
        hash_field="formal_portfolio_ledger_file_hash",
        explicit_path=formal_portfolio_ledger_path,
        label="formal portfolio ledger",
    )
    formal_rule_champion_history_path = _hash_bound_optional_input(
        direct_identity,
        path_field="formal_rule_champion_history_path",
        hash_field="formal_rule_champion_history_file_hash",
        explicit_path=formal_rule_champion_history_path,
        label="formal Rule Champion history",
    )
    if current_schema == direct_store.DIRECT_SCHEMA_VERSION:
        sector_membership_path = discover_valid_sector_membership(
            output_root=output_root,
            training_as_of=_required_text(
                direct_identity.get("training_as_of"),
                "direct_identity.training_as_of",
            ),
        )
        if (
            sector_membership_path is None
            and formal_portfolio_ledger_path is None
            and formal_rule_champion_history_path is None
        ):
            return manifest_path, manifest

    raw_manifest_path = _discover_hash_bound_manifest(
        output_root=output_root,
        root_name="ml_pit_year_shards",
        relative_globs=(
            "*/all_field_enriched/manifest.json",
            "*/core_long_history/manifest.json",
        ),
        expected_file_hash=_required_sha256_text(
            direct_identity.get("raw_manifest_file_hash"),
            "direct_identity.raw_manifest_file_hash",
        ),
        expected_manifest_hash=_required_sha256_text(
            direct_identity.get("raw_manifest_hash"),
            "direct_identity.raw_manifest_hash",
        ),
        label="raw PIT manifest",
    )
    corporate_manifest_path: Path | None = None
    corporate_file_hash = _required_sha256_text(
        direct_identity.get("corporate_action_manifest_file_hash"),
        "direct_identity.corporate_action_manifest_file_hash",
    )
    if not _is_zero_sha256(corporate_file_hash):
        corporate_manifest_path = _discover_hash_bound_manifest(
            output_root=output_root,
            root_name="official_market_events",
            relative_globs=("*/manifest.json",),
            expected_file_hash=corporate_file_hash,
            expected_manifest_hash=None,
            label="official market-event manifest",
        )

    sector_hash_value = direct_identity.get("sector_membership_file_hash")
    if current_schema != direct_store.DIRECT_SCHEMA_VERSION:
        # Older direct manifests used JSON null when no PIT sector sidecar was
        # supplied.  Preserve that absence so the refresh can publish the
        # current immutable schema while keeping the formal gate fail-closed.
        sector_file_hash = (
            "sha256:" + ("0" * 64)
            if sector_hash_value is None
            else _required_sha256_text(
                sector_hash_value,
                "direct_identity.sector_membership_file_hash",
            )
        )
        if not _is_zero_sha256(sector_file_hash):
            sector_membership_path = _discover_hash_bound_sector_sidecar(
                output_root=output_root,
                expected_file_hash=sector_file_hash,
                training_as_of=_required_text(
                    direct_identity.get("training_as_of"),
                    "direct_identity.training_as_of",
                ),
            )

    execution = _mapping(manifest.get("execution"), field_name="execution")
    temporary_budget = execution.get("temporary_storage_budget_bytes")
    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_portfolio_ml_direct_numeric_store.py"),
        "--raw-manifest",
        str(raw_manifest_path),
        "--output-dir",
        str(output_root),
        "--training-as-of",
        _required_text(
            direct_identity.get("training_as_of"),
            "direct_identity.training_as_of",
        ),
        "--benchmark-entity",
        _required_text(
            direct_identity.get("benchmark_entity_id"),
            "direct_identity.benchmark_entity_id",
        ),
        "--minimum-train-dates",
        str(_required_positive_int(
            direct_identity.get("minimum_train_dates"),
            "direct_identity.minimum_train_dates",
        )),
        "--test-date-count",
        str(_required_positive_int(
            direct_identity.get("test_date_count"),
            "direct_identity.test_date_count",
        )),
        "--purge-trading-days",
        str(_required_positive_int(
            direct_identity.get("purge_trading_days"),
            "direct_identity.purge_trading_days",
        )),
        "--embargo-trading-days",
        str(_required_positive_int(
            direct_identity.get("embargo_trading_days"),
            "direct_identity.embargo_trading_days",
        )),
        "--batch-size",
        str(batch_size),
        "--workers",
        str(workers),
        "--memory-budget-mb",
        str(memory_budget_mb),
    ]
    if corporate_manifest_path is not None:
        command.extend(
            ["--corporate-action-manifest", str(corporate_manifest_path)]
        )
    if sector_membership_path is not None:
        command.extend(["--sector-membership", str(sector_membership_path)])
    if formal_portfolio_ledger_path is not None:
        command.extend(
            ["--formal-portfolio-ledger", str(formal_portfolio_ledger_path)]
        )
    if formal_rule_champion_history_path is not None:
        command.extend(
            [
                "--formal-rule-champion-history",
                str(formal_rule_champion_history_path),
            ]
        )
    if isinstance(temporary_budget, int) and not isinstance(
        temporary_budget, bool
    ):
        command.extend(
            ["--temporary-storage-budget-bytes", str(temporary_budget)]
        )

    refresh_started_ns = time.time_ns()
    _atomic_write_json(
        status_path,
        {
            "status": "direct_schema_refresh_starting",
            "legacy_manifest_path": str(manifest_path),
            "legacy_manifest_hash": manifest.get("manifest_hash"),
            "legacy_direct_schema": current_schema,
            "target_direct_schema": direct_store.DIRECT_SCHEMA_VERSION,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        },
    )
    child_environment = forward_heavy_chain_reservation_handoff_environment(
        environment=os.environ
    )
    process = subprocess.Popen(command, cwd=ROOT, env=child_environment)
    if os.environ.get(HEAVY_CHAIN_RESERVATION_HELD_ENV) is not None:
        try:
            authorize_heavy_chain_reservation_handoff_child(
                process.pid,
                environment=child_environment,
            )
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
            raise
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(
            "direct schema refresh command failed with exit code "
            f"{return_code}"
        )
    return _validated_store_manifest(
        output_root,
        minimum_pointer_mtime_ns=refresh_started_ns,
    )


def discover_valid_sector_membership(
    *,
    output_root: Path,
    training_as_of: str,
    expected_file_hash: str | None = None,
) -> Path | None:
    """Find one validated PIT sector sidecar without mutating any source.

    Discovery is deliberately narrow: only explicit sector-sidecar
    directories/file names under the direct output lineage (or the optional
    environment-provided path) are inspected.  Every candidate is then
    passed through the production assembler's canonical-manifest, accepted
    status, lineage, license, source-hash, availability, and cutoff checks.
    A current company registry, a research artifact, or an ambiguous set of
    valid files is never selected implicitly.
    """

    if expected_file_hash is not None:
        _required_sha256_text(expected_file_hash, "expected sector file hash")
    matches: list[Path] = []
    for candidate in _sector_sidecar_candidates(output_root):
        try:
            if expected_file_hash is not None and _file_sha256(candidate) != expected_file_hash:
                continue
            _validate_sector_sidecar(candidate, training_as_of=training_as_of)
        except (OSError, TypeError, ValueError, sqlite3.Error):
            continue
        matches.append(candidate)
    if len(matches) > 1:
        raise RuntimeError(
            "automatic PIT sector sidecar discovery is ambiguous: "
            f"{len(matches)} validated candidates"
        )
    return matches[0] if matches else None


def _discover_hash_bound_sector_sidecar(
    *,
    output_root: Path,
    expected_file_hash: str,
    training_as_of: str,
) -> Path:
    candidate = discover_valid_sector_membership(
        output_root=output_root,
        training_as_of=training_as_of,
        expected_file_hash=expected_file_hash,
    )
    if candidate is None:
        raise RuntimeError(
            "direct schema refresh cannot discover hash-bound sector sidecar"
        )
    return candidate


def _sector_sidecar_candidates(output_root: Path) -> tuple[Path, ...]:
    roots: set[Path] = set()
    resolved_output = output_root.resolve()
    current = resolved_output
    # Include the direct store, its release/output parents, and DATA_ROOT;
    # never recurse from a broad drive or repository root.
    for _ in range(4):
        roots.add(current)
        if current.parent == current:
            break
        current = current.parent

    candidates: set[Path] = set()
    configured = os.environ.get("BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH")
    if configured and configured.strip():
        candidates.add(Path(configured).expanduser().resolve())
    for root in roots:
        for file_name in _SECTOR_AUTO_DISCOVERY_FILE_NAMES:
            candidates.add(root / file_name)
        for directory_name in _SECTOR_AUTO_DISCOVERY_DIRECTORY_NAMES:
            directory = root / directory_name
            if not directory.is_dir():
                continue
            for candidate in directory.rglob("*"):
                if candidate.is_file() and candidate.suffix.lower() in _SECTOR_AUTO_DISCOVERY_SUFFIXES:
                    candidates.add(candidate.resolve())
    return tuple(sorted(path for path in candidates if path.is_file()))


def _validate_sector_sidecar(path: Path, *, training_as_of: str) -> None:
    cutoff = dataset_assembler._available_datetime(
        training_as_of,
        field_name="training_as_of",
    )
    connection = sqlite3.connect(":memory:")
    try:
        dataset_assembler._initialize_spool(connection)
        _manifest_hash, row_count = dataset_assembler._spool_sector_memberships(
            connection,
            path,
            training_as_of=cutoff,
        )
        if row_count <= 0:
            raise ValueError("PIT sector sidecar has no accepted rows")
    finally:
        connection.close()


def _discover_hash_bound_manifest(
    *,
    output_root: Path,
    root_name: str,
    relative_globs: Sequence[str],
    expected_file_hash: str,
    expected_manifest_hash: str | None,
    label: str,
) -> Path:
    candidates: set[Path] = set()
    for ancestor in output_root.parents:
        root = ancestor / root_name / "runs"
        if not root.is_dir():
            continue
        for relative_glob in relative_globs:
            candidates.update(root.glob(relative_glob))
    matches: list[Path] = []
    for candidate in sorted(path.resolve() for path in candidates):
        try:
            if _file_sha256(candidate) != expected_file_hash:
                continue
            payload = _read_json(candidate)
        except (OSError, TypeError, ValueError):
            continue
        if expected_manifest_hash is not None and payload.get(
            "manifest_hash"
        ) != expected_manifest_hash:
            continue
        matches.append(candidate)
    if len(matches) != 1:
        raise RuntimeError(
            f"{label} discovery is not unique: {len(matches)}"
        )
    return matches[0]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1_048_576)
            if not chunk:
                break
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value


def _required_sha256_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise TypeError(f"{field_name} must be a sha256 string")
    if len(value) != len("sha256:") + 64:
        raise ValueError(f"{field_name} must be a sha256 string")
    return value


def _is_zero_sha256(value: str) -> bool:
    return value == "sha256:" + ("0" * 64)


def _hash_bound_optional_input(
    direct_identity: Mapping[str, Any],
    *,
    path_field: str,
    hash_field: str,
    explicit_path: Path | None,
    label: str,
) -> Path | None:
    expected_value = direct_identity.get(hash_field)
    if expected_value is None:
        return explicit_path.resolve() if explicit_path is not None else None
    expected_hash = _required_sha256_text(expected_value, hash_field)
    if _is_zero_sha256(expected_hash):
        return explicit_path.resolve() if explicit_path is not None else None
    candidate_value = (
        str(explicit_path.resolve())
        if explicit_path is not None
        else direct_identity.get(path_field)
    )
    candidate = Path(_required_text(candidate_value, path_field)).resolve()
    if not candidate.is_file():
        raise RuntimeError(f"{label} custody file is missing")
    if _file_sha256(candidate) != expected_hash:
        raise RuntimeError(f"{label} custody file hash mismatch")
    return candidate


def _required_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TypeError(f"{field_name} must be a positive integer")
    return value


def _validated_store_manifest(
    output_root: Path,
    *,
    minimum_pointer_mtime_ns: int | None = None,
) -> tuple[Path, dict[str, Any]]:
    latest_pointer = output_root / "latest_manifest.json"
    if minimum_pointer_mtime_ns is not None:
        if not latest_pointer.is_file():
            raise RuntimeError("direct store latest pointer is missing")
        if latest_pointer.stat().st_mtime_ns < minimum_pointer_mtime_ns:
            raise RuntimeError(
                "direct store latest pointer was not refreshed after "
                "supervised process start"
            )
    manifest_path, manifest = _latest_manifest(output_root)
    execution = _mapping(manifest.get("execution"), field_name="execution")
    if manifest.get("status") != "complete":
        raise RuntimeError("direct store manifest is not complete")
    if execution.get("direct_numeric_store") is not True:
        raise RuntimeError("latest store is not a direct numeric store")
    if execution.get("direct_store_complete") is not True:
        raise RuntimeError("direct numeric store is incomplete")
    if execution.get("memory_budget_enforced") is not True:
        raise RuntimeError("direct store memory budget was not enforced")
    if execution.get("within_memory_budget") is not True:
        raise RuntimeError("direct store exceeded memory budget")
    preflight = _mapping(
        execution.get("temporary_storage_preflight"),
        field_name="temporary_storage_preflight",
    )
    if preflight.get("within_budget") is not True:
        raise RuntimeError("direct store temporary preflight failed")
    if manifest.get("formal_source_only") is not True:
        raise RuntimeError("direct store is not formal-source-only")
    if manifest.get("research_shadow_included") is not False:
        raise RuntimeError("direct store includes research shadow data")
    if int(manifest.get("fold_count", 0)) < 4:
        raise RuntimeError("direct store has fewer than four folds")
    if int(manifest.get("row_count", 0)) <= 0:
        raise RuntimeError("direct store has no numeric rows")
    _validate_direct_artifact_custody(
        manifest_path=manifest_path,
        manifest=manifest,
    )
    return manifest_path, manifest


def _validate_direct_artifact_custody(
    *,
    manifest_path: Path,
    manifest: Mapping[str, Any],
) -> None:
    """Revalidate immutable direct artifacts before starting OOC training."""

    expected_manifest_hash = _required_sha256_text(
        manifest.get("manifest_hash"),
        "direct manifest_hash",
    )
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_hash", None)
    if store_module._sha256_json(manifest_body) != expected_manifest_hash:
        raise RuntimeError("direct manifest canonical hash mismatch")

    run_directory = manifest_path.parent.resolve()
    checkpoint_path = run_directory / "checkpoint.json"
    checkpoint = _read_json(checkpoint_path)
    if checkpoint.get("complete") is not True:
        raise RuntimeError("direct checkpoint is incomplete")
    if checkpoint.get("run_id") != manifest.get("run_id"):
        raise RuntimeError("direct checkpoint run_id mismatch")
    if checkpoint.get("manifest_hash") != expected_manifest_hash:
        raise RuntimeError("direct checkpoint manifest hash mismatch")
    if checkpoint.get("manifest_file_hash") != _file_sha256(manifest_path):
        raise RuntimeError("direct checkpoint manifest file hash mismatch")

    year_manifests = store_module._mapping_sequence(
        manifest.get("years"),
        field_name="years",
    )
    checkpoint_years = store_module._mapping_sequence(
        checkpoint.get("completed_years"),
        field_name="checkpoint.completed_years",
    )
    checkpoint_by_year = {
        int(item["year"]): item for item in checkpoint_years
    }
    manifest_years = {int(item["year"]) for item in year_manifests}
    if manifest_years != set(checkpoint_by_year):
        raise RuntimeError("direct checkpoint years mismatch")
    for year_manifest in year_manifests:
        year = int(year_manifest["year"])
        if not store_module._verify_year_directory(
            year_directory=run_directory / f"year={year:04d}",
            expected_manifest_hash=str(year_manifest["manifest_hash"]),
        ):
            raise RuntimeError(
                f"direct year artifact custody mismatch: {year}"
            )
        checkpoint_entry = checkpoint_by_year[year]
        if checkpoint_entry.get("manifest_hash") != year_manifest.get(
            "manifest_hash"
        ):
            raise RuntimeError(
                f"direct checkpoint year manifest hash mismatch: {year}"
            )
        year_directory = run_directory / f"year={year:04d}"
        if checkpoint_entry.get("manifest_file_hash") != _file_sha256(
            year_directory / "manifest.json"
        ):
            raise RuntimeError(
                f"direct checkpoint year manifest file hash mismatch: {year}"
            )
        if checkpoint_entry.get("carry_file_hash") != _file_sha256(
            year_directory / "carry.state.gz"
        ):
            raise RuntimeError(
                f"direct checkpoint carry hash mismatch: {year}"
            )

    folds_directory = run_directory / "folds"
    for fold_manifest in store_module._mapping_sequence(
        manifest.get("folds"),
        field_name="folds",
    ):
        if not store_module._verify_fold_manifest(
            fold_manifest,
            folds_directory=folds_directory,
        ):
            raise RuntimeError("direct fold artifact custody mismatch")


def _latest_manifest(output_root: Path) -> tuple[Path, dict[str, Any]]:
    pointer = _read_json(output_root / "latest_manifest.json")
    relative = pointer.get("manifest_path")
    if not isinstance(relative, str) or not relative:
        raise TypeError("latest pointer manifest_path must be non-empty text")
    manifest_path = (output_root / relative).resolve()
    if not manifest_path.is_relative_to(output_root.resolve()):
        raise ValueError("latest pointer escapes output root")
    return manifest_path, _read_json(manifest_path)


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                    raise
                time.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)
    finally:
        temporary.unlink(missing_ok=True)


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
