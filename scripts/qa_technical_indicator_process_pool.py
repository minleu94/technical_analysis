"""在隔離 staging 驗證技術指標 process-pool 與 single-writer 邊界。

這個 probe 讀取呼叫端指定的 raw stock CSV，將 bounded 的股票資料送入
ProcessPoolExecutor；worker 只計算並回傳 immutable 結果，父程序才負責
逐股 CSV serialization。正式 SQLite、正式 CSV、scheduler 與 production
worker 都不會被觸碰。可選的 transient／permanent failure 只用來驗證有限
retry 與 fail-closed，不代表實際來源錯誤已消失。
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Sequence

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis_module.technical_analysis.technical_indicators import (  # noqa: E402
    TechnicalIndicatorCalculator,
)
from scripts.qa_technical_indicator_full_batch import (  # noqa: E402
    _find_stock_column,
    _normalize_requested_stock_ids,
)


PROCESS_POOL_SCHEMA_VERSION = "technical-indicator-process-pool.v1"
_MAX_WORKERS = 4
_MAX_IN_FLIGHT = 16
_MAX_RETRIES = 3
_SAFE_MAX_IDS = 100
_STOCK_FILE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")


def measure_process_pool(
    *,
    stock_data_file: Path,
    staging_root: Path,
    protected_roots: Sequence[Path],
    confirm_process_pool_probe: bool = False,
    stock_ids: Sequence[str] | None = None,
    min_rows: int = 30,
    max_stocks: int | None = None,
    max_rows_per_stock: int | None = 120,
    max_workers: int = 2,
    max_in_flight: int | None = None,
    max_retries: int = 1,
    transient_fail_stocks: Sequence[str] | None = None,
    permanent_fail_stocks: Sequence[str] | None = None,
) -> dict[str, Any]:
    """量測 real calculator 的 bounded process-pool；所有寫入都在 staging。"""

    _validate_options(
        min_rows=min_rows,
        max_stocks=max_stocks,
        max_rows_per_stock=max_rows_per_stock,
        max_workers=max_workers,
        max_in_flight=max_in_flight,
        max_retries=max_retries,
    )
    resolved_input = stock_data_file.expanduser().resolve()
    resolved_staging = staging_root.expanduser().resolve()
    resolved_protected = _resolve_roots(protected_roots)
    transient_ids = set(_normalize_requested_stock_ids(transient_fail_stocks))
    permanent_ids = set(_normalize_requested_stock_ids(permanent_fail_stocks))
    effective_in_flight = max_in_flight or max_workers * 2
    base: dict[str, Any] = {
        "schema_version": PROCESS_POOL_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stock_data_file": str(resolved_input),
        "staging_root": str(resolved_staging),
        "protected_roots": [str(path) for path in resolved_protected],
        "confirmation_required": True,
        "confirm_process_pool_probe": bool(confirm_process_pool_probe),
        "read_only": False,
        "write_attempted": False,
        "staging_write_attempted": False,
        "production_write_attempted": False,
        "sqlite_write_attempted": False,
        "production_sqlite_write_attempted": False,
        "parallelism_enabled": False,
        "staging_process_pool_enabled": False,
        "production_worker_enabled": False,
        "observed_worker_count": 0,
        "single_writer_required": True,
        "cleanup_succeeded": None,
        "options": {
            "requested_stock_ids": list(stock_ids) if stock_ids is not None else None,
            "min_rows": min_rows,
            "max_stocks": max_stocks,
            "max_rows_per_stock": max_rows_per_stock,
            "max_workers": max_workers,
            "max_in_flight": effective_in_flight,
            "max_retries": max_retries,
            "transient_fail_stocks": sorted(transient_ids),
            "permanent_fail_stocks": sorted(permanent_ids),
        },
    }
    if not confirm_process_pool_probe:
        return {
            **base,
            "status": "confirmation_required",
            "blocker": "explicit_confirm_process_pool_probe_required",
            "next_safe_step": (
                "先指定既有 staging root、protected root，並明確傳入 "
                "--confirm-process-pool-probe；未確認時不建立任何檔案。"
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
    if stock_ids is None and max_stocks is None:
        return {
            **base,
            "status": "blocked",
            "blocker": "bounded_stock_selection_required",
            "next_safe_step": "明確指定 --stocks 或 --max-stocks，避免無界 process-pool probe。",
        }

    input_hash_before = _sha256(resolved_input)
    total_started = time.perf_counter()
    report: dict[str, Any]
    try:
        with tempfile.TemporaryDirectory(
            dir=str(resolved_staging),
            prefix="technical_indicator_process_pool_",
        ) as temp_name:
            temp_root = Path(temp_name)
            report = _run_process_pool(
                stock_data_file=resolved_input,
                temp_root=temp_root,
                stock_ids=stock_ids,
                min_rows=min_rows,
                max_stocks=max_stocks,
                max_rows_per_stock=max_rows_per_stock,
                max_workers=max_workers,
                max_in_flight=effective_in_flight,
                max_retries=max_retries,
                transient_fail_stocks=transient_ids,
                permanent_fail_stocks=permanent_ids,
            )
            report = {**base, **report}
            staged_write = "csv" in report
            report["staging_write_attempted"] = staged_write
            report["write_attempted"] = staged_write
            report["sqlite_write_attempted"] = False
            report["production_write_attempted"] = False
            report["production_sqlite_write_attempted"] = False
    except (OSError, TypeError, ValueError) as error:
        report = {
            **base,
            "status": "blocked",
            "blocker": "isolated_process_pool_probe_failed",
            "error_type": type(error).__name__,
            "error": str(error),
            "stages": {"total_ms": _elapsed_ms(total_started)},
            "stocks": {},
            "rows": {},
            "next_safe_step": "檢查 staging 權限、CSV schema、worker exception 後再重跑；不要改正式 worker。",
        }
    else:
        report["stages"]["total_ms"] = _elapsed_ms(total_started)
        report["input_sha256_before"] = input_hash_before
        report["input_sha256_after"] = _sha256(resolved_input)
        report["input_unchanged"] = (
            report["input_sha256_before"] == report["input_sha256_after"]
        )
    finally:
        report["cleanup_succeeded"] = resolved_staging.is_dir() and not any(
            path.is_dir() and path.name.startswith("technical_indicator_process_pool_")
            for path in resolved_staging.iterdir()
        )

    return report


def _run_process_pool(
    *,
    stock_data_file: Path,
    temp_root: Path,
    stock_ids: Sequence[str] | None,
    min_rows: int,
    max_stocks: int | None,
    max_rows_per_stock: int | None,
    max_workers: int,
    max_in_flight: int,
    max_retries: int,
    transient_fail_stocks: set[str],
    permanent_fail_stocks: set[str],
) -> dict[str, Any]:
    logger = logging.getLogger("qa_technical_indicator_process_pool")
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
            "schema_version": PROCESS_POOL_SCHEMA_VERSION,
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

    tasks: list[tuple[str, pd.DataFrame]] = []
    insufficient_ids: list[str] = []
    input_rows = 0
    for stock_id in selected_ids:
        group = groups[stock_id]
        input_rows += len(group)
        if len(group) < min_rows:
            insufficient_ids.append(stock_id)
            continue
        if max_rows_per_stock is not None:
            group = group.tail(max_rows_per_stock).copy()
        tasks.append((stock_id, group))
    if not tasks:
        return {
            "schema_version": PROCESS_POOL_SCHEMA_VERSION,
            "status": "blocked",
            "blocker": "no_stock_group_meets_min_rows",
            "stock_code_column": stock_column,
            "stages": stages,
            "stocks": {
                "available_group_count": len(groups),
                "selected_group_count": len(selected_ids),
                "insufficient_count": len(insufficient_ids),
                "insufficient_ids": insufficient_ids[:_SAFE_MAX_IDS],
                "missing_requested_ids": missing_requested[:_SAFE_MAX_IDS],
            },
            "rows": {
                "raw_input_rows": len(frame),
                "normalized_input_rows": len(normalized),
                "selected_input_rows": input_rows,
            },
            "next_safe_step": "先提供足夠歷史 rows 的 bounded stock group，再做 process-pool probe。",
        }

    queue = list(tasks)
    attempts: dict[str, int] = {stock_id: 0 for stock_id, _ in tasks}
    in_flight: dict[
        Future[dict[str, Any]], tuple[str, pd.DataFrame, int]
    ] = {}
    results: dict[str, pd.DataFrame] = {}
    failed_ids: list[str] = []
    retry_count = 0
    max_observed_in_flight = 0
    process_ids: set[int] = set()
    dispatch_started = time.perf_counter()
    executor = ProcessPoolExecutor(max_workers=max_workers)

    def submit_available() -> None:
        nonlocal max_observed_in_flight
        while queue and len(in_flight) < max_in_flight:
            stock_id, group = queue.pop(0)
            attempts[stock_id] += 1
            future = executor.submit(
                _calculate_worker,
                stock_id,
                group,
                attempts[stock_id],
                stock_id in transient_fail_stocks,
                stock_id in permanent_fail_stocks,
            )
            in_flight[future] = (stock_id, group, attempts[stock_id])
            max_observed_in_flight = max(max_observed_in_flight, len(in_flight))

    try:
        submit_available()
        while in_flight:
            done, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            for future in sorted(
                done,
                key=lambda item: in_flight[item][0],
            ):
                stock_id, group, attempt = in_flight.pop(future)
                try:
                    payload = future.result()
                except Exception:
                    if (
                        stock_id not in permanent_fail_stocks
                        and attempts[stock_id] <= max_retries
                    ):
                        queue.append((stock_id, group))
                        retry_count += 1
                    else:
                        failed_ids.append(stock_id)
                    continue
                process_ids.add(int(payload["worker_pid"]))
                result = payload.get("result")
                if not isinstance(result, pd.DataFrame) or result.empty:
                    failed_ids.append(stock_id)
                    continue
                results[stock_id] = result
            submit_available()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    stages["process_pool_dispatch_ms"] = _elapsed_ms(dispatch_started)

    if not results:
        return {
            "schema_version": PROCESS_POOL_SCHEMA_VERSION,
            "status": "blocked",
            "blocker": "no_worker_result",
            "stock_code_column": stock_column,
            "stages": stages,
            "process_pool": {
                "configured_workers": max_workers,
                "observed_worker_count": len(process_ids),
                "observed_process_ids": sorted(process_ids),
                "max_observed_in_flight": max_observed_in_flight,
                "retry_count": retry_count,
            },
            "stocks": {
                "available_group_count": len(groups),
                "selected_group_count": len(selected_ids),
                "measured_count": 0,
                "failed_count": len(failed_ids),
                "failed_ids": failed_ids[:_SAFE_MAX_IDS],
                "insufficient_ids": insufficient_ids[:_SAFE_MAX_IDS],
                "missing_requested_ids": missing_requested[:_SAFE_MAX_IDS],
            },
            "rows": {
                "raw_input_rows": len(frame),
                "normalized_input_rows": len(normalized),
                "selected_input_rows": input_rows,
            },
            "next_safe_step": "先修正 worker exception 或 raw schema，再做 staging serialization。",
        }

    technical_dir = temp_root / "technical"
    technical_dir.mkdir(parents=True, exist_ok=False)
    csv_started = time.perf_counter()
    csv_files: list[dict[str, Any]] = []
    for stock_id, result in sorted(results.items()):
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
    aggregate = pd.concat(list(results.values()), ignore_index=True)
    aggregate_target = temp_root / "technical_indicators_all.csv"
    aggregate_started = time.perf_counter()
    aggregate.to_csv(aggregate_target, index=False, encoding="utf-8-sig")
    stages["aggregate_csv_write_ms"] = _elapsed_ms(aggregate_started)
    complete = not failed_ids and not insufficient_ids and not missing_requested
    bounded_ok = max_observed_in_flight <= max_in_flight
    status = "measured" if complete and bounded_ok else "partial"
    return {
        "schema_version": PROCESS_POOL_SCHEMA_VERSION,
        "status": status,
        "blocker": None if status == "measured" else "some_stock_groups_not_measured",
        "stock_code_column": stock_column,
        "staging_process_pool_enabled": True,
        "parallelism_enabled": False,
        "production_worker_enabled": False,
        "stages": stages,
        "process_pool": {
            "configured_workers": max_workers,
            "observed_worker_count": len(process_ids),
            "observed_process_ids": sorted(process_ids),
            "max_observed_in_flight": max_observed_in_flight,
            "max_in_flight": max_in_flight,
            "retry_count": retry_count,
            "bounded_in_flight": bounded_ok,
        },
        "observed_worker_count": len(process_ids),
        "stocks": {
            "available_group_count": len(groups),
            "selected_group_count": len(selected_ids),
            "measured_count": len(results),
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids[:_SAFE_MAX_IDS],
            "insufficient_count": len(insufficient_ids),
            "insufficient_ids": insufficient_ids[:_SAFE_MAX_IDS],
            "missing_requested_ids": missing_requested[:_SAFE_MAX_IDS],
        },
        "rows": {
            "raw_input_rows": len(frame),
            "normalized_input_rows": len(normalized),
            "selected_input_rows": input_rows,
            "calculated_rows": int(sum(len(result) for result in results.values())),
            "aggregate_rows": len(aggregate),
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
        "checks": {
            "process_pool_started": bool(process_ids),
            "bounded_in_flight": bounded_ok,
            "parent_single_writer": True,
            "retry_budget_respected": retry_count <= max_retries * len(tasks),
            "no_worker_sqlite_write": True,
        },
        "next_safe_step": (
            "以此 process-pool 結果再做真實 crash recovery／取消 acceptance；"
            "SQLite 與整合 CSV 維持 parent single writer，broker fetch 仍需獨立限流驗收。"
        ),
    }


def _calculate_worker(
    stock_id: str,
    group: pd.DataFrame,
    attempt: int,
    transient_failure: bool,
    permanent_failure: bool,
) -> dict[str, Any]:
    if permanent_failure or (transient_failure and attempt == 1):
        raise RuntimeError(f"synthetic worker failure: {stock_id}, attempt={attempt}")
    logger = logging.getLogger(f"qa_worker_{os.getpid()}")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    calculator = TechnicalIndicatorCalculator(logger=logger)
    result = calculator.calculate_all_indicators(group, stock_id)
    return {
        "stock_id": stock_id,
        "worker_pid": os.getpid(),
        "attempt": attempt,
        "result": result,
    }


def _validate_options(
    *,
    min_rows: int,
    max_stocks: int | None,
    max_rows_per_stock: int | None,
    max_workers: int,
    max_in_flight: int | None,
    max_retries: int,
) -> None:
    if min_rows < 1:
        raise ValueError("min_rows must be at least 1")
    if max_stocks is not None and max_stocks < 1:
        raise ValueError("max_stocks must be at least 1 when supplied")
    if max_rows_per_stock is not None and max_rows_per_stock < 1:
        raise ValueError("max_rows_per_stock must be at least 1 when supplied")
    if max_workers < 1 or max_workers > _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    if max_in_flight is not None and (
        max_in_flight < 1 or max_in_flight > _MAX_IN_FLIGHT
    ):
        raise ValueError(f"max_in_flight must be between 1 and {_MAX_IN_FLIGHT}")
    if max_retries < 0 or max_retries > _MAX_RETRIES:
        raise ValueError(f"max_retries must be between 0 and {_MAX_RETRIES}")


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
    parser.add_argument("--confirm-process-pool-probe", action="store_true")
    parser.add_argument("--stocks", nargs="+")
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--max-stocks", type=int)
    parser.add_argument("--max-rows-per-stock", type=int, default=120)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--transient-fail-stocks", nargs="*", default=None)
    parser.add_argument("--permanent-fail-stocks", nargs="*", default=None)
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
                        "schema_version": PROCESS_POOL_SCHEMA_VERSION,
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
        report = measure_process_pool(
            stock_data_file=args.stock_data_file,
            staging_root=args.staging_root,
            protected_roots=args.protected_root,
            confirm_process_pool_probe=args.confirm_process_pool_probe,
            stock_ids=args.stocks,
            min_rows=args.min_rows,
            max_stocks=args.max_stocks,
            max_rows_per_stock=args.max_rows_per_stock,
            max_workers=args.workers,
            max_in_flight=args.max_in_flight,
            max_retries=args.max_retries,
            transient_fail_stocks=args.transient_fail_stocks,
            permanent_fail_stocks=args.permanent_fail_stocks,
        )
    except (OSError, TypeError, ValueError) as error:
        report = {
            "schema_version": PROCESS_POOL_SCHEMA_VERSION,
            "status": "blocked",
            "error_type": type(error).__name__,
            "error": str(error),
            "production_write_attempted": False,
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        output_target = args.output_json.expanduser().resolve()
        output_target.parent.mkdir(parents=True, exist_ok=True)
        output_target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("status") in {"measured", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
