"""Broker Flow dashboard 的唯讀 latency 與資料形狀量測工具。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import tracemalloc
from pathlib import Path
from datetime import datetime
from typing import Any, Callable, Sequence, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _emit_report(rendered: str, output_json: Path | None) -> None:
    _configure_utf8_stdio()
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def summarize_latency_samples(samples_ms: Sequence[float]) -> dict[str, int | float | None]:
    samples = [float(value) for value in samples_ms]
    if not samples:
        return {
            "sample_count": 0,
            "cold_ms": None,
            "warm_sample_count": 0,
            "warm_p95_ms": None,
            "warm_min_ms": None,
            "warm_max_ms": None,
        }

    warm = sorted(samples[1:])
    if not warm:
        warm_p95 = warm_min = warm_max = None
    else:
        rank = max(1, (95 * len(warm) + 99) // 100)
        warm_p95 = warm[rank - 1]
        warm_min = warm[0]
        warm_max = warm[-1]
    return {
        "sample_count": len(samples),
        "cold_ms": samples[0],
        "warm_sample_count": len(warm),
        "warm_p95_ms": warm_p95,
        "warm_min_ms": warm_min,
        "warm_max_ms": warm_max,
    }


def benchmark_operation(
    name: str,
    operation: Callable[[], object],
    *,
    runs: int = 20,
) -> dict[str, Any]:
    """執行一次 warm-up 與固定次數量測，保留原始樣本。"""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    started = time.perf_counter()
    last_result = operation()
    warmup_ms = (time.perf_counter() - started) * 1000
    samples: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        last_result = operation()
        samples.append((time.perf_counter() - started) * 1000)
    summary = summarize_latency_samples((warmup_ms, *samples))
    return {
        "name": name,
        "warmup_ms": round(warmup_ms, 3),
        "raw_samples_ms": [round(value, 3) for value in samples],
        "summary": summary,
        "last_result": last_result,
    }


def evaluate_latency_gate(
    summary: dict[str, object],
    *,
    warm_limit_ms: float,
    cold_limit_ms: float | None = None,
) -> dict[str, object]:
    warm_p95 = summary.get("warm_p95_ms")
    cold_ms = summary.get("cold_ms")
    passed = isinstance(warm_p95, (int, float)) and warm_p95 < warm_limit_ms
    if cold_limit_ms is not None:
        passed = passed and isinstance(cold_ms, (int, float)) and cold_ms < cold_limit_ms
    return {
        "status": "pass" if passed else "fail",
        "warm_limit_ms": warm_limit_ms,
        "warm_p95_ms": warm_p95,
        "cold_limit_ms": cold_limit_ms,
        "cold_ms": cold_ms,
    }


def capture_file_integrity(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = resolved.stat()
    return {
        "sha256": digest.hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def measure_ui_responsiveness() -> dict[str, object]:
    """以明確慢 worker 驗證 refresh 立即返回且 Qt heartbeat 可執行。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ui_qt.views.smart_money.smart_money_flow_view import SmartMoneyFlowView

    class SlowDashboardService:
        def load_dashboard_snapshot(self, query):
            time.sleep(0.5)
            return None

    app = QApplication.instance() or QApplication([])
    view = SmartMoneyFlowView(cast(Any, SlowDashboardService()))
    heartbeat_at: list[float] = []
    started = time.perf_counter()
    QTimer.singleShot(0, lambda: heartbeat_at.append(time.perf_counter()))
    view._refresh_data()
    loading_state_ms = (time.perf_counter() - started) * 1000
    deadline = started + 0.3
    while not heartbeat_at and time.perf_counter() < deadline:
        app.processEvents()
    heartbeat_ms = (
        (heartbeat_at[0] - started) * 1000 if heartbeat_at else None
    )
    workers = tuple(view._workers.values())
    view.close()
    for worker in workers:
        worker.wait()
    return {
        "loading_state_ms": round(loading_state_ms, 3),
        "heartbeat_ms": round(heartbeat_ms, 3) if heartbeat_ms is not None else None,
        "loading_label": view.load_status_label.text(),
        "status": (
            "pass"
            if loading_state_ms < 300
            and heartbeat_ms is not None
            and heartbeat_ms < 300
            else "fail"
        ),
        "limit_ms": 300.0,
    }


