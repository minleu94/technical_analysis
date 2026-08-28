"""Bounded technical-indicator workers with a parent-only writer boundary.

The worker side of this module is deliberately calculation-only.  Workers return
``pandas.DataFrame`` objects to the coordinating process; CSV and SQLite writes
remain in the caller so an opt-in process pool cannot create concurrent writers.
The coordinator is bounded and fail-closed: a worker exception may be retried
within the configured budget, but it is never silently replaced by a serial
fallback.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
import logging
import os
from typing import Any, Callable, Sequence

import pandas as pd


PROCESS_POOL_SCHEMA_VERSION = "technical-indicator-production-pool.v1"
DEFAULT_MAX_WORKERS = 2
DEFAULT_MAX_IN_FLIGHT = 4
DEFAULT_MAX_RETRIES = 1
MAX_WORKERS = 4
MAX_IN_FLIGHT = 16
MAX_RETRIES = 3


def run_bounded_indicator_pool(
    tasks: Sequence[tuple[str, pd.DataFrame]],
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    max_in_flight: int | None = DEFAULT_MAX_IN_FLIGHT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    cancel_callback: Callable[[], bool] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Calculate prepared stock groups in a bounded process pool.

    ``tasks`` must already contain the exact warm-up / incremental frame that
    the parent intends to calculate.  This keeps date filtering in the parent
    and prevents a worker from making a different look-ahead decision.
    """

    _validate_options(
        max_workers=max_workers,
        max_in_flight=max_in_flight,
        max_retries=max_retries,
    )
    normalized_tasks = [
        (str(stock_id), group.copy())
        for stock_id, group in tasks
        if str(stock_id).strip() and isinstance(group, pd.DataFrame)
    ]
    effective_in_flight = max_in_flight or max_workers * 2
    log = logger or logging.getLogger(__name__)
    base: dict[str, Any] = {
        "schema_version": PROCESS_POOL_SCHEMA_VERSION,
        "enabled": True,
        "single_writer_required": True,
        "worker_writes": False,
        "sqlite_worker_writes": False,
        "configured_workers": max_workers,
        "max_in_flight": effective_in_flight,
        "max_retries": max_retries,
        "task_count": len(normalized_tasks),
        "observed_worker_count": 0,
        "observed_process_ids": [],
        "max_observed_in_flight": 0,
        "retry_count": 0,
        "pool_restart_count": 0,
        "failed_ids": [],
        "cancelled_ids": [],
        "attempts": {},
        "results": {},
    }
    if not normalized_tasks:
        return {**base, "status": "empty"}

    queue: list[tuple[str, pd.DataFrame]] = list(normalized_tasks)
    attempts = {stock_id: 0 for stock_id, _ in normalized_tasks}
    in_flight: dict[Future[dict[str, Any]], tuple[str, pd.DataFrame]] = {}
    results: dict[str, pd.DataFrame] = {}
    failed_ids: list[str] = []
    cancelled_ids: list[str] = []
    process_ids: set[int] = set()
    retry_count = 0
    pool_restart_count = 0
    max_observed_in_flight = 0
    cancelled = False
    executor: ProcessPoolExecutor | None = None

    def new_executor() -> ProcessPoolExecutor:
        return ProcessPoolExecutor(max_workers=max_workers)

    def submit_available() -> None:
        nonlocal max_observed_in_flight
        if executor is None:
            return
        while queue and len(in_flight) < effective_in_flight:
            stock_id, group = queue.pop(0)
            attempts[stock_id] += 1
            future = executor.submit(_calculate_worker, stock_id, group)
            in_flight[future] = (stock_id, group)
            max_observed_in_flight = max(max_observed_in_flight, len(in_flight))

    def retry_or_fail(stock_id: str, group: pd.DataFrame) -> None:
        nonlocal retry_count
        if attempts[stock_id] <= max_retries:
            queue.append((stock_id, group))
            retry_count += 1
        else:
            failed_ids.append(stock_id)

    try:
        executor = new_executor()
        submit_available()
        while in_flight or queue:
            if _is_cancel_requested(cancel_callback):
                cancelled = True
                cancelled_ids.extend(stock_id for stock_id, _ in queue)
                queue.clear()
                cancelled_ids.extend(stock_id for stock_id, _ in in_flight.values())
                for future in in_flight:
                    future.cancel()
                in_flight.clear()
                break
            if not in_flight:
                submit_available()
                continue
            done, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            broken = False
            for future in sorted(done, key=lambda item: in_flight[item][0]):
                stock_id, group = in_flight.pop(future)
                try:
                    payload = future.result()
                except BrokenProcessPool:
                    broken = True
                    retry_or_fail(stock_id, group)
                    break
                except Exception as exc:  # noqa: BLE001
                    log.warning("technical indicator worker failed for %s: %s", stock_id, exc)
                    retry_or_fail(stock_id, group)
                    continue
                process_id = payload.get("worker_pid")
                if process_id is not None:
                    process_ids.add(int(process_id))
                result = payload.get("result")
                if not isinstance(result, pd.DataFrame) or result.empty:
                    retry_or_fail(stock_id, group)
                    continue
                results[stock_id] = result
            if broken:
                # BrokenProcessPool invalidates every future still associated
                # with the old executor.  Requeue those exact frames under the
                # same retry budget and recreate the bounded pool.
                for pending_stock_id, pending_group in in_flight.values():
                    retry_or_fail(pending_stock_id, pending_group)
                in_flight.clear()
                pool_restart_count += 1
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
                executor = new_executor()
            submit_available()
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    unique_failed = list(dict.fromkeys(failed_ids))
    unique_cancelled = list(dict.fromkeys(cancelled_ids))
    if cancelled:
        status = "cancelled"
    elif unique_failed:
        status = "failed"
    elif len(results) == len(normalized_tasks):
        status = "completed"
    else:
        status = "partial"
    return {
        **base,
        "status": status,
        "observed_worker_count": len(process_ids),
        "observed_process_ids": sorted(process_ids),
        "max_observed_in_flight": max_observed_in_flight,
        "retry_count": retry_count,
        "pool_restart_count": pool_restart_count,
        "failed_ids": unique_failed,
        "cancelled_ids": unique_cancelled,
        "attempts": attempts,
        "results": results,
    }


