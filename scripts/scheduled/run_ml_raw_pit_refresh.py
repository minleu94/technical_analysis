"""資料更新後自動發布全市場 immutable raw PIT publication。

這個 runner 只在 data-update quick 已經證明 daily／technical core date 就緒時，
以 SQLite ``mode=ro/query_only`` 呼叫既有 PIT shard exporter。它不寫正式 SQLite、
不建立 promotion evidence，也不放寬任何 ML formal gate；publication 完成後由
Direct/OOC maintenance watcher 依 hash-bound pointer 自動接續。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from scripts.scheduled.scheduled_clock import scheduled_now


_TAIPEI = ZoneInfo("Asia/Taipei")
_DECISION_TIME = time(8, 30)
_SCHEMA_VERSION = "ml-raw-pit-refresh-status.v1"
_POINTER_SCHEMA_VERSION = "ml-pit-year-shards-pointer.v1"
_DATASET_SCHEMA_VERSION = "ml-pit-year-shard-dataset.v1"
_RAW_ROOT_NAME = "ml_pit_year_shards"
_DEFAULT_MINIMUM_FREE_SPACE_BYTES = 20 * 1024**3
_ALLOWED_DATA_UPDATE_STATUSES = frozenset(
    {"passed", "passed_with_warnings"}
)


class _UpstreamNotReady(RuntimeError):
    """The runner must wait for a later scheduled data-update proof."""


@dataclass(frozen=True)
class _CoreFreshnessProof:
    latest_core_date: date
    decision_at: str
    completed_at: datetime
    data_update_status: str


@dataclass(frozen=True)
class _RawPublication:
    publication_id: str
    publication_manifest_path: Path
    publication_manifest_hash: str
    dataset_manifest_path: Path
    dataset_manifest_hash: str
    decision_at: datetime
    manifest_mtime: datetime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--history-start-date", default="2014-01-01")
    parser.add_argument("--batch-size", type=int, default=2_048)
    parser.add_argument("--compression-level", type=int, default=6, choices=range(10))
    parser.add_argument(
        "--minimum-free-space-bytes",
        type=int,
        default=_DEFAULT_MINIMUM_FREE_SPACE_BYTES,
        help=(
            "fail closed before launching the raw PIT builder when the "
            "output filesystem has less free space than this threshold"
        ),
    )
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--log-path", type=Path)
    return parser


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON root must be object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_date(value: object, *, field_name: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO date")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _parse_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone offset")
    return parsed


def _taipei_now() -> datetime:
    return datetime.now(_TAIPEI)


def _core_freshness_proof(status_path: Path) -> _CoreFreshnessProof:
    if not status_path.is_file():
        raise _UpstreamNotReady("data_update_status_missing")
    try:
        payload = _read_object(status_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _UpstreamNotReady("data_update_status_invalid") from exc
    update_status = payload.get("status")
    if update_status not in _ALLOWED_DATA_UPDATE_STATUSES:
        raise _UpstreamNotReady(
            f"data_update_status_not_ready:{update_status or 'missing'}"
        )
    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise _UpstreamNotReady("data_update_check_overview_after_missing")
    after_step = next(
        (
            item
            for item in steps
            if isinstance(item, dict) and item.get("name") == "check_overview_after"
        ),
        None,
    )
    if not isinstance(after_step, dict):
        raise _UpstreamNotReady("data_update_check_overview_after_missing")
    result = after_step.get("result")
    if not isinstance(result, dict):
        raise _UpstreamNotReady("data_update_check_overview_after_invalid")
    daily = result.get("daily_data")
    technical = result.get("technical_indicators")
    if not isinstance(daily, dict) or not isinstance(technical, dict):
        raise _UpstreamNotReady("data_update_core_date_missing")
    daily_date = _parse_date(daily.get("latest_date"), field_name="daily.latest_date")
    technical_date = _parse_date(
        technical.get("latest_date"),
        field_name="technical_indicators.latest_date",
    )
    if technical_date < daily_date:
        raise _UpstreamNotReady(
            "data_update_technical_indicators_lagging:" + technical_date.isoformat()
        )
    completed_at = _parse_datetime(
        payload.get("completed_at") or payload.get("checked_at"),
        field_name="data_update.completed_at",
    )
    decision = datetime.combine(daily_date, _DECISION_TIME, tzinfo=_TAIPEI)
    if decision > _taipei_now():
        raise _UpstreamNotReady(
            "data_update_core_date_is_future:" + daily_date.isoformat()
        )
    return _CoreFreshnessProof(
        latest_core_date=daily_date,
        decision_at=decision.isoformat(),
        completed_at=completed_at,
        data_update_status=str(update_status),
    )


def _resolve_child(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("manifest relative path missing")
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(value)).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("manifest relative path escapes publication root")
    return resolved


def _required_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(f"{field_name} must be sha256")
    digest = value[7:]
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} must be sha256")
    return value


def _latest_raw_publication(raw_root: Path) -> _RawPublication | None:
    pointer_path = raw_root / "latest_manifest.json"
    if not pointer_path.is_file():
        return None
    try:
        pointer = _read_object(pointer_path)
        if pointer.get("schema_version") != _POINTER_SCHEMA_VERSION:
            return None
        pointer_hash = _required_sha256(
            pointer.get("manifest_hash"),
            field_name="raw pointer.manifest_hash",
        )
        manifest_path = _resolve_child(raw_root, pointer.get("manifest_path"))
        manifest = _read_object(manifest_path)
        if (
            manifest.get("schema_version") != "ml-pit-year-shards.v1"
            or manifest.get("publication_id") != pointer.get("publication_id")
            or manifest.get("manifest_hash") != pointer_hash
        ):
            return None
        logical_manifest = dict(manifest)
        logical_manifest.pop("manifest_hash", None)
        if _canonical_sha256(logical_manifest) != pointer_hash:
            return None
        scope = manifest.get("scope")
        if not isinstance(scope, dict) or scope.get("all_universe") is not True:
            return None
        datasets = manifest.get("datasets")
        if not isinstance(datasets, dict):
            return None
        dataset_meta = datasets.get("all_field_enriched")
        if not isinstance(dataset_meta, dict):
            return None
        dataset_path = _resolve_child(manifest_path.parent, dataset_meta.get("manifest_path"))
        dataset_manifest = _read_object(dataset_path)
        dataset_hash = _required_sha256(
            dataset_manifest.get("manifest_hash"),
            field_name="raw dataset.manifest_hash",
        )
        dataset_assembler._validate_raw_dataset_manifest(dataset_manifest)
        if (
            dataset_manifest.get("schema_version") != _DATASET_SCHEMA_VERSION
            or dataset_manifest.get("dataset_id") != "all_field_enriched"
            or dataset_meta.get("manifest_hash") != dataset_hash
            or dataset_manifest.get("decision_at") != manifest.get("decision_at")
            or dataset_manifest.get("history_start_date")
            != manifest.get("history_start_date")
        ):
            return None
        decision_at = dataset_assembler._decision_datetime(
            str(dataset_manifest["decision_at"])
        )
        manifest_mtime = datetime.fromtimestamp(
            manifest_path.stat().st_mtime,
            tz=timezone.utc,
        )
        return _RawPublication(
            publication_id=str(manifest["publication_id"]),
            publication_manifest_path=manifest_path,
            publication_manifest_hash=pointer_hash,
            dataset_manifest_path=dataset_path,
            dataset_manifest_hash=dataset_hash,
            decision_at=decision_at,
            manifest_mtime=manifest_mtime,
        )
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        KeyError,
        json.JSONDecodeError,
    ):
        return None


def _refresh_needed(
    current: _RawPublication | None,
    proof: _CoreFreshnessProof,
) -> bool:
    if current is None:
        return True
    target = _parse_datetime(proof.decision_at, field_name="target decision_at")
    if current.decision_at > target:
        return False
    if current.decision_at < target:
        return True
    return current.manifest_mtime < proof.completed_at.astimezone(timezone.utc)


def _acquire_lock(lock_path: Path) -> tuple[Path, Any] | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            handle = lock_path.open("x", encoding="utf-8", newline="\n")
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            return lock_path, handle
        except FileExistsError:
            try:
                owner_pid = int(lock_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                owner_pid = 0
            if owner_pid and _pid_is_live(owner_pid):
                return None
            try:
                lock_path.unlink()
            except FileNotFoundError:
                continue
    return None


def _pid_is_live(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _release_lock(lock: tuple[Path, Any] | None) -> None:
    if lock is None:
        return
    path, handle = lock
    try:
        handle.close()
    finally:
        path.unlink(missing_ok=True)


def _append_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(message.rstrip() + "\n")


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


def _builder_command(
    *,
    database: Path,
    raw_root: Path,
    proof: _CoreFreshnessProof,
    history_start_date: str,
    batch_size: int,
    compression_level: int,
) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "build_ml_pit_year_shards.py"),
        "--database",
        str(database.resolve()),
        "--output-dir",
        str(raw_root.resolve()),
        "--decision-at",
        proof.decision_at,
        "--history-start-date",
        history_start_date,
        "--all-universe",
        "--batch-size",
        str(batch_size),
        "--compression-level",
        str(compression_level),
    ]


def _base_status(
    *,
    status: str,
    output_root: Path,
    raw_root: Path,
    database: Path,
    status_path: Path,
    log_path: Path,
    **fields: object,
) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "task": "baldr-ml-raw-pit-refresh-daily",
        "status": status,
        "process_id": os.getpid(),
        "output_root": str(output_root),
        "raw_output_root": str(raw_root),
        "database": str(database),
        "database_mode": "ro",
        "query_only": True,
        "writes_source_database": False,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "status_path": str(status_path),
        "log_path": str(log_path),
        **fields,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.batch_size <= 0 or args.batch_size > 100_000:
        raise ValueError("batch-size must be within 1..100000")
    if args.minimum_free_space_bytes <= 0:
        raise ValueError("minimum-free-space-bytes must be positive")
    output_root = args.output_root.resolve()
    release_root = (
        args.release_root.resolve()
        if args.release_root is not None
        else output_root / "release_v4"
    )
    raw_root = release_root / _RAW_ROOT_NAME
    database = (
        args.database.resolve()
        if args.database is not None
        else args.data_root.resolve() / "sqlite" / "twstock.db"
    )
    run_root = output_root / "scheduled" / "ml_raw_pit_refresh"
    status_path = args.status_path.resolve() if args.status_path else run_root / "latest_status.json"
    log_path = args.log_path.resolve() if args.log_path else run_root / "refresh.log"
    data_update_status_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    lock_path = raw_root / ".ml_raw_pit_refresh.lock"
    started_at = scheduled_now()
    lock = _acquire_lock(lock_path)
    if lock is None:
        _write_json(
            status_path,
            _base_status(
                status="skipped_locked",
                output_root=output_root,
                raw_root=raw_root,
                database=database,
                status_path=status_path,
                log_path=log_path,
                started_at=started_at.isoformat(timespec="seconds"),
                completed_at=scheduled_now().isoformat(timespec="seconds"),
                reason="another_raw_pit_refresh_is_running",
            ),
        )
        return 0
    _write_json(
        status_path,
        _base_status(
            status="running",
            output_root=output_root,
            raw_root=raw_root,
            database=database,
            status_path=status_path,
            log_path=log_path,
            started_at=started_at.isoformat(timespec="seconds"),
            data_update_status_path=str(data_update_status_path),
        ),
    )
    try:
        try:
            proof = _core_freshness_proof(data_update_status_path)
            current = _latest_raw_publication(raw_root)
            if not _refresh_needed(current, proof):
                payload = _base_status(
                    status="skipped_current",
                    output_root=output_root,
                    raw_root=raw_root,
                    database=database,
                    status_path=status_path,
                    log_path=log_path,
                    started_at=started_at.isoformat(timespec="seconds"),
                    completed_at=scheduled_now().isoformat(timespec="seconds"),
                    latest_core_date=proof.latest_core_date.isoformat(),
                    decision_at=proof.decision_at,
                    data_update_status=proof.data_update_status,
                    current_publication_id=(
                        None if current is None else current.publication_id
                    ),
                    current_dataset_manifest_hash=(
                        None if current is None else current.dataset_manifest_hash
                    ),
                    reason="raw_pit_publication_current",
                )
                _write_json(status_path, payload)
                return 0
            storage_preflight = _storage_preflight(
                raw_root,
                minimum_free_space_bytes=args.minimum_free_space_bytes,
            )
            if not storage_preflight["within_minimum_free_space"]:
                payload = _base_status(
                    status="blocked_insufficient_storage",
                    output_root=output_root,
                    raw_root=raw_root,
                    database=database,
                    status_path=status_path,
                    log_path=log_path,
                    started_at=started_at.isoformat(timespec="seconds"),
                    completed_at=scheduled_now().isoformat(timespec="seconds"),
                    latest_core_date=proof.latest_core_date.isoformat(),
                    decision_at=proof.decision_at,
                    data_update_status=proof.data_update_status,
                    current_publication_id=(
                        None if current is None else current.publication_id
                    ),
                    storage_preflight=storage_preflight,
                    error_type="InsufficientFreeSpace",
                    error=(
                        "raw PIT output filesystem free space is below the "
                        "configured preflight threshold"
                    ),
                )
                _write_json(status_path, payload)
                return 0
            if not database.is_file():
                raise RuntimeError(f"database_missing:{database}")
            command = _builder_command(
                database=database,
                raw_root=raw_root,
                proof=proof,
                history_start_date=args.history_start_date,
                batch_size=args.batch_size,
                compression_level=args.compression_level,
            )
            _append_log(log_path, json.dumps({"event": "builder_start", "command": command}, ensure_ascii=False))
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if completed.stdout:
                _append_log(log_path, completed.stdout)
            if completed.stderr:
                _append_log(log_path, completed.stderr)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"raw_pit_builder_failed:{completed.returncode}"
                )
            published = _latest_raw_publication(raw_root)
            if published is None:
                raise RuntimeError("raw_pit_pointer_validation_failed")
            target = _parse_datetime(proof.decision_at, field_name="target decision_at")
            if published.decision_at < target:
                raise RuntimeError("raw_pit_publication_decision_at_not_advanced")
            payload = _base_status(
                status="completed",
                output_root=output_root,
                raw_root=raw_root,
                database=database,
                status_path=status_path,
                log_path=log_path,
                started_at=started_at.isoformat(timespec="seconds"),
                completed_at=scheduled_now().isoformat(timespec="seconds"),
                latest_core_date=proof.latest_core_date.isoformat(),
                decision_at=proof.decision_at,
                data_update_status=proof.data_update_status,
                publication_id=published.publication_id,
                publication_manifest_hash=published.publication_manifest_hash,
                dataset_manifest_hash=published.dataset_manifest_hash,
                publication_manifest_path=str(published.publication_manifest_path),
                dataset_manifest_path=str(published.dataset_manifest_path),
                builder_returncode=completed.returncode,
            )
            _write_json(status_path, payload)
            return 0
        except _UpstreamNotReady as exc:
            payload = _base_status(
                status="blocked_upstream_not_ready",
                output_root=output_root,
                raw_root=raw_root,
                database=database,
                status_path=status_path,
                log_path=log_path,
                started_at=started_at.isoformat(timespec="seconds"),
                completed_at=scheduled_now().isoformat(timespec="seconds"),
                reason=str(exc),
            )
            _write_json(status_path, payload)
            return 0
        except Exception as exc:  # noqa: BLE001 - preserve machine-readable failure
            payload = _base_status(
                status="failed",
                output_root=output_root,
                raw_root=raw_root,
                database=database,
                status_path=status_path,
                log_path=log_path,
                started_at=started_at.isoformat(timespec="seconds"),
                completed_at=scheduled_now().isoformat(timespec="seconds"),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            _write_json(status_path, payload)
            _append_log(log_path, f"failure: {type(exc).__name__}: {exc}")
            return 1
    finally:
        _release_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