def inspect_broker_flow_sqlite(db_path: Path) -> dict[str, object]:
    resolved = Path(db_path).expanduser().resolve()
    if not resolved.is_file():
        return {
            "quality": "missing",
            "db_path": str(resolved),
            "row_count": 0,
            "warnings": ("broker_flow_sqlite_missing",),
        }

    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        columns = connection.execute("PRAGMA table_info(broker_flows)").fetchall()
        if not columns:
            return {
                "quality": "missing",
                "db_path": str(resolved),
                "row_count": 0,
                "warnings": ("broker_flows_table_missing",),
            }
        names = [str(row[1]) for row in columns]
        quoted = ['"' + name.replace('"', '""') + '"' for name in names]
        date_column, branch_column, stock_column = quoted[:3]
        started = time.perf_counter()
        values = connection.execute(
            "SELECT COUNT(*), MIN({date}), MAX({date}), "
            "COUNT(DISTINCT {date}), COUNT(DISTINCT {branch}), "
            "COUNT(DISTINCT {stock}) FROM broker_flows".format(
                date=date_column,
                branch=branch_column,
                stock=stock_column,
            )
        ).fetchone()
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert values is not None
        return {
            "quality": "observed",
            "db_path": str(resolved),
            "row_count": int(values[0]),
            "min_date": values[1],
            "max_date": values[2],
            "trading_date_count": int(values[3]),
            "branch_count": int(values[4]),
            "stock_count": int(values[5]),
            "shape_query_ms": round(elapsed_ms, 3),
            "warnings": (),
        }
    finally:
        connection.close()


