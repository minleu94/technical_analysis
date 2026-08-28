"""在隔離 staging 驗證技術指標 worker 的 crash recovery 與取消邊界。

這個 probe 會先呼叫既有的 real calculator bounded process-pool，再以同一
份受控 raw CSV 驗證兩個 production 前置條件：worker process 意外退出後
能重建 pool 並完成下一個計算，以及取消後不再提交尚未完成的結果。worker
只回傳 immutable 計算結果，父程序才是唯一 writer；正式 SQLite、正式 CSV、
scheduler 與 production worker 都不會被觸碰。production single-writer
integration 仍刻意標成 ``not_completed``，不能用 staging probe 冒充。
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Sequence

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis_module.technical_analysis.technical_indicators import (  # noqa: E402
    TechnicalIndicatorCalculator,
)
from scripts.qa_technical_indicator_process_pool import (  # noqa: E402
    _find_stock_column,
    _normalize_requested_stock_ids,
    measure_process_pool,
)


RECOVERY_SCHEMA_VERSION = "technical-indicator-worker-recovery.v1"
_MAX_WORKERS = 4
_MAX_IN_FLIGHT = 16
_MAX_RETRIES = 3
_MAX_TASKS = 16


def measure_worker_recovery(
    *,
    stock_data_file: Path,
    staging_root: Path,
    protected_roots: Sequence[Path],
    confirm_probe: bool = False,
    stock_ids: Sequence[str] = ("0050", "2330"),
    min_rows: int = 30,
    max_rows_per_stock: int = 120,
    max_workers: int = 2,
    max_in_flight: int | None = None,
    max_retries: int = 1,
) -> dict[str, Any]:
    """量測 real calculator、process crash recovery 與 cooperative cancel。"""

    _validate_options(
        min_rows=min_rows,
        max_rows_per_stock=max_rows_per_stock,
        max_workers=max_workers,
        max_in_flight=max_in_flight,
        max_retries=max_retries,
    )
    resolved_input = stock_data_file.expanduser().resolve()
    resolved_staging = staging_root.expanduser().resolve()
    resolved_protected = tuple(
        item.expanduser().resolve() for item in protected_roots if str(item).strip()
    )
    normalized_stock_ids = _normalize_requested_stock_ids(stock_ids)
    effective_in_flight = max_in_flight or max_workers * 2
    base: dict[str, Any] = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stock_data_file": str(resolved_input),
        "staging_root": str(resolved_staging),
        "protected_roots": [str(item) for item in resolved_protected],
        "confirmation_required": True,
        "confirm_probe": bool(confirm_probe),
        "read_only": False,
        "write_attempted": False,
        "staging_write_attempted": False,
        "production_write_attempted": False,
        "sqlite_write_attempted": False,
        "production_sqlite_write_attempted": False,
        "parallelism_enabled": False,
        "staging_process_pool_enabled": False,
        "production_worker_enabled": False,
        "single_writer_required": True,
        "production_single_writer_integration": {
            "status": "not_completed",
            "reason": "production worker and writer wiring require a separate owner-approved integration change",
        },
    }
    if not confirm_probe:
        return {
            **base,
            "status": "confirmation_required",
            "blocker": "explicit_confirm_probe_required",
            "next_safe_step": "指定隔離 staging/protected root 並傳入 --confirm-probe；未確認時不建立任何檔案。",
        }
    if not normalized_stock_ids:
        return {
            **base,
            "status": "blocked",
            "blocker": "bounded_stock_selection_required",
            "next_safe_step": "明確指定至少一檔股票，避免無界 process-pool recovery probe。",
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
            "next_safe_step": "建立專用 staging root 後再重跑；probe 不會自動建立根目錄。",
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

    base_report = measure_process_pool(
        stock_data_file=resolved_input,
        staging_root=resolved_staging,
        protected_roots=resolved_protected,
        confirm_process_pool_probe=True,
        stock_ids=normalized_stock_ids,
        min_rows=min_rows,
        max_stocks=len(normalized_stock_ids),
        max_rows_per_stock=max_rows_per_stock,
        max_workers=max_workers,
        max_in_flight=effective_in_flight,
        max_retries=max_retries,
        transient_fail_stocks=(normalized_stock_ids[0],),
    )
    # Keep the real process-pool measurements (including staging write flags)
    # while replacing only the artifact schema and recovery metadata below.
    report: dict[str, Any] = {**base, **base_report}
    report["schema_version"] = RECOVERY_SCHEMA_VERSION
    report["stock_data_file"] = str(resolved_input)
    report["staging_root"] = str(resolved_staging)
    report["protected_roots"] = [str(item) for item in resolved_protected]
    report["confirm_probe"] = True
    report["production_single_writer_integration"] = base[
        "production_single_writer_integration"
    ]

    if base_report.get("status") != "measured":
        report.update(
            {
                "status": "blocked",
                "blocker": "real_calculator_process_pool_not_measured",
                "crash_recovery": {
                    "status": "not_run",
                    "reason": "base process-pool acceptance did not measure all requested stocks",
                },
                "cancellation": {
                    "status": "not_run",
                    "reason": "base process-pool acceptance did not measure all requested stocks",
                },
                "checks": {},
            }
        )
        return report

    groups = _load_groups(
        resolved_input,
        stock_ids=normalized_stock_ids,
        min_rows=min_rows,
        max_rows_per_stock=max_rows_per_stock,
    )
    if not groups:
        report.update(
            {
                "status": "blocked",
                "blocker": "recovery_stock_groups_missing",
                "crash_recovery": {"status": "not_run"},
                "cancellation": {"status": "not_run"},
                "checks": {},
            }
        )
        return report

    recovery = _run_crash_recovery(groups[0])
    cancellation = _run_cancellation(groups)
    base_checks = base_report.get("checks")
    base_checks_mapping = base_checks if isinstance(base_checks, dict) else {}
    checks = {
        "real_calculator_process_pool": base_report.get("status") == "measured",
        "bounded_in_flight": base_checks_mapping.get("bounded_in_flight") is True,
        "parent_single_writer": base_checks_mapping.get("parent_single_writer") is True,
        "retry_budget_respected": base_checks_mapping.get("retry_budget_respected") is True,
        "no_worker_sqlite_write": base_checks_mapping.get("no_worker_sqlite_write") is True,
        "crash_recovery": recovery.get("status") == "measured",
        "cancellation": cancellation.get("status") == "measured",
        "no_production_write": (
            base_report.get("production_write_attempted") is False
            and base_report.get("production_sqlite_write_attempted") is False
        ),
    }
    report.update(
        {
            "status": "measured" if all(checks.values()) else "partial",
            "blocker": None if all(checks.values()) else "worker_recovery_acceptance_failed",
            "staging_process_pool_enabled": True,
            "production_worker_enabled": False,
            "parallelism_enabled": False,
            "checks": checks,
            "crash_recovery": recovery,
            "cancellation": cancellation,
            "worker_recovery_stock_count": len(groups),
            "worker_recovery_input_sha256": _sha256(resolved_input),
            "next_safe_step": "把 recovery/cancellation contract 映射到 production technical writer；完成前維持 worker 關閉，再由 owner 核准 broker canary。",
        }
    )
    report["observed_worker_count"] = max(
        int(base_report.get("observed_worker_count", 0) or 0),
        int(recovery.get("recovered_worker_pid") is not None),
    )
    report["cleanup_succeeded"] = bool(base_report.get("cleanup_succeeded")) and not any(
        path.name.startswith("technical_indicator_process_pool_")
        for path in resolved_staging.iterdir()
    )
    return report


def _load_groups(
    path: Path,
    *,
    stock_ids: Sequence[str],
    min_rows: int,
    max_rows_per_stock: int,
) -> list[tuple[str, pd.DataFrame]]:
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, low_memory=False)
    stock_column = _find_stock_column(frame.columns)
    if stock_column is None:
        return []
    normalized = frame.copy()
    normalized[stock_column] = normalized[stock_column].astype(str).str.strip()
    normalized = normalized[normalized[stock_column].ne("")].copy()
    grouped = {
        str(stock_id): group.copy()
        for stock_id, group in normalized.groupby(stock_column, sort=True)
    }
    requested = _normalize_requested_stock_ids(stock_ids)
    selected = [item for item in requested if item in grouped]
    result: list[tuple[str, pd.DataFrame]] = []
    for stock_id in selected:
        group = grouped[stock_id]
        if len(group) < min_rows:
            continue
        result.append((stock_id, group.tail(max_rows_per_stock).copy()))
    return result


def _run_crash_recovery(group: tuple[str, pd.DataFrame]) -> dict[str, Any]:
    stock_id, frame = group
    started = time.perf_counter()
    crash_observed = False
    crash_exception = ""
    crashed_executor = ProcessPoolExecutor(max_workers=1)
    try:
        future = crashed_executor.submit(_crash_worker)
        try:
            future.result(timeout=30)
        except BrokenProcessPool as exc:
            crash_observed = True
            crash_exception = type(exc).__name__
        except Exception as exc:  # pragma: no cover - platform-specific wrapper
            crash_exception = type(exc).__name__
    finally:
        crashed_executor.shutdown(wait=True, cancel_futures=True)

    recovered_pid: int | None = None
    recovered_rows = 0
    recovery_exception: str | None = None
    recovered_executor = ProcessPoolExecutor(max_workers=1)
    try:
        recovered = recovered_executor.submit(_calculate_worker, stock_id, frame)
        payload = recovered.result(timeout=60)
        recovered_pid = int(payload["worker_pid"])
        result = payload.get("result")
        if isinstance(result, pd.DataFrame):
            recovered_rows = len(result)
    except Exception as exc:  # pragma: no cover - platform-specific wrapper
        recovery_exception = type(exc).__name__
    finally:
        recovered_executor.shutdown(wait=True, cancel_futures=True)
    status = "measured" if crash_observed and recovered_pid is not None and recovered_rows > 0 else "blocked"
    return {
        "status": status,
        "crash_observed": crash_observed,
        "crash_exception": crash_exception or None,
        "recovered_worker_pid": recovered_pid,
        "recovered_rows": recovered_rows,
        "recovery_exception": recovery_exception,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "worker_wrote": False,
        "sqlite_write_attempted": False,
    }


def _run_cancellation(groups: Sequence[tuple[str, pd.DataFrame]]) -> dict[str, Any]:
    started = time.perf_counter()
    main_process_id = os.getpid()
    tasks = [
        (f"cancel-{index}", stock_id, frame, 300)
        for index in range(max(8, len(groups) * 4))
        for stock_id, frame in groups[:1]
    ]
    tasks = tasks[:_MAX_TASKS]
    executor = ProcessPoolExecutor(max_workers=1)
    futures: dict[Future[dict[str, Any]], str] = {}
    try:
        for task_id, stock_id, frame, delay_ms in tasks:
            futures[executor.submit(_delayed_calculate_worker, task_id, stock_id, frame, delay_ms)] = task_id
        time.sleep(0.03)
        cancellation_requested = True
        cancelled_ids: list[str] = []
        for future, task_id in list(futures.items()):
            if future.cancel():
                cancelled_ids.append(task_id)
        done, pending = wait(tuple(futures), timeout=90)
        discarded_after_cancel = 0
        for future in done:
            if future.cancelled():
                continue
            try:
                future.result()
            except Exception:
                continue
            discarded_after_cancel += 1
        status = "measured" if cancellation_requested and bool(cancelled_ids) else "blocked"
        return {
            "status": status,
            "task_count": len(tasks),
            "cancellation_requested": cancellation_requested,
            "cancelled_ids": sorted(cancelled_ids),
            "pending_after_wait": len(pending),
            "discarded_after_cancel_count": discarded_after_cancel,
            "worker_wrote": False,
            "sqlite_write_attempted": False,
            "main_process_id": main_process_id,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def _calculate_worker(stock_id: str, frame: pd.DataFrame) -> dict[str, Any]:
    logger = logging.getLogger(f"qa_recovery_worker_{os.getpid()}")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    result = TechnicalIndicatorCalculator(logger=logger).calculate_all_indicators(
        frame, stock_id
    )
    return {"stock_id": stock_id, "worker_pid": os.getpid(), "result": result}


def _delayed_calculate_worker(
    task_id: str,
    stock_id: str,
    frame: pd.DataFrame,
    delay_ms: int,
) -> dict[str, Any]:
    time.sleep(delay_ms / 1000)
    payload = _calculate_worker(stock_id, frame)
    payload["task_id"] = task_id
    return payload


def _crash_worker() -> None:
    os._exit(91)


def _validate_options(
    *,
    min_rows: int,
    max_rows_per_stock: int,
    max_workers: int,
    max_in_flight: int | None,
    max_retries: int,
) -> None:
    if min_rows < 1:
        raise ValueError("min_rows must be at least 1")
    if max_rows_per_stock < min_rows:
        raise ValueError("max_rows_per_stock must be at least min_rows")
    if max_workers < 1 or max_workers > _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    if max_in_flight is not None and not 1 <= max_in_flight <= _MAX_IN_FLIGHT:
        raise ValueError(f"max_in_flight must be between 1 and {_MAX_IN_FLIGHT}")
    if max_retries < 0 or max_retries > _MAX_RETRIES:
        raise ValueError(f"max_retries must be between 0 and {_MAX_RETRIES}")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    parser.add_argument("--confirm-probe", action="store_true")
    parser.add_argument("--stocks", nargs="+", default=["0050", "2330"])
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--max-rows-per-stock", type=int, default=120)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    protected = tuple(path.expanduser().resolve() for path in args.protected_root)
    if args.output_json is not None:
        output_target = args.output_json.expanduser().resolve()
        if any(_is_within(output_target, root) for root in protected):
            print(json.dumps({"status": "blocked", "blocker": "output_inside_protected_root"}))
            return 2
    try:
        report = measure_worker_recovery(
            stock_data_file=args.stock_data_file,
            staging_root=args.staging_root,
            protected_roots=args.protected_root,
            confirm_probe=args.confirm_probe,
            stock_ids=args.stocks,
            min_rows=args.min_rows,
            max_rows_per_stock=args.max_rows_per_stock,
            max_workers=args.workers,
            max_in_flight=args.max_in_flight,
            max_retries=args.max_retries,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        report = {
            "schema_version": RECOVERY_SCHEMA_VERSION,
            "status": "blocked",
            "error_type": type(error).__name__,
            "error": str(error),
            "production_write_attempted": False,
            "production_sqlite_write_attempted": False,
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        target = args.output_json.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("status") in {"measured", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
