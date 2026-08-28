"""Execute one explicitly approved technical-indicator production canary.

The default mode is read-only preview.  A production write requires both the
confirmation token and an operator acknowledgement that no other data-update
writer is running.  Before the write the script creates an online SQLite
backup and a copy of the selected technical CSV.  The canary uses the existing
``UpdateService`` path with one bounded process-pool request; workers return
calculation frames and the parent remains the only CSV/SQLite writer.

This script is intentionally narrow: it recalculates one stock in incremental
mode, never runs a market-data download, never enables broker/Selenium work,
and never treats a failed validation as success.  A validation failure restores
the captured SQLite/CSV state when possible.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.update_service import UpdateService  # noqa: E402
from data_module.config import TWStockConfig  # noqa: E402


CANARY_SCHEMA_VERSION = "technical-indicator-production-canary.v1"
OWNER_APPROVAL_TOKEN = "technical-single-writer-canary"
NO_CONCURRENT_WRITER_TOKEN = "no-concurrent-writer"
MAX_WORKERS = 4
MAX_IN_FLIGHT = 16
MAX_RETRIES = 3
DEFAULT_MINIMUM_FREE_SPACE_BYTES = 20 * 1024**3


def inspect_production_state(
    *,
    data_root: Path,
    stock_id: str,
    expected_latest_date: str | None = None,
) -> dict[str, Any]:
    """Read the selected production state without creating files or schemas."""

    resolved_root = Path(data_root).expanduser().resolve()
    db_path = resolved_root / "sqlite" / "twstock.db"
    indicator_path = resolved_root / "technical_analysis" / f"{stock_id}_indicators.csv"
    state: dict[str, Any] = {
        "data_root": str(resolved_root),
        "db_file": str(db_path),
        "indicator_file": str(indicator_path),
        "stock_id": stock_id,
        "expected_latest_date": expected_latest_date,
        "db_exists": db_path.exists(),
        "indicator_file_exists": indicator_path.exists(),
        "indicator_file_sha256": _sha256(indicator_path),
        "indicator_file_row_count": _csv_row_count(indicator_path),
        "db_quick_check": None,
        "daily_stock_row_count": 0,
        "daily_stock_min_date": None,
        "daily_stock_max_date": None,
        "technical_stock_row_count": 0,
        "technical_stock_min_date": None,
        "technical_stock_max_date": None,
        "technical_total_row_count": 0,
    }
    if not db_path.exists():
        state["diagnostic"] = "production SQLite does not exist"
        return state

    with _read_only_connection(db_path) as connection:
        state["db_quick_check"] = str(
            connection.execute("PRAGMA quick_check").fetchone()[0]
        )
        daily_columns = _table_columns(connection, "daily_prices")
        technical_columns = _table_columns(connection, "technical_indicators")
        daily_date = _pick_column(daily_columns, ("日期", "date", "trade_date"))
        daily_stock = _pick_column(
            daily_columns,
            ("證券代號", "股票代號", "stock_code", "stock_id"),
        )
        technical_date = _pick_column(technical_columns, ("日期", "date", "trade_date"))
        technical_stock = _pick_column(
            technical_columns,
            ("證券代號", "股票代號", "stock_code", "stock_id"),
        )
        if daily_date and daily_stock:
            row = connection.execute(
                f"SELECT COUNT(*) AS count, MIN({_quote(daily_date)}) AS min_date, "
                f"MAX({_quote(daily_date)}) AS max_date FROM daily_prices "
                f"WHERE {_quote(daily_stock)} = ?",
                (stock_id,),
            ).fetchone()
            state["daily_stock_row_count"] = int(row[0] or 0)
            state["daily_stock_min_date"] = _date_text(row[1])
            state["daily_stock_max_date"] = _date_text(row[2])
        if technical_date and technical_stock:
            row = connection.execute(
                f"SELECT COUNT(*) AS count, MIN({_quote(technical_date)}) AS min_date, "
                f"MAX({_quote(technical_date)}) AS max_date FROM technical_indicators "
                f"WHERE {_quote(technical_stock)} = ?",
                (stock_id,),
            ).fetchone()
            state["technical_stock_row_count"] = int(row[0] or 0)
            state["technical_stock_min_date"] = _date_text(row[1])
            state["technical_stock_max_date"] = _date_text(row[2])
            state["technical_total_row_count"] = int(
                connection.execute("SELECT COUNT(*) FROM technical_indicators").fetchone()[0]
                or 0
            )
        state["daily_table_columns"] = sorted(daily_columns)
        state["technical_table_columns"] = sorted(technical_columns)
    return state


def execute_production_canary(
    *,
    data_root: Path,
    output_root: Path,
    protected_roots: Sequence[Path],
    stock_id: str,
    expected_latest_date: str,
    backup_root: Path | None = None,
    owner_approval: str | None = None,
    no_concurrent_writer_ack: str | None = None,
    confirm: bool = False,
    workers: int = 2,
    max_in_flight: int = 2,
    max_retries: int = 1,
    minimum_free_space_bytes: int = DEFAULT_MINIMUM_FREE_SPACE_BYTES,
) -> dict[str, Any]:
    """Run the guarded one-stock production canary after explicit approval."""

    resolved_root = Path(data_root).expanduser().resolve()
    resolved_output = Path(output_root).expanduser().resolve()
    resolved_protected = _resolve_roots(protected_roots)
    resolved_db = resolved_root / "sqlite" / "twstock.db"
    indicator_path = resolved_root / "technical_analysis" / f"{stock_id}_indicators.csv"
    base: dict[str, Any] = {
        "schema_version": CANARY_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "mode": "production_canary",
        "data_root": str(resolved_root),
        "output_root": str(resolved_output),
        "protected_roots": [str(path) for path in resolved_protected],
        "db_file": str(resolved_db),
        "indicator_file": str(indicator_path),
        "stock_id": stock_id,
        "expected_latest_date": expected_latest_date,
        "owner_approval": bool(owner_approval),
        "no_concurrent_writer_ack": bool(no_concurrent_writer_ack),
        "confirmation_required": True,
        "confirm_production_technical_canary": bool(confirm),
        "network_enabled": False,
        "broker_enabled": False,
        "selenium_invocations": 0,
        "production_write_attempted": False,
        "production_sqlite_write_attempted": False,
        "production_worker_enabled": False,
        "parent_single_writer": False,
        "worker_writes": False,
        "sqlite_worker_writes": False,
        "workers": workers,
        "max_in_flight": max_in_flight,
        "max_retries": max_retries,
        "minimum_free_space_bytes": minimum_free_space_bytes,
        "storage_preflight": None,
        "backup": None,
        "rollback": {"available": False, "attempted": False, "succeeded": None},
    }

    input_error = _validate_inputs(
        data_root=resolved_root,
        output_root=resolved_output,
        protected_roots=resolved_protected,
        stock_id=stock_id,
        expected_latest_date=expected_latest_date,
        workers=workers,
        max_in_flight=max_in_flight,
        max_retries=max_retries,
        minimum_free_space_bytes=minimum_free_space_bytes,
    )
    if input_error:
        return {**base, "status": "blocked", "blocker": input_error}

    pre_state = inspect_production_state(
        data_root=resolved_root,
        stock_id=stock_id,
        expected_latest_date=expected_latest_date,
    )
    base["pre_state"] = pre_state
    if not pre_state.get("db_exists"):
        return {
            **base,
            "status": "blocked",
            "blocker": "production_sqlite_missing",
            "next_safe_step": "先確認 production DB 路徑與資料更新執行身份。",
        }
    if pre_state.get("db_quick_check") != "ok":
        return {
            **base,
            "status": "blocked",
            "blocker": "production_sqlite_quick_check_failed",
            "next_safe_step": "先停止寫入並修復／回復 DB，再重做 canary。",
        }
    if int(pre_state.get("daily_stock_row_count", 0) or 0) == 0:
        return {
            **base,
            "status": "blocked",
            "blocker": "target_stock_daily_input_missing",
            "next_safe_step": "先取得指定股票的既有日價資料；本 canary 不下載資料。",
        }
    if pre_state.get("daily_stock_max_date") != expected_latest_date:
        return {
            **base,
            "status": "blocked",
            "blocker": "target_stock_latest_date_mismatch",
            "observed_latest_date": pre_state.get("daily_stock_max_date"),
            "next_safe_step": "更新 expected latest date 或先完成上游資料更新；禁止猜測日期。",
        }
    if not confirm:
        return {
            **base,
            "status": "confirmation_required",
            "writes_allowed": False,
            "next_safe_step": (
                "預演已完成；只有 owner_approval=technical-single-writer-canary、"
                "no_concurrent_writer_ack=no-concurrent-writer 與 --confirm-production-technical-canary "
                "同時成立才會建立 backup 並寫入一檔。"
            ),
        }
    if owner_approval != OWNER_APPROVAL_TOKEN:
        return {
            **base,
            "status": "blocked",
            "blocker": "owner_approval_token_required",
            "required_token": OWNER_APPROVAL_TOKEN,
        }
    if no_concurrent_writer_ack != NO_CONCURRENT_WRITER_TOKEN:
        return {
            **base,
            "status": "blocked",
            "blocker": "no_concurrent_writer_ack_required",
            "required_token": NO_CONCURRENT_WRITER_TOKEN,
        }

    backup_dir = (
        Path(backup_root).expanduser().resolve()
        if backup_root is not None
        else resolved_root / "sqlite" / "backups" / "technical_indicator_canary"
    )
    if not _is_within(backup_dir, resolved_root):
        return {
            **base,
            "status": "blocked",
            "blocker": "backup_root_must_be_inside_data_root",
        }

    try:
        storage_preflight = _storage_preflight(
            backup_dir,
            minimum_free_space_bytes=minimum_free_space_bytes,
        )
    except OSError as error:
        return {
            **base,
            "status": "blocked",
            "blocker": "production_canary_storage_preflight_failed",
            "error_type": type(error).__name__,
            "error": str(error),
        }
    base["storage_preflight"] = storage_preflight
    if not storage_preflight["within_minimum_free_space"]:
        return {
            **base,
            "status": "blocked",
            "blocker": "production_canary_storage_preflight_blocked",
            "next_safe_step": (
                "先處理 canary backup 所在檔案系統容量；在最低 headroom 通過前，"
                "不建立 backup、不啟動 technical writer。"
            ),
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup: dict[str, Any] = {
        "status": "blocked",
        "created_at": _utc_now(),
        "directory": str(backup_dir),
        "sqlite_file": None,
        "indicator_file": None,
    }
    backup_db: Path | None = None
    backup_indicator: Path | None = None
    try:
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup_db = backup_dir / f"twstock_before_technical_canary_{stamp}.db"
        _online_backup(resolved_db, backup_db)
        backup["sqlite_file"] = str(backup_db)
        backup["sqlite_sha256"] = _sha256(backup_db)
        if indicator_path.exists():
            backup_indicator = backup_dir / f"{stock_id}_indicators_before_{stamp}.csv"
            shutil.copy2(indicator_path, backup_indicator)
            backup["indicator_file"] = str(backup_indicator)
            backup["indicator_sha256"] = _sha256(backup_indicator)
        backup["status"] = "created"
    except Exception as error:
        return {
            **base,
            "status": "blocked",
            "blocker": "production_canary_backup_failed",
            "error_type": type(error).__name__,
            "error": str(error),
            "backup": backup,
        }

    base["backup"] = backup
    base["rollback"] = {
        "available": backup_db is not None,
        "attempted": False,
        "succeeded": None,
    }
    started = time.perf_counter()
    service_result: dict[str, Any] | None = None
    try:
        config = TWStockConfig(
            data_root=resolved_root,
            output_root=resolved_output,
            profile="prod",
            use_sqlite=True,
            technical_process_pool_enabled=True,
            technical_process_pool_workers=workers,
            technical_process_pool_max_in_flight=max_in_flight,
            technical_process_pool_max_retries=max_retries,
        )
        service_result = UpdateService(config).calculate_technical_indicators(
            target_stock=stock_id,
            force_all=False,
            start_date=None,
            ignore_existing_files=True,
            incremental_lookback_days=120,
            technical_process_pool=True,
            technical_process_pool_workers=workers,
            technical_process_pool_max_in_flight=max_in_flight,
            technical_process_pool_max_retries=max_retries,
        )
        base["production_write_attempted"] = True
        base["production_sqlite_write_attempted"] = True
        post_state = inspect_production_state(
            data_root=resolved_root,
            stock_id=stock_id,
            expected_latest_date=expected_latest_date,
        )
        validation = _validate_post_state(
            service_result=service_result,
            pre_state=pre_state,
            post_state=post_state,
            expected_latest_date=expected_latest_date,
        )
        base["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        base["service_result"] = _bounded_service_result(service_result)
        base["post_state"] = post_state
        base["validation"] = validation
        pool = service_result.get("technical_process_pool")
        if isinstance(pool, Mapping):
            base["production_worker_enabled"] = pool.get("production_worker_enabled") is True
            base["parent_single_writer"] = pool.get("parent_single_writer") is True
            base["worker_writes"] = pool.get("worker_writes") is True
            base["sqlite_worker_writes"] = pool.get("sqlite_worker_writes") is True
        if validation["ok"]:
            base.update(
                {
                    "status": "measured",
                    "blocker": None,
                    "writes_allowed": True,
                    "rollback": {
                        "available": True,
                        "attempted": False,
                        "succeeded": None,
                    },
                    "single_writer_verified": True,
                    "cleanup_succeeded": True,
                    "next_safe_step": (
                        "保留 worker 上限與 parent-only writer；先觀察下一次真實排程，"
                        "再由 owner review canary backup／post-state／rollback artifact。"
                    ),
                }
            )
            return base
        rollback = _rollback(
            db_file=resolved_db,
            indicator_file=indicator_path,
            backup_db=backup_db,
            backup_indicator=backup_indicator,
        )
        base.update(
            {
                "status": "blocked",
                "blocker": "technical_production_canary_validation_failed",
                "writes_allowed": True,
                "rollback": rollback,
                "cleanup_succeeded": rollback.get("succeeded") is True,
            }
        )
        return base
    except Exception as error:
        rollback = _rollback(
            db_file=resolved_db,
            indicator_file=indicator_path,
            backup_db=backup_db,
            backup_indicator=backup_indicator,
        )
        base.update(
            {
                "status": "blocked",
                "blocker": "technical_production_canary_failed",
                "production_write_attempted": True,
                "production_sqlite_write_attempted": True,
                "error_type": type(error).__name__,
                "error": str(error),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "rollback": rollback,
                "cleanup_succeeded": rollback.get("succeeded") is True,
            }
        )
        if service_result is not None:
            base["service_result"] = _bounded_service_result(service_result)
        return base


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, action="append", required=True)
    parser.add_argument("--stock-id", required=True)
    parser.add_argument("--expected-latest-date", required=True)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--owner-approval")
    parser.add_argument("--no-concurrent-writer-ack")
    parser.add_argument("--confirm-production-technical-canary", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-in-flight", type=int, default=2)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument(
        "--minimum-free-space-bytes",
        type=int,
        default=DEFAULT_MINIMUM_FREE_SPACE_BYTES,
        help="fail closed before backup when the canary filesystem has less free space",
    )
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    protected = _resolve_roots(args.protected_root)
    if args.output_json is not None:
        output_target = args.output_json.expanduser().resolve()
        if any(_is_within(output_target, root) for root in protected):
            print(
                json.dumps(
                    {
                        "schema_version": CANARY_SCHEMA_VERSION,
                        "status": "blocked",
                        "blocker": "output_json_inside_protected_root",
                        "production_write_attempted": False,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2
    try:
        report = execute_production_canary(
            data_root=args.data_root,
            output_root=args.output_root,
            protected_roots=args.protected_root,
            stock_id=args.stock_id,
            expected_latest_date=args.expected_latest_date,
            backup_root=args.backup_root,
            owner_approval=args.owner_approval,
            no_concurrent_writer_ack=args.no_concurrent_writer_ack,
            confirm=args.confirm_production_technical_canary,
            workers=args.workers,
            max_in_flight=args.max_in_flight,
            max_retries=args.max_retries,
            minimum_free_space_bytes=args.minimum_free_space_bytes,
        )
    except (OSError, TypeError, ValueError, sqlite3.Error) as error:
        report = {
            "schema_version": CANARY_SCHEMA_VERSION,
            "status": "blocked",
            "blocker": "technical_production_canary_input_or_runtime_error",
            "error_type": type(error).__name__,
            "error": str(error),
            "production_write_attempted": False,
            "production_sqlite_write_attempted": False,
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("status") == "measured" else 2


def _validate_inputs(
    *,
    data_root: Path,
    output_root: Path,
    protected_roots: Sequence[Path],
    stock_id: str,
    expected_latest_date: str,
    workers: int,
    max_in_flight: int,
    max_retries: int,
    minimum_free_space_bytes: int,
) -> str | None:
    if not protected_roots:
        return "protected_root_required"
    if not data_root.is_dir():
        return "data_root_must_preexist"
    if not output_root.is_dir():
        return "output_root_must_preexist_as_directory"
    if not any(_is_within(data_root, root) for root in protected_roots):
        return "data_root_not_covered_by_protected_root"
    if not any(_is_within(output_root, root) for root in protected_roots):
        return "output_root_not_covered_by_protected_root"
    if len(stock_id) != 4 or not stock_id.isdigit():
        return "stock_id_must_be_four_digits"
    try:
        datetime.strptime(expected_latest_date, "%Y-%m-%d")
    except ValueError:
        return "expected_latest_date_invalid"
    if workers < 1 or workers > MAX_WORKERS:
        return "workers_out_of_range"
    if max_in_flight < 1 or max_in_flight > MAX_IN_FLIGHT:
        return "max_in_flight_out_of_range"
    if max_retries < 0 or max_retries > MAX_RETRIES:
        return "max_retries_out_of_range"
    if minimum_free_space_bytes <= 0:
        return "minimum_free_space_bytes_must_be_positive"
    return None


def _storage_preflight(
    path: Path,
    *,
    minimum_free_space_bytes: int,
) -> dict[str, Any]:
    """Read backup filesystem headroom without creating or mutating anything."""

    if minimum_free_space_bytes <= 0:
        raise ValueError("minimum_free_space_bytes must be positive")
    probe_path = path
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent
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


def _validate_post_state(
    *,
    service_result: Mapping[str, Any],
    pre_state: Mapping[str, Any],
    post_state: Mapping[str, Any],
    expected_latest_date: str,
) -> dict[str, Any]:
    pool = service_result.get("technical_process_pool")
    pool_mapping = pool if isinstance(pool, Mapping) else {}
    checks = {
        "service_success": service_result.get("success") is True,
        "pool_completed": pool_mapping.get("status") == "completed",
        "pool_parent_single_writer": pool_mapping.get("parent_single_writer") is True,
        "pool_worker_writes_false": pool_mapping.get("worker_writes") is False,
        "pool_sqlite_worker_writes_false": pool_mapping.get("sqlite_worker_writes") is False,
        "pool_written_one_stock": int(pool_mapping.get("parent_written_stock_count", 0) or 0) == 1,
        "pool_write_failures_zero": int(pool_mapping.get("parent_write_failed_count", 1)) == 0,
        "post_db_quick_check": post_state.get("db_quick_check") == "ok",
        "post_daily_latest_matches": post_state.get("daily_stock_max_date") == expected_latest_date,
        "post_technical_rows_present": int(post_state.get("technical_stock_row_count", 0) or 0) > 0,
        "post_indicator_file_present": post_state.get("indicator_file_exists") is True,
    }
    return {"ok": all(checks.values()), "checks": checks}


def _bounded_service_result(result: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "success",
        "message",
        "total_stocks",
        "success_count",
        "fail_count",
        "insufficient_data_count",
        "updated_stocks",
        "failed_stocks",
        "start_date",
        "end_date",
        "technical_process_pool",
    )
    output: dict[str, Any] = {}
    for key in allowed:
        value = result.get(key)
        if isinstance(value, (str, int, bool, float)) or value is None:
            output[key] = value
        elif isinstance(value, (list, tuple)):
            output[key] = [str(item) for item in value[:32]]
        elif isinstance(value, Mapping):
            output[key] = dict(value)
    return output


def _rollback(
    *,
    db_file: Path,
    indicator_file: Path,
    backup_db: Path | None,
    backup_indicator: Path | None,
) -> dict[str, Any]:
    rollback: dict[str, Any] = {
        "available": backup_db is not None,
        "attempted": True,
        "succeeded": False,
        "sqlite_restored": False,
        "indicator_restored": False,
    }
    try:
        if backup_db is None or not backup_db.exists():
            raise FileNotFoundError("SQLite backup is missing")
        _online_backup(backup_db, db_file)
        rollback["sqlite_restored"] = True
        if backup_indicator is not None:
            shutil.copy2(backup_indicator, indicator_file)
            rollback["indicator_restored"] = True
        elif indicator_file.exists():
            indicator_file.unlink()
            rollback["indicator_restored"] = True
        else:
            # The pre-canary state legitimately had no per-stock CSV.
            rollback["indicator_restored"] = True
        rollback["succeeded"] = bool(rollback["sqlite_restored"] and rollback["indicator_restored"])
    except Exception as error:
        rollback["error_type"] = type(error).__name__
        rollback["error"] = str(error)
    return rollback


def _online_backup(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source, sqlite3.connect(target_path) as target:
        source.execute("PRAGMA busy_timeout=5000")
        source.backup(target)
    with _read_only_connection(target_path) as verification:
        if verification.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"SQLite backup quick_check failed: {target_path}")


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({_quote(table_name)})"
        ).fetchall()
    }


def _pick_column(columns: set[str], candidates: Sequence[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10] if len(text) >= 10 else text


def _csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_roots(roots: Sequence[Path]) -> list[Path]:
    return [Path(root).expanduser().resolve() for root in roots if str(root).strip()]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