def main() -> int:
    from app_module.broker_flow_dashboard_dtos import (
        BrokerFlowDashboardQuery,
        BrokerFlowDashboardSnapshot,
    )
    from app_module.broker_flow_dashboard_query_service import BrokerFlowDashboardQueryService
    from app_module.broker_flow_service import BrokerFlowService
    from data_module.config import TWStockConfig

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--include-legacy", action="store_true")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--period", choices=("week", "month", "all"), default="all")
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()

    config = TWStockConfig()
    db_path = args.db_path or config.db_file
    sqlite_shape = inspect_broker_flow_sqlite(db_path)
    report: dict[str, object] = {
        "sqlite_shape": sqlite_shape,
        "legacy_pipeline": {"status": "not_requested"},
    }

    if sqlite_shape["quality"] == "observed":
        before = capture_file_integrity(db_path)
        service = BrokerFlowService(config)
        source_only_service = BrokerFlowDashboardQueryService(
            service.dashboard_query_service.repository
        )
        raw_as_of = str(sqlite_shape["max_date"])
        as_of_date = datetime.strptime(raw_as_of.replace("-", ""), "%Y%m%d").date()
        periods = ("week", "month") if args.period == "all" else (args.period,)
        benchmarks: dict[str, Any] = {}
        seed_snapshots: dict[str, BrokerFlowDashboardSnapshot] = {}
        for period in periods:
            query = BrokerFlowDashboardQuery(
                period=period,
                scope="top_bottom_50",
                requested_as_of_date=as_of_date,
                limit_per_side=50,
            )

            def load_dashboard(query=query):
                snapshot = service.load_dashboard_snapshot(query)
                seed_snapshots[query.period] = snapshot
                return {
                    "as_of_date": snapshot.as_of_date.isoformat(),
                    "signal_count": len(snapshot.top_signals) + len(snapshot.bottom_signals),
                    "semantic_count": len(snapshot.semantics_by_code),
                    "query_counts": dict(snapshot.query_counts),
                    "sqlite_statement_count": (
                        int(snapshot.query_counts.get("repository", 0)) + 3
                    ),
                    "quality": snapshot.quality,
                    "warning_count": len(snapshot.warnings),
                }

            dashboard = benchmark_operation(
                f"dashboard_{period}", load_dashboard, runs=args.runs
            )
            warm_limit = 2000.0 if period == "week" else 3000.0
            dashboard["gate"] = evaluate_latency_gate(
                dashboard["summary"],
                warm_limit_ms=warm_limit,
                cold_limit_ms=5000.0,
            )
            benchmarks[f"dashboard_{period}"] = dashboard

            def load_dashboard_without_semantics(query=query):
                snapshot = source_only_service.load_dashboard_snapshot(query)
                return {
                    "signal_count": len(snapshot.top_signals) + len(snapshot.bottom_signals),
                    "query_counts": dict(snapshot.query_counts),
                    "sqlite_statement_count": int(
                        snapshot.query_counts.get("repository", 0)
                    ),
                }

            source_only = benchmark_operation(
                f"dashboard_without_semantics_{period}",
                load_dashboard_without_semantics,
                runs=args.runs,
            )
            source_only["diagnostic_only"] = True
            benchmarks[f"dashboard_without_semantics_{period}"] = source_only
            dashboard["semantic_overhead_p95_ms"] = round(
                float(dashboard["summary"]["warm_p95_ms"])
                - float(source_only["summary"]["warm_p95_ms"]),
                3,
            )

        seed = seed_snapshots.get("week") or next(iter(seed_snapshots.values()))
        selected_signals = (*seed.top_signals, *seed.bottom_signals)
        if selected_signals:
            stock_code = selected_signals[0].stock_code

            def load_detail():
                snapshot = service.load_stock_branch_detail(
                    stock_code, "week", as_of_date
                )
                return {
                    "stock_code": stock_code,
                    "row_count": len(snapshot.rows),
                    "query_count": snapshot.query_count,
                    "quality": snapshot.quality,
                }

            detail = benchmark_operation("stock_branch_detail", load_detail, runs=args.runs)
            detail["gate"] = evaluate_latency_gate(
                detail["summary"], warm_limit_ms=500.0
            )
            benchmarks["stock_branch_detail"] = detail
        else:
            benchmarks["stock_branch_detail"] = {
                "status": "blocked",
                "blocker": "dashboard_returned_no_signals",
            }

        if seed.tracked_branches:
            branch_key = seed.tracked_branches[0][0]

            def load_branch():
                snapshot = service.load_branch_tracker(
                    branch_key, "week", as_of_date
                )
                return {
                    "branch_system_key": branch_key,
                    "row_count": len(snapshot.rows),
                    "query_count": snapshot.query_count,
                    "quality": snapshot.quality,
                }

            branch = benchmark_operation("branch_tracker", load_branch, runs=args.runs)
            branch["gate"] = evaluate_latency_gate(
                branch["summary"], warm_limit_ms=1000.0
            )
            benchmarks["branch_tracker"] = branch
        else:
            benchmarks["branch_tracker"] = {
                "status": "blocked",
                "blocker": "dashboard_returned_no_tracked_branches",
            }

        after = capture_file_integrity(db_path)
        report["production_benchmarks"] = benchmarks
        report["ui_responsiveness"] = measure_ui_responsiveness()
        report["database_integrity"] = {
            "before": before,
            "after": after,
            "unchanged": before == after,
        }
    else:
        report["production_benchmarks"] = {
            "status": "blocked",
            "blocker": "production_broker_flow_sqlite_unavailable",
        }
        report["ui_responsiveness"] = {"status": "not_run"}

    if args.include_legacy:
        service = BrokerFlowService(config)
        tracemalloc.start()
        started = time.perf_counter()
        events = service.get_events(force_reload=True)
        csv_load_ms = (time.perf_counter() - started) * 1000
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        started = time.perf_counter()
        legacy_signals = service.get_stock_flow_signals(period="week")
        scanner_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        service.get_market_flow_summary(signals=legacy_signals, period="week")
        summary_ms = (time.perf_counter() - started) * 1000
        report["legacy_pipeline"] = {
            "status": "measured",
            "event_count": len(events),
            "signal_count": len(legacy_signals),
            "csv_load_ms": round(csv_load_ms, 3),
            "scanner_ms": round(scanner_ms, 3),
            "summary_ms": round(summary_ms, 3),
            "peak_mib": round(peak_bytes / (1024 * 1024), 3),
        }

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    _emit_report(rendered, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