def _calculate_worker(stock_id: str, group: pd.DataFrame) -> dict[str, Any]:
    """Process entry point; never writes a file or opens SQLite."""

    from analysis_module.technical_analysis.technical_indicators import (
        TechnicalIndicatorCalculator,
    )

    worker_logger = logging.getLogger(f"technical_indicator_worker_{os.getpid()}")
    worker_logger.handlers.clear()
    worker_logger.addHandler(logging.NullHandler())
    calculator = TechnicalIndicatorCalculator(logger=worker_logger)
    result = calculator.calculate_all_indicators(group, stock_id)
    return {
        "stock_id": stock_id,
        "worker_pid": os.getpid(),
        "result": result,
    }


def _validate_options(
    *,
    max_workers: int,
    max_in_flight: int | None,
    max_retries: int,
) -> None:
    if max_workers < 1 or max_workers > MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {MAX_WORKERS}")
    effective_in_flight = max_in_flight or max_workers * 2
    if effective_in_flight < 1 or effective_in_flight > MAX_IN_FLIGHT:
        raise ValueError(f"max_in_flight must be between 1 and {MAX_IN_FLIGHT}")
    if max_retries < 0 or max_retries > MAX_RETRIES:
        raise ValueError(f"max_retries must be between 0 and {MAX_RETRIES}")


def _is_cancel_requested(callback: Callable[[], bool] | None) -> bool:
    if callback is None:
        return False
    try:
        return bool(callback())
    except Exception:  # noqa: BLE001
        return False
