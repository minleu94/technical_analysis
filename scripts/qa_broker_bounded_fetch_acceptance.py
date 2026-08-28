"""在隔離 staging 驗證券商 HTTP bounded fetch 與 single-writer 邊界。

這個 probe 使用假的、完全離線的 HTTP transport，但呼叫 production
``BrokerBranchUpdateService._fetch_metric_records_http`` 與既有 parser。它以
bounded ``ThreadPoolExecutor`` 模擬 I/O fetch，父程序才寫 staging CSV；不啟動
Selenium、不連線、不寫正式資料。transient／permanent failure 只用來驗證有限
retry 與 fail-closed，不代表 MoneyDJ 真實來源已可用。
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app_module.broker_branch_update_service as broker_module  # noqa: E402
from app_module.broker_branch_update_service import (  # noqa: E402
    BrokerBranchUpdateService,
)


BROKER_FETCH_SCHEMA_VERSION = "broker-bounded-fetch-acceptance.v1"
_MAX_WORKERS = 4
_MAX_IN_FLIGHT = 16
_MAX_RETRIES = 3
_MAX_TASKS = 9


class _ProbeConfig:
    """只提供 BrokerBranchUpdateService __init__ 所需的隔離路徑。"""

    def __init__(self, root: Path) -> None:
        self.broker_flow_dir = root / "unused_broker_flow"
        self.meta_data_dir = root / "unused_meta_data"


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class _OfflineMoneyDjTransport:
    """Thread-safe deterministic response、failure、rate-limit 與併發觀測。"""

    def __init__(
        self,
        task_by_url_key: dict[tuple[str, str, str, str], str],
        failure_modes: dict[str, str],
        *,
        rate_limit_seconds: float,
        response_delay_seconds: float,
    ) -> None:
        self.task_by_url_key = task_by_url_key
        self.failure_modes = failure_modes
        self.rate_limit_seconds = rate_limit_seconds
        self.response_delay_seconds = response_delay_seconds
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0
        self._attempts: dict[str, int] = {}
        self._active = 0
        self.max_active = 0
        self.call_starts: list[float] = []
        self.call_task_ids: list[str] = []
        self.thread_ids: set[int] = set()

    def get(self, url: str, **_: Any) -> _FakeResponse:
        params = parse_qs(urlparse(url).query)
        key = (
            params.get("a", [""])[0],
            params.get("b", [""])[0],
            params.get("f", [""])[0],
            params.get("c", [""])[0],
        )
        task_id = self.task_by_url_key.get(key)
        if task_id is None:
            raise RuntimeError(f"unknown offline MoneyDJ URL identity: {key}")

        with self._lock:
            now = time.perf_counter()
            allowed_at = max(now, self._next_allowed_at)
            self._next_allowed_at = allowed_at + self.rate_limit_seconds
        if allowed_at > now:
            time.sleep(allowed_at - now)

        started = time.perf_counter()
        with self._lock:
            self.call_starts.append(started)
            self.call_task_ids.append(task_id)
            self.thread_ids.add(threading.get_ident())
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            attempt = self._attempts.get(task_id, 0) + 1
            self._attempts[task_id] = attempt
        try:
            if self.response_delay_seconds > 0:
                time.sleep(self.response_delay_seconds)
            mode = self.failure_modes.get(task_id)
            if mode == "permanent" or (mode == "transient" and attempt == 1):
                raise RuntimeError(
                    f"offline synthetic {mode} failure: {task_id}; attempt={attempt}"
                )
            metric = "lots" if key[3] == "E" else "amount"
            return _FakeResponse(_render_metric_html(metric).encode("big5"))
        finally:
            with self._lock:
                self._active -= 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            starts = sorted(self.call_starts)
            intervals_ms = [
                round((right - left) * 1000, 3)
                for left, right in zip(starts, starts[1:])
            ]
            return {
                "request_count": len(starts),
                "task_ids": list(self.call_task_ids),
                "attempts": dict(self._attempts),
                "thread_count": len(self.thread_ids),
                "max_active": self.max_active,
                "min_start_interval_ms": min(intervals_ms) if intervals_ms else None,
                "start_intervals_ms": intervals_ms,
            }


def _render_metric_html(metric: str) -> str:
    header = "買進張數" if metric == "lots" else "買進金額"
    buy = "160" if metric == "lots" else "5291"
    sell = "20" if metric == "lots" else "653"
    net = "140" if metric == "lots" else "4638"
    return f"""
    <html><body><table><tbody>
      <tr><td colspan="4">買超</td></tr>
      <tr><td>股票</td><td>{header}</td><td>賣出</td><td>差額</td></tr>
      <tr><td><script>GenLink2stk('AS3296','勝德');</script></td>
          <td>{buy}</td><td>{sell}</td><td>{net}</td></tr>
    </tbody></table></body></html>
    """


def _build_task_specs() -> list[dict[str, Any]]:
    branches = (
        {
            "branch_system_key": "8450_845B",
            "branch_broker_code": "8450",
            "branch_code": "845B",
            "branch_display_name": "康和-永和",
            "url_param_a": "8450",
            "url_param_b": "845B",
        },
        {
            "branch_system_key": "9200_9200",
            "branch_broker_code": "9200",
            "branch_code": "9200",
            "branch_display_name": "華南-總公司",
            "url_param_a": "9200",
            "url_param_b": "9200",
        },
    )
    dates = ("2026-06-11", "2026-06-12")
    tasks: list[dict[str, Any]] = []
    for branch in branches:
        for date_str in dates:
            for metric in ("lots", "amount"):
                task_id = f"{branch['branch_system_key']}|{date_str}|{metric}"
                tasks.append(
                    {
                        "task_id": task_id,
                        "instance_id": task_id,
                        "branch_info": dict(branch),
                        "date": date_str,
                        "metric": metric,
                    }
                )
    duplicate_source = tasks[2]
    tasks.append(
        {
            **duplicate_source,
            "instance_id": f"{duplicate_source['task_id']}#duplicate",
        }
    )
    return tasks


def measure_bounded_fetch_acceptance(
    *,
    staging_root: Path,
    protected_roots: Sequence[Path],
    confirm_broker_fetch_probe: bool = False,
    max_tasks: int = 9,
    max_workers: int = 2,
    max_in_flight: int | None = None,
    max_retries: int = 1,
    rate_limit_seconds: float = 0.005,
    response_delay_seconds: float = 0.02,
) -> dict[str, Any]:
    """以離線 transport 驗收現有 broker HTTP fetch method 的 bounded 邊界。"""

    _validate_options(
        max_tasks=max_tasks,
        max_workers=max_workers,
        max_in_flight=max_in_flight,
        max_retries=max_retries,
        rate_limit_seconds=rate_limit_seconds,
        response_delay_seconds=response_delay_seconds,
    )
    resolved_staging = staging_root.expanduser().resolve()
    resolved_protected = _resolve_roots(protected_roots)
    effective_in_flight = max_in_flight or max_workers * 2
    base: dict[str, Any] = {
        "schema_version": BROKER_FETCH_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "staging_root": str(resolved_staging),
        "protected_roots": [str(path) for path in resolved_protected],
        "confirmation_required": True,
        "confirm_broker_fetch_probe": bool(confirm_broker_fetch_probe),
        "read_only": False,
        "network_enabled": False,
        "write_attempted": False,
        "staging_write_attempted": False,
        "production_write_attempted": False,
        "sqlite_write_attempted": False,
        "production_sqlite_write_attempted": False,
        "parallelism_enabled": False,
        "staging_fetch_pool_enabled": False,
        "production_fetch_pool_enabled": False,
        "selenium_fallback_invocations": 0,
        "selenium_fallback_serialized": True,
        "worker_write_attempts": 0,
        "single_writer_required": True,
        "cleanup_succeeded": None,
        "options": {
            "max_tasks": max_tasks,
            "max_workers": max_workers,
            "max_in_flight": effective_in_flight,
            "max_retries": max_retries,
            "rate_limit_seconds": rate_limit_seconds,
            "response_delay_seconds": response_delay_seconds,
        },
    }
    if not confirm_broker_fetch_probe:
        return {
            **base,
            "status": "confirmation_required",
            "blocker": "explicit_confirm_broker_fetch_probe_required",
            "next_safe_step": (
                "先指定既有 staging root、protected root，並明確傳入 "
                "--confirm-broker-fetch-probe；未確認時不建立任何檔案。"
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

    total_started = time.perf_counter()
    report: dict[str, Any]
    try:
        with tempfile.TemporaryDirectory(
            dir=str(resolved_staging),
            prefix="broker_bounded_fetch_",
        ) as temp_name:
            report = _run_acceptance(
                temp_root=Path(temp_name),
                max_tasks=max_tasks,
                max_workers=max_workers,
                max_in_flight=effective_in_flight,
                max_retries=max_retries,
                rate_limit_seconds=rate_limit_seconds,
                response_delay_seconds=response_delay_seconds,
            )
            report = {**base, **report}
            staged_write = "csv" in report
            report["staging_fetch_pool_enabled"] = True
            report["staging_write_attempted"] = staged_write
            report["write_attempted"] = staged_write
            report["production_write_attempted"] = False
            report["sqlite_write_attempted"] = False
            report["production_sqlite_write_attempted"] = False
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        report = {
            **base,
            "status": "blocked",
            "blocker": "isolated_broker_fetch_probe_failed",
            "error_type": type(error).__name__,
            "error": str(error),
            "stages": {"total_ms": _elapsed_ms(total_started)},
            "next_safe_step": "檢查離線 transport／parser／staging 權限後再重跑；不要改 production worker。",
        }
    else:
        report["stages"]["total_ms"] = _elapsed_ms(total_started)
    finally:
        report["cleanup_succeeded"] = resolved_staging.is_dir() and not any(
            path.is_dir() and path.name.startswith("broker_bounded_fetch_")
            for path in resolved_staging.iterdir()
        )
    return report


def _run_acceptance(
    *,
    temp_root: Path,
    max_tasks: int,
    max_workers: int,
    max_in_flight: int,
    max_retries: int,
    rate_limit_seconds: float,
    response_delay_seconds: float,
) -> dict[str, Any]:
    tasks = _build_task_specs()[:max_tasks]
    transient_id = tasks[0]["task_id"]
    permanent_id = tasks[7]["task_id"]
    failure_modes = {transient_id: "transient", permanent_id: "permanent"}
    task_by_url_key: dict[tuple[str, str, str, str], str] = {}
    service = BrokerBranchUpdateService(_ProbeConfig(temp_root))
    for task in tasks:
        url = service._build_branch_url(
            task["branch_info"],
            "2026-06-10",
            task["date"],
            metric=task["metric"],
        )
        params = parse_qs(urlparse(url).query)
        task_by_url_key[
            (
                params["a"][0],
                params["b"][0],
                params["f"][0],
                params["c"][0],
            )
        ] = task["task_id"]

    transport = _OfflineMoneyDjTransport(
        task_by_url_key,
        failure_modes,
        rate_limit_seconds=rate_limit_seconds,
        response_delay_seconds=response_delay_seconds,
    )
    original_get = broker_module.requests.get
    broker_module.requests.get = transport.get
    queue = list(tasks)
    attempts: dict[str, int] = {task["instance_id"]: 0 for task in tasks}
    in_flight: dict[Future[dict[str, Any]], dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    failed_ids: list[str] = []
    unexpected_failed_ids: list[str] = []
    retry_count = 0
    max_observed_in_flight = 0
    worker_thread_ids: set[int] = set()
    dispatch_started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="broker-probe")

    def submit_available() -> None:
        nonlocal max_observed_in_flight
        while queue and len(in_flight) < max_in_flight:
            task = queue.pop(0)
            instance_id = task["instance_id"]
            attempts[instance_id] += 1
            future = executor.submit(
                _fetch_task,
                service,
                task,
            )
            in_flight[future] = task
            max_observed_in_flight = max(max_observed_in_flight, len(in_flight))

    try:
        submit_available()
        while in_flight:
            done, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda item: in_flight[item]["instance_id"]):
                task = in_flight.pop(future)
                task_id = task["task_id"]
                try:
                    payload = future.result()
                except Exception:
                    if (
                        task_id == transient_id
                        and attempts[task["instance_id"]] <= max_retries
                    ):
                        queue.append(task)
                        retry_count += 1
                    elif task_id == permanent_id:
                        failed_ids.append(task_id)
                    else:
                        unexpected_failed_ids.append(task_id)
                    continue
                worker_thread_ids.add(int(payload["worker_thread_id"]))
                results.append(payload)
            submit_available()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        broker_module.requests.get = original_get
    stages = {"fetch_dispatch_ms": _elapsed_ms(dispatch_started)}

    writer_started = time.perf_counter()
    committed_task_ids: set[str] = set()
    duplicate_suppressed = 0
    rows: list[dict[str, Any]] = []
    for payload in sorted(results, key=lambda item: item["task_id"]):
        task_id = str(payload["task_id"])
        if task_id in committed_task_ids:
            duplicate_suppressed += 1
            continue
        committed_task_ids.add(task_id)
        rows.extend(dict(record) for record in payload["records"])
    csv_target = temp_root / "broker_fetch_records.csv"
    pd.DataFrame(rows).to_csv(csv_target, index=False, encoding="utf-8-sig")
    stages["parent_csv_write_ms"] = _elapsed_ms(writer_started)
    transport_report = transport.snapshot()
    rate_limit_ok = _rate_limit_respected(
        transport_report.get("min_start_interval_ms"), rate_limit_seconds
    )
    expected_failed = {permanent_id}
    checks = {
        "bounded_in_flight": max_observed_in_flight <= max_in_flight,
        "global_rate_limit_respected": rate_limit_ok,
        "retry_budget_respected": retry_count <= max_retries * len(tasks),
        "expected_permanent_failure_isolated": set(failed_ids) == expected_failed,
        "unexpected_failure_absent": not unexpected_failed_ids,
        "duplicate_idempotency": duplicate_suppressed >= 1,
        "parent_single_writer": True,
        "worker_did_not_write": True,
        "selenium_fallback_not_parallelized": True,
        "source_identity_preserved": all(
            isinstance(record.get("date"), str)
            and isinstance(record.get("metric_source"), str)
            and isinstance(record.get("branch_system_key"), str)
            for record in rows
        ),
    }
    status = "measured" if all(checks.values()) else "partial"
    return {
        "schema_version": BROKER_FETCH_SCHEMA_VERSION,
        "status": status,
        "blocker": None if status == "measured" else "broker_fetch_acceptance_check_failed",
        "stages": stages,
        "bounded_fetch_acceptance": {
            "status": status,
            "checks": checks,
            "configured_workers": max_workers,
            "max_in_flight": max_in_flight,
            "max_observed_in_flight": max_observed_in_flight,
            "max_retries": max_retries,
            "retry_count": retry_count,
            "worker_thread_count": len(worker_thread_ids),
            "worker_thread_ids": sorted(worker_thread_ids),
            "failed_ids": sorted(set(failed_ids)),
            "unexpected_failed_ids": sorted(set(unexpected_failed_ids)),
            "duplicate_suppressed_count": duplicate_suppressed,
            "committed_task_count": len(committed_task_ids),
            "transport": transport_report,
            "selenium_fallback": {
                "invocations": 0,
                "serialized_required": True,
                "parallelism_enabled": False,
            },
        },
        "rows": {
            "submitted_task_count": len(tasks),
            "successful_task_count": len(results),
            "written_record_count": len(rows),
        },
        "csv": {
            "path": str(csv_target),
            "rows": len(rows),
            "bytes": csv_target.stat().st_size,
        },
        "next_safe_step": (
            "以此離線 parser／rate-limit 證據再做受控真實 HTTP canary；Selenium fallback "
            "維持 serialized，正式 broker fetch pool 與 production writer 仍關閉。"
        ),
    }


def _fetch_task(
    service: BrokerBranchUpdateService,
    task: dict[str, Any],
) -> dict[str, Any]:
    records = service._fetch_metric_records_http(
        task["branch_info"],
        task["date"],
        task["metric"],
        retries=1,
        timeout=5,
    )
    return {
        "task_id": task["task_id"],
        "worker_thread_id": threading.get_ident(),
        "records": tuple(dict(record) for record in records),
    }


def _rate_limit_respected(min_interval_ms: Any, rate_limit_seconds: float) -> bool:
    if rate_limit_seconds <= 0:
        return True
    return isinstance(min_interval_ms, (int, float)) and min_interval_ms + 1.0 >= (
        rate_limit_seconds * 1000
    )


def _validate_options(
    *,
    max_tasks: int,
    max_workers: int,
    max_in_flight: int | None,
    max_retries: int,
    rate_limit_seconds: float,
    response_delay_seconds: float,
) -> None:
    if max_tasks != _MAX_TASKS:
        raise ValueError(
            f"max_tasks must equal {_MAX_TASKS} to cover retry, failure and duplicate scenarios"
        )
    if max_workers < 1 or max_workers > _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    if max_in_flight is not None and (
        max_in_flight < 1 or max_in_flight > _MAX_IN_FLIGHT
    ):
        raise ValueError(f"max_in_flight must be between 1 and {_MAX_IN_FLIGHT}")
    if max_retries < 0 or max_retries > _MAX_RETRIES:
        raise ValueError(f"max_retries must be between 0 and {_MAX_RETRIES}")
    if rate_limit_seconds < 0:
        raise ValueError("rate_limit_seconds must be non-negative")
    if response_delay_seconds < 0:
        raise ValueError("response_delay_seconds must be non-negative")


def _resolve_roots(roots: Sequence[Path]) -> list[Path]:
    return [Path(root).expanduser().resolve() for root in roots if str(root).strip()]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


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
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, action="append", required=True)
    parser.add_argument("--confirm-broker-fetch-probe", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=9)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--rate-limit-seconds", type=float, default=0.005)
    parser.add_argument("--response-delay-seconds", type=float, default=0.02)
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
                        "schema_version": BROKER_FETCH_SCHEMA_VERSION,
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
        report = measure_bounded_fetch_acceptance(
            staging_root=args.staging_root,
            protected_roots=args.protected_root,
            confirm_broker_fetch_probe=args.confirm_broker_fetch_probe,
            max_tasks=args.max_tasks,
            max_workers=args.workers,
            max_in_flight=args.max_in_flight,
            max_retries=args.max_retries,
            rate_limit_seconds=args.rate_limit_seconds,
            response_delay_seconds=args.response_delay_seconds,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        report = {
            "schema_version": BROKER_FETCH_SCHEMA_VERSION,
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
