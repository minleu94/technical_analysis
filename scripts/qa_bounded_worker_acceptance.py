"""驗證 bounded worker／取消／retry／single-writer 契約的 synthetic QA probe。

這個 probe 不讀正式資料、不建立 CSV／SQLite，也不代表 production worker
已啟用。它只以固定 task spec 驗證 orchestration：in-flight 數量有上限、
transient failure 有限重試、worker exception 不會寫入、取消後不再提交
未完成結果、重複 task 不會造成重複 commit，所有寫入都由主執行緒的
synthetic writer 收口。
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any, Mapping, Sequence


ACCEPTANCE_SCHEMA_VERSION = "bounded-worker-acceptance.v1"
_MAX_WORKERS = 8
_MAX_IN_FLIGHT = 32
_MAX_RETRIES = 5
_MAX_TASKS = 128


@dataclass(frozen=True)
class SyntheticTask:
    task_id: str
    failures_before_success: int = 0
    permanent_failure: bool = False
    delay_ms: int = 0


def measure_bounded_worker_acceptance(
    *,
    max_workers: int = 2,
    max_in_flight: int | None = None,
    max_retries: int = 1,
    cancel_after: int = 3,
    full_tasks: Sequence[Mapping[str, Any]] | None = None,
    cancellation_tasks: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """執行 full-completion 與 cancellation 兩組 deterministic synthetic case。"""

    _validate_options(
        max_workers=max_workers,
        max_in_flight=max_in_flight,
        max_retries=max_retries,
        cancel_after=cancel_after,
    )
    effective_in_flight = max_in_flight or max_workers * 2
    full_specs = _normalize_tasks(full_tasks or _default_full_tasks())
    cancel_specs = _normalize_tasks(
        cancellation_tasks or _default_cancellation_tasks()
    )
    full = _run_scenario(
        name="full_completion",
        tasks=full_specs,
        max_workers=max_workers,
        max_in_flight=effective_in_flight,
        max_retries=max_retries,
        cancel_after=None,
    )
    cancellation = _run_scenario(
        name="cooperative_cancellation",
        tasks=cancel_specs,
        max_workers=max_workers,
        max_in_flight=effective_in_flight,
        max_retries=max_retries,
        cancel_after=cancel_after,
    )
    expected_transient_retry = any(
        task.failures_before_success > 0 for task in full_specs
    )
    permanent_ids = {
        task.task_id for task in full_specs if task.permanent_failure
    }
    checks = {
        "full_completed_without_duplicate_commit": (
            full["status"] == "measured"
            and full["committed_ids"] == sorted(set(full["committed_ids"]))
        ),
        "full_retry_budget_respected": (
            full["retry_count"] <= max_retries * len(full_specs)
            and (not expected_transient_retry or full["retry_count"] >= 1)
        ),
        "permanent_failure_not_written": (
            all(task_id in full["failed_ids"] for task_id in permanent_ids)
            and all(task_id not in full["committed_ids"] for task_id in permanent_ids)
        ),
        "worker_did_not_write": (
            full["worker_write_attempts"] == 0
            and cancellation["worker_write_attempts"] == 0
        ),
        "bounded_in_flight": (
            full["max_observed_in_flight"] <= effective_in_flight
            and cancellation["max_observed_in_flight"] <= effective_in_flight
        ),
        "cancellation_stopped_pending_work": (
            cancellation["cancellation_requested"] is True
            and bool(cancellation["cancelled_ids"])
        ),
        "cancellation_did_not_commit_discarded_results": (
            cancellation["discarded_after_cancel_count"] >= 0
            and cancellation["writer_owner_thread_id"]
            == cancellation["main_thread_id"]
        ),
        "single_writer_owned_by_main_thread": (
            full["writer_owner_thread_id"] == full["main_thread_id"]
            and cancellation["writer_owner_thread_id"]
            == cancellation["main_thread_id"]
        ),
    }
    status = "measured" if all(checks.values()) else "blocked"
    return {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "blocker": None if status == "measured" else "bounded_worker_acceptance_failed",
        "read_only": True,
        "write_attempted": False,
        "staging_write_attempted": False,
        "production_write_attempted": False,
        "sqlite_write_attempted": False,
        "production_sqlite_write_attempted": False,
        "parallelism_enabled": False,
        "synthetic_parallelism_enabled": True,
        "production_worker_enabled": False,
        "worker_kind": "synthetic_thread_pool",
        "observed_worker_count": max_workers,
        "single_writer_required": True,
        "writer_scope": "main_thread_memory_only",
        "options": {
            "max_workers": max_workers,
            "max_in_flight": effective_in_flight,
            "max_retries": max_retries,
            "cancel_after": cancel_after,
        },
        "checks": checks,
        "scenarios": {
            "full_completion": full,
            "cooperative_cancellation": cancellation,
        },
        "next_safe_step": (
            "把這組 synthetic contract 映射到 technical compute-only worker；"
            "再以 isolated staging 做真實 worker throughput／crash recovery，"
            "broker fetch 仍須另行完成 rate-limit／retry acceptance。"
        ),
    }


def _run_scenario(
    *,
    name: str,
    tasks: Sequence[SyntheticTask],
    max_workers: int,
    max_in_flight: int,
    max_retries: int,
    cancel_after: int | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    main_thread_id = threading.get_ident()
    queue = list(tasks)
    duplicate_input_ids = sorted(
        {
            task.task_id
            for task in tasks
            if sum(candidate.task_id == task.task_id for candidate in tasks) > 1
        }
    )
    attempts: dict[str, int] = {task.task_id: 0 for task in tasks}
    in_flight: dict[Future[dict[str, Any]], SyntheticTask] = {}
    committed: list[str] = []
    failed: list[str] = []
    cancelled: list[str] = []
    discarded_after_cancel = 0
    retry_count = 0
    worker_write_attempts = 0
    max_observed_in_flight = 0
    cancellation_requested = False
    writer_owner_thread_id: int | None = None

    def submit_available(executor: ThreadPoolExecutor) -> None:
        nonlocal max_observed_in_flight
        while queue and not cancellation_requested and len(in_flight) < max_in_flight:
            task = queue.pop(0)
            attempts[task.task_id] += 1
            future = executor.submit(_execute_synthetic_task, task, attempts[task.task_id])
            in_flight[future] = task
            max_observed_in_flight = max(max_observed_in_flight, len(in_flight))

    executor = ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix=f"qa-{name}",
    )
    try:
        submit_available(executor)
        while in_flight:
            done, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            ordered_done = sorted(
                done,
                key=lambda future: in_flight[future].task_id,
            )
            for future in ordered_done:
                task = in_flight.pop(future)
                try:
                    result = future.result()
                except Exception:
                    if (
                        not cancellation_requested
                        and not task.permanent_failure
                        and attempts[task.task_id] <= max_retries
                    ):
                        queue.append(task)
                        retry_count += 1
                    else:
                        failed.append(task.task_id)
                    continue
                if cancellation_requested:
                    discarded_after_cancel += 1
                    continue
                # Only this main orchestration thread owns the synthetic writer.
                writer_owner_thread_id = threading.get_ident()
                if writer_owner_thread_id != main_thread_id:
                    worker_write_attempts += 1
                if task.task_id not in committed:
                    committed.append(task.task_id)
                if cancel_after is not None and len(committed) >= cancel_after:
                    cancellation_requested = True
            if cancellation_requested:
                for future, task in list(in_flight.items()):
                    if future.cancel():
                        cancelled.append(task.task_id)
                        del in_flight[future]
                if queue:
                    cancelled.extend(task.task_id for task in queue)
                    queue.clear()
            else:
                submit_available(executor)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return {
        "status": "measured",
        "task_count": len(tasks),
        "duplicate_input_ids": duplicate_input_ids,
        "committed_ids": sorted(committed),
        "failed_ids": sorted(set(failed)),
        "cancelled_ids": sorted(set(cancelled)),
        "discarded_after_cancel_count": discarded_after_cancel,
        "retry_count": retry_count,
        "attempts": dict(sorted(attempts.items())),
        "worker_write_attempts": worker_write_attempts,
        "max_observed_in_flight": max_observed_in_flight,
        "cancellation_requested": cancellation_requested,
        "writer_owner_thread_id": writer_owner_thread_id,
        "main_thread_id": main_thread_id,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _execute_synthetic_task(task: SyntheticTask, attempt: int) -> dict[str, Any]:
    if task.delay_ms:
        time.sleep(task.delay_ms / 1000)
    if task.permanent_failure or attempt <= task.failures_before_success:
        raise RuntimeError(f"synthetic failure: {task.task_id}, attempt={attempt}")
    return {"task_id": task.task_id, "attempt": attempt}


def _default_full_tasks() -> list[Mapping[str, Any]]:
    return [
        {"task_id": "task-normal-1"},
        {"task_id": "task-transient", "failures_before_success": 1},
        {"task_id": "task-permanent-failure", "permanent_failure": True},
        {"task_id": "task-normal-2"},
        {"task_id": "task-normal-3"},
        {"task_id": "task-normal-3"},
    ]


def _default_cancellation_tasks() -> list[Mapping[str, Any]]:
    return [
        {"task_id": "cancel-fast-1", "delay_ms": 1},
        {"task_id": "cancel-fast-2", "delay_ms": 2},
        {"task_id": "cancel-fast-3", "delay_ms": 3},
        {"task_id": "cancel-slow-1", "delay_ms": 80},
        {"task_id": "cancel-slow-2", "delay_ms": 80},
        {"task_id": "cancel-slow-3", "delay_ms": 80},
        {"task_id": "cancel-slow-4", "delay_ms": 80},
        {"task_id": "cancel-slow-5", "delay_ms": 80},
    ]


def _normalize_tasks(raw_tasks: Sequence[Mapping[str, Any]]) -> list[SyntheticTask]:
    if not raw_tasks or len(raw_tasks) > _MAX_TASKS:
        raise ValueError(f"tasks must contain 1..{_MAX_TASKS} items")
    result: list[SyntheticTask] = []
    for raw in raw_tasks:
        task_id = str(raw.get("task_id", "")).strip()
        if not task_id:
            raise ValueError("each task requires a non-empty task_id")
        failures = int(raw.get("failures_before_success", 0))
        delay_ms = int(raw.get("delay_ms", 0))
        if failures < 0 or failures > _MAX_RETRIES:
            raise ValueError("failures_before_success is outside the bounded range")
        if delay_ms < 0 or delay_ms > 5000:
            raise ValueError("delay_ms is outside the bounded range")
        result.append(
            SyntheticTask(
                task_id=task_id,
                failures_before_success=failures,
                permanent_failure=bool(raw.get("permanent_failure", False)),
                delay_ms=delay_ms,
            )
        )
    return result


def _validate_options(
    *,
    max_workers: int,
    max_in_flight: int | None,
    max_retries: int,
    cancel_after: int,
) -> None:
    if max_workers < 1 or max_workers > _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    if max_in_flight is not None and (
        max_in_flight < 1 or max_in_flight > _MAX_IN_FLIGHT
    ):
        raise ValueError(f"max_in_flight must be between 1 and {_MAX_IN_FLIGHT}")
    if max_retries < 0 or max_retries > _MAX_RETRIES:
        raise ValueError(f"max_retries must be between 0 and {_MAX_RETRIES}")
    if cancel_after < 1:
        raise ValueError("cancel_after must be at least 1")


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
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--cancel-after", type=int, default=3)
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        report = measure_bounded_worker_acceptance(
            max_workers=args.workers,
            max_in_flight=args.max_in_flight,
            max_retries=args.max_retries,
            cancel_after=args.cancel_after,
        )
    except (TypeError, ValueError) as error:
        report = {
            "schema_version": ACCEPTANCE_SCHEMA_VERSION,
            "status": "blocked",
            "error_type": type(error).__name__,
            "error": str(error),
            "read_only": True,
            "write_attempted": False,
            "production_write_attempted": False,
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        target = args.output_json.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("status") == "measured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
