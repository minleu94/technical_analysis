"""自動啟動並持續維護 Direct v4 → OOC v5 的 fail-closed refresh chain。

此 wrapper 只負責從已驗證的 immutable pointer 組合 process-custody 參數，
再交由既有 maintainer 執行。它不建立 raw data、不寫入來源 SQLite、不建立
sector history，也不改變 formal promotion、alpha 或 broker gate。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from data_module.ml_storage_capacity import (
    BYTES_PER_GIB,
    MLStorageCapacityBudget,
    directory_size_bytes,
    evaluate_capacity,
)
from scripts import maintain_ml_direct_v3_refresh_chain as maintenance


_DEFAULT_DATA_ROOT = Path(r"D:\Min\Python\Project\FA_Data")
_RAW_ROOT_NAME = "ml_pit_year_shards"
_DEFAULT_MINIMUM_FREE_SPACE_BYTES = 20 * 1024**3
_DEFAULT_DIRECT_PERSISTENT_STORAGE_BUDGET_BYTES = 35 * BYTES_PER_GIB
_DEFAULT_DIRECT_TEMPORARY_STORAGE_BUDGET_BYTES = 40 * BYTES_PER_GIB


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--benchmark-entity", default="TAIEX")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--retry-delay-seconds", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument(
        "--minimum-free-space-bytes",
        type=int,
        default=_DEFAULT_MINIMUM_FREE_SPACE_BYTES,
        help=(
            "fail closed before launching Direct/OOC when the output "
            "filesystem has less free space than this threshold"
        ),
    )
    parser.add_argument(
        "--persistent-storage-budget-bytes",
        "--persistent-new-bytes-budget",
        dest="persistent_storage_budget_bytes",
        type=int,
        default=_DEFAULT_DIRECT_PERSISTENT_STORAGE_BUDGET_BYTES,
        help=(
            "maximum bytes of new persistent Direct/OOC artifacts for one "
            "chain"
        ),
    )
    parser.add_argument(
        "--temporary-storage-budget-bytes",
        "--temporary-peak-bytes-budget",
        dest="temporary_storage_budget_bytes",
        type=int,
        default=_DEFAULT_DIRECT_TEMPORARY_STORAGE_BUDGET_BYTES,
        help=(
            "maximum Direct temporary workspace peak; explicitly forwarded "
            "to the Direct child"
        ),
    )
    parser.add_argument(
        "--safety-reserve-bytes",
        type=int,
        help="filesystem bytes that must remain free after the chain",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "resolve and record immutable inputs plus storage headroom, then "
            "stop before acquiring the maintenance lock or launching Direct/OOC"
        ),
    )
    return parser


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _required_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid {field_name}")
    return maintenance.ooc_continuation._required_sha256_text(
        value, field_name
    )


def _capacity_budget_from_args(args: argparse.Namespace) -> MLStorageCapacityBudget:
    """將新容量參數與舊 headroom 參數組合成單一政策。"""

    reserve = getattr(args, "safety_reserve_bytes", None)
    if reserve is None:
        reserve = getattr(
            args,
            "minimum_free_space_bytes",
            _DEFAULT_MINIMUM_FREE_SPACE_BYTES,
        )
    if isinstance(reserve, bool) or not isinstance(reserve, int):
        raise TypeError("safety_reserve_bytes must be integer")
    return MLStorageCapacityBudget(
        persistent_new_bytes_budget=getattr(
            args,
            "persistent_storage_budget_bytes",
            None,
        ),
        temporary_peak_bytes_budget=getattr(
            args,
            "temporary_storage_budget_bytes",
            None,
        ),
        safety_reserve_bytes=reserve,
    )


def _live_maintenance_owner(training_output_dir: Path) -> int | None:
    """Return the verified maintainer owner from the instance lock, if any."""

    state, owner_pid = _maintenance_lock_state(training_output_dir)
    return owner_pid if state == "verified" else None


def _maintenance_lock_state(
    training_output_dir: Path,
) -> tuple[str, int | None]:
    """Classify lock custody without deleting or mutating the lock."""

    lock_path = training_output_dir.resolve() / ".ml_direct_chain_maintenance.lock"
    try:
        owner_pid = int(lock_path.read_text(encoding="utf-8").strip())
        process = maintenance.psutil.Process(owner_pid)
    except (
        FileNotFoundError,
        ValueError,
    ):
        return "missing_or_invalid", None
    except maintenance.psutil.NoSuchProcess:
        return "stale", owner_pid
    except (OSError, maintenance.psutil.AccessDenied):
        return "owner_lock_unverifiable", owner_pid
    try:
        command_line = process.cmdline()
    except maintenance.psutil.AccessDenied:
        return "owner_lock_unverifiable", owner_pid
    except maintenance.psutil.NoSuchProcess:
        return "stale", owner_pid
    except OSError:
        return "owner_lock_unverifiable", owner_pid
    if maintenance._is_matching_maintenance_owner(
        command_line, training_output_dir
    ):
        return "verified", owner_pid
    return "mismatched", owner_pid


def resolve_latest_raw_dataset(output_root: Path) -> tuple[Path, str]:
    """解析並驗證 pointer-bound、全市場 raw PIT dataset。"""

    publication_root = output_root.resolve() / _RAW_ROOT_NAME
    pointer = _read_json(publication_root / "latest_manifest.json")
    if pointer.get("schema_version") != "ml-pit-year-shards-pointer.v1":
        raise ValueError("unsupported raw PIT pointer schema")
    pointer_hash = _required_sha256(
        pointer.get("manifest_hash"), "raw PIT pointer manifest_hash"
    )
    publication_path = maintenance._resolve_child(
        publication_root, pointer.get("manifest_path")
    )
    if publication_path is None:
        raise ValueError("raw PIT publication path escapes publication root")
    publication = _read_json(publication_path)
    if (
        publication.get("schema_version") != "ml-pit-year-shards.v1"
        or publication.get("publication_id") != pointer.get("publication_id")
        or publication.get("manifest_hash") != pointer_hash
    ):
        raise ValueError("raw PIT pointer does not bind publication")
    logical_publication = dict(publication)
    logical_publication.pop("manifest_hash", None)
    if maintenance._canonical_sha256(logical_publication) != pointer_hash:
        raise ValueError("raw PIT publication canonical hash mismatch")

    scope = publication.get("scope")
    if not isinstance(scope, dict) or scope.get("all_universe") is not True:
        raise ValueError("raw PIT publication is not all-universe")
    datasets = publication.get("datasets")
    if not isinstance(datasets, dict):
        raise ValueError("raw PIT publication datasets missing")
    dataset_meta = datasets.get("all_field_enriched")
    if not isinstance(dataset_meta, dict):
        raise ValueError("all_field_enriched dataset missing")
    dataset_path = maintenance._resolve_child(
        publication_path.parent, dataset_meta.get("manifest_path")
    )
    if dataset_path is None:
        raise ValueError("raw PIT dataset path escapes publication root")
    dataset = _read_json(dataset_path)
    dataset_assembler._validate_raw_dataset_manifest(dataset)
    dataset_hash = _required_sha256(
        dataset.get("manifest_hash"), "raw PIT dataset manifest_hash"
    )
    if (
        dataset.get("dataset_id") != "all_field_enriched"
        or dataset_meta.get("manifest_hash") != dataset_hash
        or dataset.get("decision_at") != publication.get("decision_at")
        or dataset.get("history_start_date")
        != publication.get("history_start_date")
    ):
        raise ValueError("raw PIT dataset metadata does not bind publication")
    decision_at = dataset_assembler._decision_datetime(
        str(dataset.get("decision_at"))
    )
    if decision_at > datetime.now(timezone.utc):
        raise ValueError("raw PIT decision_at is in the future")
    return dataset_path.resolve(), decision_at.isoformat()


def _resolve_inputs(args: argparse.Namespace) -> tuple[list[str], dict[str, Any]]:
    data_root = (args.data_root or _DEFAULT_DATA_ROOT).resolve()
    output_root = (args.output_root or data_root / "output").resolve()
    release_root = (output_root / "release_v4").resolve()
    database = (args.database or data_root / "sqlite" / "twstock.db").resolve()
    store_output_dir = (
        release_root / "portfolio_ml_direct_numeric_production_v4_v2"
    ).resolve()
    training_output_dir = (
        release_root / "portfolio_ml_direct_ooc_training_production_v4_v5"
    ).resolve()

    raw_manifest, training_as_of = resolve_latest_raw_dataset(release_root)
    helper_args = argparse.Namespace(
        output_root=release_root,
        store_output_dir=store_output_dir,
    )
    event_result = maintenance._validated_latest_corporate_action_manifest(
        helper_args,
        training_as_of=training_as_of,
    )
    corporate_action_manifest = (
        None if event_result is None else event_result[0]
    )

    sector_membership: Path | None = None
    direct_identity = maintenance._current_direct_identity(helper_args)
    if direct_identity is not None:
        raw_sector_hash = direct_identity.get("sector_membership_file_hash")
        if raw_sector_hash is not None and not maintenance.ooc_continuation._is_zero_sha256(
            str(raw_sector_hash)
        ):
            sector_membership = (
                maintenance.ooc_continuation._discover_hash_bound_sector_sidecar(
                    output_root=store_output_dir,
                    expected_file_hash=str(raw_sector_hash),
                    training_as_of=training_as_of,
                )
            )

    command = [
        sys.executable,
        str(ROOT / "scripts" / "maintain_ml_direct_v3_refresh_chain.py"),
        "--raw-manifest",
        str(raw_manifest),
        "--store-output-dir",
        str(store_output_dir),
        "--training-output-dir",
        str(training_output_dir),
        "--output-root",
        str(release_root),
        "--database",
        str(database),
        "--training-as-of",
        training_as_of,
        "--benchmark-entity",
        str(args.benchmark_entity),
        "--minimum-train-dates",
        "252",
        "--test-date-count",
        "63",
        "--purge-trading-days",
        "60",
        "--embargo-trading-days",
        "5",
        "--batch-size",
        str(args.batch_size),
        "--workers",
        str(args.workers),
        "--memory-budget-mb",
        str(args.memory_budget_mb),
        "--poll-seconds",
        str(args.poll_seconds),
        "--retry-delay-seconds",
        str(args.retry_delay_seconds),
        "--watch-formal-inputs",
    ]
    for flag, value in (
        (
            "--persistent-storage-budget-bytes",
            getattr(args, "persistent_storage_budget_bytes", None),
        ),
        (
            "--temporary-storage-budget-bytes",
            getattr(args, "temporary_storage_budget_bytes", None),
        ),
        (
            "--safety-reserve-bytes",
            getattr(args, "safety_reserve_bytes", None),
        ),
    ):
        if value is not None:
            command.extend([flag, str(value)])
    if corporate_action_manifest is not None:
        command.extend(["--corporate-action-manifest", str(corporate_action_manifest)])
    if sector_membership is not None:
        command.extend(["--sector-membership", str(sector_membership)])
    metadata = {
        "raw_manifest": str(raw_manifest),
        "raw_manifest_hash": _required_sha256(
            _read_json(raw_manifest).get("manifest_hash"),
            "raw PIT dataset manifest_hash",
        ),
        "training_as_of": training_as_of,
        "store_output_dir": str(store_output_dir),
        "training_output_dir": str(training_output_dir),
        "database": str(database),
        "database_mode": "ro",
        "query_only": True,
        "writes_source_database": False,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "capacity_budget": _capacity_budget_from_args(args).as_dict(),
    }
    return command, metadata


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _storage_preflight(
    path: Path,
    *,
    minimum_free_space_bytes: int,
) -> dict[str, Any]:
    """Read filesystem headroom without creating, deleting, or mutating data."""

    if minimum_free_space_bytes <= 0:
        raise ValueError("minimum-free-space-bytes must be positive")
    probe_path = path if path.exists() else path.parent
    usage = shutil.disk_usage(probe_path)
    free_bytes = int(usage.free)
    minimum = int(minimum_free_space_bytes)
    return {
        "probe_path": str(probe_path),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": free_bytes,
        "minimum_free_space_bytes": minimum,
        "within_minimum_free_space": free_bytes >= minimum,
    }


def _run_maintainer_with_heartbeat(
    command: list[str],
    *,
    status_path: Path,
    running_status: dict[str, Any],
    training_output_dir: Path,
    poll_seconds: int,
) -> int:
    """Run the maintainer while refreshing verified process custody.

    The maintainer intentionally owns the long-lived instance lock.  Polling
    the child instead of using ``subprocess.run`` lets the scheduled status
    expose the actual lock owner after the child has acquired it, rather than
    retaining the bootstrap-time observation indefinitely.
    """

    process = subprocess.Popen(command, cwd=ROOT)
    while True:
        return_code = process.poll()
        if return_code is not None:
            return int(return_code)
        lock_state, owner_pid = _maintenance_lock_state(training_output_dir)
        _write_status(
            status_path,
            {
                **running_status,
                "status": "running",
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "maintenance_lock_state": lock_state,
                "maintenance_owner_process_id": owner_pid,
            },
        )
        time.sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.poll_seconds <= 0 or args.retry_delay_seconds < 0:
        raise ValueError("poll/retry intervals must be non-negative and poll > 0")
    data_root = (args.data_root or _DEFAULT_DATA_ROOT).resolve()
    output_root = (args.output_root or data_root / "output").resolve()
    status_path = (
        args.status_path
        or output_root
        / "scheduled"
        / "ml_direct_chain_maintenance"
        / "latest_status.json"
    ).resolve()
    started_at = datetime.now(timezone.utc).isoformat()
    base_status: dict[str, Any] = {
        "schema_version": "ml-direct-chain-maintenance-status.v1",
        "task": "baldr-ml-direct-chain-maintainer",
        "status_path": str(status_path),
        "started_at": started_at,
        "preflight_only": bool(getattr(args, "preflight_only", False)),
        "execution_started": False,
        "destructive_action_performed": False,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    try:
        command, metadata = _resolve_inputs(args)
        training_output_dir = Path(str(metadata["training_output_dir"]))
        storage_preflight = _storage_preflight(
            training_output_dir,
            minimum_free_space_bytes=args.minimum_free_space_bytes,
        )
        metadata["storage_preflight"] = storage_preflight
        capacity_budget = _capacity_budget_from_args(args)
        metadata["capacity_budget"] = capacity_budget.as_dict()
        persistent_roots = [training_output_dir]
        store_output_value = metadata.get("store_output_dir")
        if isinstance(store_output_value, str) and store_output_value.strip():
            persistent_roots.append(Path(store_output_value))
        capacity_usage = dict(storage_preflight)
        # Keep compatibility with tests/embedding callers that supplied the
        # previous three-field preflight mapping.
        capacity_usage.setdefault("used_bytes", 0)
        capacity_usage.setdefault(
            "total_bytes",
            int(capacity_usage["free_bytes"])
            + int(capacity_usage["used_bytes"]),
        )
        capacity_result = evaluate_capacity(
            budget=capacity_budget,
            usage=capacity_usage,
            stage="scheduled_direct_chain_bootstrap",
            persistent_existing_bytes=sum(
                directory_size_bytes(path) for path in persistent_roots
            ),
            # Before a child is launched the exact output size is unknown;
            # reserve the configured chain budget itself as the worst case.
            persistent_new_bytes_estimate=(
                capacity_budget.persistent_new_bytes_budget or 0
            ),
            temporary_peak_bytes_observed=0,
        )
        metadata["capacity_preflight"] = capacity_result.as_dict()
        if bool(getattr(args, "preflight_only", False)):
            _write_status(
                status_path,
                {
                    **base_status,
                    **metadata,
                    "status": "preflight_only",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "execution_disposition": "not_started",
                },
            )
            return 0
        if (
            not storage_preflight["within_minimum_free_space"]
            or not capacity_result.within_budget
        ):
            _write_status(
                status_path,
                {
                    **base_status,
                    **metadata,
                    "status": "blocked_insufficient_storage",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "error_type": "InsufficientFreeSpace",
                    "error": (
                        "output filesystem free space is below the "
                        "configured Direct/OOC capacity policy"
                    ),
                },
            )
            return 0
        owner_state, owner_pid = _maintenance_lock_state(training_output_dir)
        execution_disposition = (
            "existing_owner_lock"
            if owner_state == "verified"
            else (
                "owner_lock_unverifiable"
                if owner_state == "owner_lock_unverifiable"
                else "new_owner_requested"
            )
        )
        running_status = {
            **base_status,
            **metadata,
            "status": "running",
            "command": command,
            "execution_disposition": execution_disposition,
            "maintenance_lock_state": owner_state,
            "maintenance_owner_process_id": owner_pid,
        }
        _write_status(status_path, running_status)
        return_code = _run_maintainer_with_heartbeat(
            command,
            status_path=status_path,
            running_status=running_status,
            training_output_dir=training_output_dir,
            poll_seconds=args.poll_seconds,
        )
        final_lock_state, final_owner_pid = _maintenance_lock_state(
            training_output_dir
        )
        _write_status(
            status_path,
            {
                **running_status,
                "status": "completed" if return_code == 0 else "failed",
                "returncode": return_code,
                "execution_disposition": running_status[
                    "execution_disposition"
                ],
                "maintenance_lock_state": final_lock_state,
                "maintenance_owner_process_id": final_owner_pid,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return int(return_code)
    except Exception as exc:
        _write_status(
            status_path,
            {
                **base_status,
                "status": "blocked_invalid_bootstrap_input",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
