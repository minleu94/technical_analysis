"""在隔離 staging 量測技術指標 CSV serialization 與 SQLite single-writer。

這個 probe 只接受呼叫端明確指定的 raw CSV、既有 staging root、protected
roots 與 --confirm-write-probe。所有 CSV／SQLite 寫入都發生在 staging
root 下的 ephemeral 子目錄，probe 結束後清除；正式 DATA_ROOT、正式輸出與
正式 SQLite 絕不會被當成 writer 目標。SQLite contention 以兩個 staging
connection 實測 BEGIN IMMEDIATE 的 single-writer 邊界，並在 holder
釋放後驗證 serialized retry。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
from typing import Any, Sequence, cast

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis_module.technical_analysis.technical_indicators import (  # noqa: E402
    TechnicalIndicatorCalculator,
)
from data_module.db_manager import DBManager  # noqa: E402
from scripts.qa_technical_indicator_full_batch import (  # noqa: E402
    _find_stock_column,
    _normalize_requested_stock_ids,
)


WRITE_PROBE_SCHEMA_VERSION = "technical-indicator-write-probe.v1"
_SAFE_MAX_IDS = 100
_STOCK_FILE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")


def measure_write_probe(
    *,
    stock_data_file: Path,
    staging_root: Path,
    protected_roots: Sequence[Path],
    confirm_write_probe: bool = False,
    stock_ids: Sequence[str] | None = None,
    min_rows: int = 30,
    max_stocks: int | None = None,
    max_rows_per_stock: int | None = 120,
) -> dict[str, Any]:
    """量測 staging writer 與 SQLite contention；不允許未確認的寫入。"""

    _validate_options(
        min_rows=min_rows,
        max_stocks=max_stocks,
        max_rows_per_stock=max_rows_per_stock,
    )
    resolved_input = stock_data_file.expanduser().resolve()
    resolved_staging = staging_root.expanduser().resolve()
    resolved_protected = _resolve_roots(protected_roots)
    base: dict[str, Any] = {
        "schema_version": WRITE_PROBE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stock_data_file": str(resolved_input),
        "staging_root": str(resolved_staging),
        "protected_roots": [str(path) for path in resolved_protected],
        "confirmation_required": True,
        "confirm_write_probe": bool(confirm_write_probe),
        "read_only": False,
        "write_attempted": False,
        "staging_write_attempted": False,
        "production_write_attempted": False,
        "sqlite_write_attempted": False,
        "production_sqlite_write_attempted": False,
        "parallelism_enabled": False,
        "observed_worker_count": 1,
        "single_writer_required": True,
        "cleanup_succeeded": None,
        "options": {
            "requested_stock_ids": list(stock_ids) if stock_ids is not None else None,
            "min_rows": min_rows,
            "max_stocks": max_stocks,
            "max_rows_per_stock": max_rows_per_stock,
        },
    }
    if not confirm_write_probe:
        return {
            **base,
            "status": "confirmation_required",
            "blocker": "explicit_confirm_write_probe_required",
            "next_safe_step": (
                "先指定既有 staging root、protected root，並明確傳入 "
                "--confirm-write-probe；未確認時不建立任何檔案。"
            ),
        }
    if not resolved_protected:
        return {
            **base,
            "status": "blocked",
            "blocker": "protected_root_required",
            "next_safe_step": "至少指定一個 protected root，讓 probe 能拒絕正式路徑。",
        }
    if not resolved_staging.is_dir():
        return {
            **base,
            "status": "blocked",
            "blocker": "staging_root_must_preexist",
            "next_safe_step": "建立專用、非正式資料根目錄的 staging root 後再重跑。",
        }
    if any(_is_within(resolved_staging, root) for root in resolved_protected):
        return {
            **base,
            "status": "blocked",
            "blocker": "staging_root_inside_protected_root",
            "next_safe_step": "改用正式資料根目錄之外的 staging root；禁止在 protected root 寫入。",
        }
    if not resolved_input.is_file():
        return {
            **base,
            "status": "blocked",
            "blocker": "stock_data_file_missing",
            "next_safe_step": "提供存在且可讀取的 raw stock CSV；probe 不會自動建立來源。",
        }

    input_hash_before = _sha256(resolved_input)
    total_started = time.perf_counter()
    report: dict[str, Any]
    try:
        with tempfile.TemporaryDirectory(
            dir=str(resolved_staging),
            prefix="technical_indicator_write_probe_",
        ) as temp_name:
            temp_root = Path(temp_name)
            report = _run_staged_probe(
                stock_data_file=resolved_input,
                temp_root=temp_root,
                stock_ids=stock_ids,
                min_rows=min_rows,
                max_stocks=max_stocks,
                max_rows_per_stock=max_rows_per_stock,
            )
            report = {**base, **report}
            staged_write = "csv" in report
            report["staging_write_attempted"] = staged_write
            report["write_attempted"] = staged_write
            report["production_write_attempted"] = False
            report["production_sqlite_write_attempted"] = False
            report["sqlite_write_attempted"] = staged_write
    except (OSError, TypeError, ValueError, sqlite3.Error) as error:
        report = {
            **base,
            "status": "blocked",
            "blocker": "isolated_write_probe_failed",
            "error_type": type(error).__name__,
            "error": str(error),
            "stages": {"total_ms": _elapsed_ms(total_started)},
            "stocks": {},
            "rows": {},
            "next_safe_step": "檢查 staging 權限、CSV schema 與 SQLite 錯誤後再重跑；不要改正式 writer。",
        }
    else:
        report["stages"]["total_ms"] = _elapsed_ms(total_started)
        report["input_sha256_before"] = input_hash_before
        report["input_sha256_after"] = _sha256(resolved_input)
        report["input_unchanged"] = (
            report["input_sha256_before"] == report["input_sha256_after"]
        )
        report["production_write_attempted"] = False
        report["production_sqlite_write_attempted"] = False
    finally:
        # TemporaryDirectory 已在離開 with 後清理；以 glob 驗證 staging root
        # 沒有遺留本 probe 的 ephemeral 目錄。
        report["cleanup_succeeded"] = resolved_staging.is_dir() and not any(
            path.is_dir() and path.name.startswith("technical_indicator_write_probe_")
            for path in resolved_staging.iterdir()
        )

    return report


def _run_staged_probe(
    *,
    stock_data_file: Path,
    temp_root: Path,
    stock_ids: Sequence[str] | None,
    min_rows: int,
    max_stocks: int | None,
    max_rows_per_stock: int | None,
) -> dict[str, Any]:
    logger = logging.getLogger("qa_technical_indicator_write_probe")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    stages: dict[str, Any] = {}
    read_started = time.perf_counter()
    frame = pd.read_csv(
        stock_data_file,
        encoding="utf-8-sig",
        dtype=str,
        low_memory=False,
    )
    stages["read_ms"] = _elapsed_ms(read_started)
    stages["input_file_size_bytes"] = stock_data_file.stat().st_size
    stock_column = _find_stock_column(frame.columns)
    if stock_column is None:
        return {
            "schema_version": WRITE_PROBE_SCHEMA_VERSION,
            "status": "blocked",
            "blocker": "stock_code_column_missing",
            "stages": stages,
            "stocks": {},
            "rows": {"raw_input_rows": len(frame)},
            "next_safe_step": "提供含證券代號／股票代號或 stock_id 欄位的 CSV；不猜欄位。",
        }

    normalized = frame.copy()
    normalized[stock_column] = normalized[stock_column].astype(str).str.strip()
    normalized = normalized[normalized[stock_column].ne("")].copy()
    groups = {
        str(stock_id): group.copy()
        for stock_id, group in normalized.groupby(stock_column, sort=True)
    }
    requested = _normalize_requested_stock_ids(stock_ids)
    selected_ids = (
        [stock_id for stock_id in requested if stock_id in groups]
        if requested
        else sorted(groups)
    )
    missing_requested = [stock_id for stock_id in requested if stock_id not in groups]
    if max_stocks is not None:
        selected_ids = selected_ids[:max_stocks]

    calculator = TechnicalIndicatorCalculator(logger=logger)
    calculated: dict[str, pd.DataFrame] = {}
    insufficient_ids: list[str] = []
    failed_ids: list[str] = []
    input_rows = 0
    calculation_started = time.perf_counter()
    for stock_id in selected_ids:
        group = groups[stock_id]
        input_rows += len(group)
        if len(group) < min_rows:
            insufficient_ids.append(stock_id)
            continue
        if max_rows_per_stock is not None:
            group = group.tail(max_rows_per_stock).copy()
        try:
            result = calculator.calculate_all_indicators(group, stock_id)
        except Exception:
            failed_ids.append(stock_id)
            continue
        if not isinstance(result, pd.DataFrame) or result.empty:
            failed_ids.append(stock_id)
            continue
        result = result.copy()
        if "證券代號" not in result.columns:
            result["證券代號"] = str(stock_id)
        if "日期" not in result.columns:
            failed_ids.append(stock_id)
            continue
        calculated[stock_id] = result
    stages["calculate_ms"] = _elapsed_ms(calculation_started)

    if not calculated:
        status = "blocked"
        blocker = "no_stock_completed_calculation" if selected_ids else "no_matching_stock_groups"
        return {
            "schema_version": WRITE_PROBE_SCHEMA_VERSION,
            "status": status,
            "blocker": blocker,
            "stock_code_column": stock_column,
            "stages": stages,
            "stocks": {
                "available_group_count": len(groups),
                "selected_group_count": len(selected_ids),
                "measured_count": 0,
                "insufficient_count": len(insufficient_ids),
                "failed_count": len(failed_ids),
                "insufficient_ids": insufficient_ids[:_SAFE_MAX_IDS],
                "failed_ids": failed_ids[:_SAFE_MAX_IDS],
                "missing_requested_ids": missing_requested[:_SAFE_MAX_IDS],
            },
            "rows": {
                "raw_input_rows": len(frame),
                "normalized_input_rows": len(normalized),
                "selected_input_rows": input_rows,
            },
            "next_safe_step": "先修正可計算的 stock group 或 raw schema，再做 staging writer probe。",
        }

    technical_dir = temp_root / "technical"
    technical_dir.mkdir(parents=True, exist_ok=False)
    csv_started = time.perf_counter()
    csv_files: list[dict[str, Any]] = []
    for stock_id, result in calculated.items():
        target = technical_dir / f"{_stock_file_token(stock_id)}_indicators.csv"
        result.to_csv(target, index=False, encoding="utf-8-sig")
        csv_files.append(
            {
                "stock_id": stock_id,
                "path": str(target),
                "rows": len(result),
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )
    stages["csv_serialization_ms"] = _elapsed_ms(csv_started)

    aggregate_started = time.perf_counter()
    aggregate = pd.concat(list(calculated.values()), ignore_index=True)
    aggregate_target = temp_root / "technical_indicators_all.csv"
    aggregate.to_csv(aggregate_target, index=False, encoding="utf-8-sig")
    stages["aggregate_csv_write_ms"] = _elapsed_ms(aggregate_started)
    aggregate_before_dedup = len(aggregate)
    if {"證券代號", "日期"}.issubset(aggregate.columns):
        aggregate_for_db = aggregate.drop_duplicates(
            subset=["證券代號", "日期"], keep="last"
        ).copy()
    else:
        aggregate_for_db = aggregate.copy()
    duplicate_rows_dropped = aggregate_before_dedup - len(aggregate_for_db)

    sqlite_result = _write_staging_sqlite(
        temp_root / "technical_indicators.sqlite",
        aggregate_for_db,
    )
    stages.update(sqlite_result.pop("stages"))
    measured_ids = list(calculated)
    complete = not insufficient_ids and not failed_ids and not missing_requested
    status = "measured" if complete and sqlite_result["status"] == "measured" else "partial"
    if sqlite_result["status"] == "blocked":
        status = "blocked"
    return {
        "schema_version": WRITE_PROBE_SCHEMA_VERSION,
        "status": status,
        "blocker": (
            None
            if status == "measured"
            else sqlite_result.get("blocker", "some_stock_groups_not_measured")
        ),
        "stock_code_column": stock_column,
        "stages": stages,
        "stocks": {
            "available_group_count": len(groups),
            "selected_group_count": len(selected_ids),
            "measured_count": len(measured_ids),
            "insufficient_count": len(insufficient_ids),
            "failed_count": len(failed_ids),
            "measured_ids": measured_ids[:_SAFE_MAX_IDS],
            "insufficient_ids": insufficient_ids[:_SAFE_MAX_IDS],
            "failed_ids": failed_ids[:_SAFE_MAX_IDS],
            "missing_requested_ids": missing_requested[:_SAFE_MAX_IDS],
        },
        "rows": {
            "raw_input_rows": len(frame),
            "normalized_input_rows": len(normalized),
            "selected_input_rows": input_rows,
            "calculated_rows": aggregate_before_dedup,
            "sqlite_rows": len(aggregate_for_db),
            "duplicate_rows_dropped_for_sqlite": duplicate_rows_dropped,
            "aggregate_column_count": len(aggregate.columns),
        },
        "csv": {
            "files": csv_files,
            "aggregate": {
                "path": str(aggregate_target),
                "rows": len(aggregate),
                "bytes": aggregate_target.stat().st_size,
                "sha256": _sha256(aggregate_target),
            },
        },
        "sqlite": sqlite_result,
        "next_safe_step": (
            "以本次 CSV／SQLite stage timing 定義 bounded worker 的輸出佇列與 "
            "single writer；在 broker fetch concurrency 與 cancel/retry acceptance "
            "完成前維持 worker 關閉。"
        ),
    }


def _write_staging_sqlite(db_path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    log_dir = db_path.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    manager_logger = logging.getLogger("data_module.db_manager")
    existing_handlers = list(manager_logger.handlers)
    schema_started = time.perf_counter()
    try:
        manager = DBManager(cast(Any, SimpleNamespace(db_file=db_path, log_dir=log_dir)))
        schema_ms = _elapsed_ms(schema_started)
        write_started = time.perf_counter()
        write_ok = manager.write_dataframe("technical_indicators", frame, if_exists="append")
        write_ms = _elapsed_ms(write_started)
    finally:
        _close_new_file_handlers(manager_logger, existing_handlers)
    if not write_ok:
        return {
            "status": "blocked",
            "blocker": "staging_sqlite_write_failed",
            "stages": {
                "sqlite_schema_ms": schema_ms,
                "sqlite_write_ms": write_ms,
            },
            "write_ok": False,
            "contention": {},
        }

    count_started = time.perf_counter()
    count_conn = sqlite3.connect(db_path)
    try:
        row = count_conn.execute("SELECT COUNT(*) FROM technical_indicators").fetchone()
        sqlite_rows = int(row[0]) if row else 0
    finally:
        count_conn.close()
    count_ms = _elapsed_ms(count_started)
    contention = _measure_single_writer_contention(db_path)
    return {
        "status": (
            "measured"
            if contention["contention_observed"] and contention["retry_succeeded"]
            else "partial"
        ),
        "blocker": (
            None
            if contention["contention_observed"] and contention["retry_succeeded"]
            else "sqlite_single_writer_contention_not_proven"
        ),
        "stages": {
            "sqlite_schema_ms": schema_ms,
            "sqlite_write_ms": write_ms,
            "sqlite_count_ms": count_ms,
            "sqlite_contention_ms": contention["contention_ms"],
            "sqlite_retry_ms": contention["retry_ms"],
        },
        "write_ok": True,
        "sqlite_rows": sqlite_rows,
        "contention": contention,
    }


def _measure_single_writer_contention(db_path: Path) -> dict[str, Any]:
    holder = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
    contender = sqlite3.connect(db_path, timeout=0.0, isolation_level=None)
    contention_ms = 0.0
    retry_ms = 0.0
    error_type: str | None = None
    error_message: str | None = None
    try:
        holder.execute("PRAGMA journal_mode=WAL")
        contender.execute("PRAGMA busy_timeout=0")
        holder.execute(
            "CREATE TABLE IF NOT EXISTS qa_single_writer_probe "
            "(probe_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        holder.commit()
        holder.execute("BEGIN IMMEDIATE")
        holder.execute(
            "INSERT INTO qa_single_writer_probe(probe_id, payload) VALUES (?, ?)",
            ("holder", "lock-held"),
        )
        started = time.perf_counter()
        contention_observed = False
        try:
            contender.execute("BEGIN IMMEDIATE")
            contender.execute(
                "INSERT INTO qa_single_writer_probe(probe_id, payload) VALUES (?, ?)",
                ("unexpected", "contender-wrote-before-release"),
            )
            contender.rollback()
        except sqlite3.OperationalError as error:
            contention_ms = _elapsed_ms(started)
            error_type = type(error).__name__
            error_message = str(error)
            contention_observed = "locked" in str(error).lower()
            contender.rollback()
        else:
            contention_ms = _elapsed_ms(started)

        release_started = time.perf_counter()
        holder.commit()
        release_ms = _elapsed_ms(release_started)
        retry_started = time.perf_counter()
        retry_succeeded = False
        try:
            contender.execute("BEGIN IMMEDIATE")
            contender.execute(
                "INSERT INTO qa_single_writer_probe(probe_id, payload) VALUES (?, ?)",
                ("retry", "serialized-after-release"),
            )
            contender.commit()
            retry_succeeded = True
        except sqlite3.Error:
            contender.rollback()
        retry_ms = _elapsed_ms(retry_started)
        row = contender.execute("SELECT COUNT(*) FROM qa_single_writer_probe").fetchone()
        row_count = int(row[0]) if row else 0
        return {
            "contention_observed": contention_observed,
            "retry_succeeded": retry_succeeded,
            "holder_release_ms": release_ms,
            "contention_ms": contention_ms,
            "retry_ms": retry_ms,
            "row_count": row_count,
            "error_type": error_type,
            "error": error_message,
        }
    finally:
        try:
            if holder.in_transaction:
                holder.rollback()
        finally:
            holder.close()
        try:
            if contender.in_transaction:
                contender.rollback()
        finally:
            contender.close()


def _validate_options(
    *,
    min_rows: int,
    max_stocks: int | None,
    max_rows_per_stock: int | None,
) -> None:
    if min_rows < 1:
        raise ValueError("min_rows must be at least 1")
    if max_stocks is not None and max_stocks < 1:
        raise ValueError("max_stocks must be at least 1 when supplied")
    if max_rows_per_stock is not None and max_rows_per_stock < 1:
        raise ValueError("max_rows_per_stock must be at least 1 when supplied")


def _resolve_roots(roots: Sequence[Path]) -> list[Path]:
    return [Path(root).expanduser().resolve() for root in roots if str(root).strip()]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _stock_file_token(stock_id: str) -> str:
    if _STOCK_FILE_TOKEN.fullmatch(stock_id):
        return stock_id
    return hashlib.sha256(stock_id.encode("utf-8")).hexdigest()[:16]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _close_new_file_handlers(
    logger: logging.Logger,
    existing_handlers: Sequence[logging.Handler],
) -> None:
    prior = {id(handler) for handler in existing_handlers}
    for handler in list(logger.handlers):
        if id(handler) in prior:
            continue
        if isinstance(handler, logging.FileHandler):
            handler.close()
            logger.removeHandler(handler)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-data-file", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, action="append", required=True)
    parser.add_argument("--confirm-write-probe", action="store_true")
    parser.add_argument("--stocks", nargs="+")
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--max-stocks", type=int)
    parser.add_argument("--max-rows-per-stock", type=int, default=120)
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    if args.output_json is not None:
        output_target = args.output_json.expanduser().resolve()
        protected = _resolve_roots(args.protected_root)
        if any(_is_within(output_target, root) for root in protected):
            print(
                json.dumps(
                    {
                        "schema_version": WRITE_PROBE_SCHEMA_VERSION,
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
        report = measure_write_probe(
            stock_data_file=args.stock_data_file,
            staging_root=args.staging_root,
            protected_roots=args.protected_root,
            confirm_write_probe=args.confirm_write_probe,
            stock_ids=args.stocks,
            min_rows=args.min_rows,
            max_stocks=args.max_stocks,
            max_rows_per_stock=args.max_rows_per_stock,
        )
    except (OSError, TypeError, ValueError) as error:
        report = {
            "schema_version": WRITE_PROBE_SCHEMA_VERSION,
            "status": "blocked",
            "error_type": type(error).__name__,
            "error": str(error),
            "production_write_attempted": False,
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        output_target.parent.mkdir(parents=True, exist_ok=True)
        output_target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("status") in {"measured", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
