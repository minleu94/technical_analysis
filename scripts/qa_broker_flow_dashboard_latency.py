"""Broker Flow dashboard 的唯讀 latency 與資料形狀量測工具。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
    from app_module.broker_flow_service import BrokerFlowService
    from data_module.config import TWStockConfig

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--include-legacy", action="store_true")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    config = TWStockConfig()
    db_path = args.db_path or config.db_file
    report: dict[str, object] = {
        "sqlite_shape": inspect_broker_flow_sqlite(db_path),
        "legacy_pipeline": {"status": "not_requested"},
    }

    if args.include_legacy:
        service = BrokerFlowService(config)
        tracemalloc.start()
        started = time.perf_counter()
        events = service.get_events(force_reload=True)
        csv_load_ms = (time.perf_counter() - started) * 1000
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        started = time.perf_counter()
        signals = service.get_stock_flow_signals(period="week")
        scanner_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        service.get_market_flow_summary(signals=signals, period="week")
        summary_ms = (time.perf_counter() - started) * 1000
        report["legacy_pipeline"] = {
            "status": "measured",
            "event_count": len(events),
            "signal_count": len(signals),
            "csv_load_ms": round(csv_load_ms, 3),
            "scanner_ms": round(scanner_ms, 3),
            "summary_ms": round(summary_ms, 3),
            "peak_mib": round(peak_bytes / (1024 * 1024), 3),
        }

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
