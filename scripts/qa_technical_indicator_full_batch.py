"""唯讀量測技術指標全批次的 read／calculate／aggregate stages。

這個 probe 對呼叫端明確指定的原始股票 CSV 做一次記憶體內的批次模擬：讀取
整個 CSV、依股票代號分組、逐股呼叫 ``calculate_all_indicators``，最後只在記憶體
中 concat 結果。它不呼叫 ``calculate_and_store_indicators``，不建立備份、不寫
CSV／SQLite，也不啟用 process pool 或 thread；輸出只用來評估未來的 bounded
worker 與 single-writer 設計。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis_module.technical_analysis.technical_indicators import (  # noqa: E402
    TechnicalIndicatorCalculator,
)


FULL_BATCH_SCHEMA_VERSION = "technical-indicator-full-batch-latency.v1"
_STOCK_COLUMN_ALIASES = (
    "證券代號",
    "股票代號",
    "stock_code",
    "stock_id",
    "code",
    "ticker",
)
_SAFE_MAX_FAILED_STOCKS = 100


def measure_full_batch_latency(
    *,
    stock_data_file: Path,
    stock_ids: Sequence[str] | None = None,
    min_rows: int = 30,
    max_stocks: int | None = None,
    max_rows_per_stock: int | None = None,
    runs: int = 1,
) -> dict[str, Any]:
    """量測明確 CSV 的全批次記憶體流程，永遠不碰 writer。"""

    if min_rows < 1:
        raise ValueError("min_rows must be at least 1")
    if max_stocks is not None and max_stocks < 1:
        raise ValueError("max_stocks must be at least 1 when supplied")
    if max_rows_per_stock is not None and max_rows_per_stock < 1:
        raise ValueError("max_rows_per_stock must be at least 1 when supplied")
    if runs < 1:
        raise ValueError("runs must be at least 1")

    path = stock_data_file.expanduser().resolve()
    base: dict[str, Any] = {
        "schema_version": FULL_BATCH_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stock_data_file": str(path),
        "read_only": True,
        "write_attempted": False,
        "sqlite_write_attempted": False,
        "parallelism_enabled": False,
        "observed_worker_count": 1,
        "single_writer_required": True,
        "options": {
            "requested_stock_ids": list(stock_ids) if stock_ids is not None else None,
            "min_rows": min_rows,
            "max_stocks": max_stocks,
            "max_rows_per_stock": max_rows_per_stock,
            "runs": runs,
        },
    }
    if not path.is_file():
        return {
            **base,
            "status": "missing",
            "blocker": "stock_data_file_missing",
            "stages": {},
            "stocks": {},
            "rows": {},
            "next_safe_step": "提供明確且不在正式輸出目錄的 raw stock CSV，再重跑唯讀 probe。",
        }

    logger = logging.getLogger("qa_technical_indicator_full_batch")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    stages: dict[str, Any] = {}
    total_started = time.perf_counter()

    read_started = time.perf_counter()
    try:
        # 先以字串讀取，保留 `0050` 這類前導零代號；計算器自己的
        # preprocess 會在使用價格／成交量欄位前做數值正規化。
        frame = pd.read_csv(
            path,
            encoding="utf-8-sig",
            dtype=str,
            low_memory=False,
        )
    except Exception as error:  # pragma: no cover - defensive CLI boundary
        return {
            **base,
            "status": "invalid",
            "blocker": "stock_data_file_read_failed",
            "error_type": type(error).__name__,
            "error": str(error),
            "stages": {"read_ms": _elapsed_ms(read_started)},
            "stocks": {},
            "rows": {},
            "next_safe_step": "修正 raw stock CSV 欄位／編碼後再重跑，不要讓 probe 自動修補來源。",
        }
    stages["read_ms"] = _elapsed_ms(read_started)
    stages["input_columns"] = [str(column) for column in frame.columns]
    stages["input_file_size_bytes"] = path.stat().st_size

    stock_column = _find_stock_column(frame.columns)
    if stock_column is None:
        return {
            **base,
            "status": "blocked",
            "blocker": "stock_code_column_missing",
            "stages": stages,
            "stocks": {},
            "rows": {"input_rows": len(frame)},
            "next_safe_step": "提供含證券代號／股票代號或明確 stock_id 欄位的 CSV；不猜測欄位。",
        }

    normalize_started = time.perf_counter()
    normalized = frame.copy()
    normalized[stock_column] = normalized[stock_column].astype(str).str.strip()
    normalized = normalized[normalized[stock_column].ne("")].copy()
    stages["normalize_ms"] = _elapsed_ms(normalize_started)

    group_started = time.perf_counter()
    grouped = normalized.groupby(stock_column, sort=True)
    groups: dict[str, pd.DataFrame] = {
        str(stock_id): group.copy()
        for stock_id, group in grouped
    }
    stages["group_ms"] = _elapsed_ms(group_started)
    requested = _normalize_requested_stock_ids(stock_ids)
    if requested:
        selected_ids = [stock_id for stock_id in requested if stock_id in groups]
        missing_requested = [stock_id for stock_id in requested if stock_id not in groups]
    else:
        selected_ids = sorted(groups)
        missing_requested = []
    if max_stocks is not None:
        selected_ids = selected_ids[:max_stocks]

    calculator = TechnicalIndicatorCalculator(logger=logger)
    calculated_frames: list[pd.DataFrame] = []
    measured_ids: list[str] = []
    insufficient_ids: list[str] = []
    failed_ids: list[str] = []
    calculation_samples_ms: list[float] = []
    input_rows = 0
    calculated_rows = 0
    calculation_started = time.perf_counter()
    for stock_id in selected_ids:
        group = groups[stock_id]
        input_rows += len(group)
        if len(group) < min_rows:
            insufficient_ids.append(stock_id)
            continue
        if max_rows_per_stock is not None:
            group = group.tail(max_rows_per_stock).copy()
        last_result: pd.DataFrame | None = None
        stock_failed = False
        for _ in range(runs):
            started = time.perf_counter()
            try:
                result = calculator.calculate_all_indicators(group.copy(), stock_id)
                if result is None or not isinstance(result, pd.DataFrame):
                    raise ValueError("calculate_all_indicators returned no DataFrame")
            except Exception:
                stock_failed = True
                break
            calculation_samples_ms.append(_elapsed_ms(started))
            last_result = result
        if stock_failed or last_result is None:
            failed_ids.append(stock_id)
            continue
        measured_ids.append(stock_id)
        calculated_frames.append(last_result)
        calculated_rows += len(last_result)
    stages["calculate_ms"] = _elapsed_ms(calculation_started)

    aggregate_started = time.perf_counter()
    aggregate_rows = 0
    aggregate_columns: list[str] = []
    if calculated_frames:
        aggregate = pd.concat(calculated_frames, ignore_index=True)
        aggregate_rows = len(aggregate)
        aggregate_columns = [str(column) for column in aggregate.columns]
    stages["aggregate_ms"] = _elapsed_ms(aggregate_started)
    stages["total_ms"] = _elapsed_ms(total_started)

    selected_count = len(selected_ids)
    if not selected_count:
        status = "blocked"
        blocker = "no_matching_stock_groups"
    elif not measured_ids:
        status = "blocked"
        blocker = "no_stock_completed_calculation"
    elif failed_ids or insufficient_ids or missing_requested:
        status = "partial"
        blocker = "some_stock_groups_not_measured"
    else:
        status = "measured"
        blocker = None
    stocks = {
        "available_group_count": len(groups),
        "selected_group_count": selected_count,
        "measured_count": len(measured_ids),
        "insufficient_count": len(insufficient_ids),
        "failed_count": len(failed_ids),
        "measured_ids": measured_ids,
        "insufficient_ids": insufficient_ids[:_SAFE_MAX_FAILED_STOCKS],
        "failed_ids": failed_ids[:_SAFE_MAX_FAILED_STOCKS],
        "missing_requested_ids": missing_requested[:_SAFE_MAX_FAILED_STOCKS],
    }
    rows = {
        "raw_input_rows": len(frame),
        "normalized_input_rows": len(normalized),
        "selected_input_rows": input_rows,
        "calculated_rows": calculated_rows,
        "aggregate_rows": aggregate_rows,
        "aggregate_column_count": len(aggregate_columns),
        "aggregate_columns": aggregate_columns,
    }
    report: dict[str, Any] = {
        **base,
        "status": status,
        "blocker": blocker,
        "stock_code_column": stock_column,
        "stages": stages,
        "stocks": stocks,
        "rows": rows,
        "calculation": _summarize(calculation_samples_ms),
        "next_safe_step": (
            "另以明確 isolated staging 量測 CSV serialization 與 SQLite single-writer contention；"
            "在 bounded worker acceptance 前不要改 production worker 數。"
        ),
    }
    return report


def _find_stock_column(columns: Sequence[object]) -> str | None:
    names = {str(column): str(column) for column in columns}
    for alias in _STOCK_COLUMN_ALIASES:
        if alias in names:
            return names[alias]
    candidates = [name for name in names if "代號" in name]
    return candidates[0] if len(candidates) == 1 else None


def _normalize_requested_stock_ids(stock_ids: Sequence[str] | None) -> list[str]:
    if stock_ids is None:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in stock_ids:
        value = str(raw).strip()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _summarize(samples_ms: Sequence[float]) -> dict[str, int | float | None]:
    if not samples_ms:
        return {
            "sample_count": 0,
            "total_ms": 0.0,
            "mean_ms": None,
            "p95_ms": None,
            "min_ms": None,
            "max_ms": None,
        }
    ordered = sorted(float(value) for value in samples_ms)
    rank = max(1, (95 * len(ordered) + 99) // 100)
    return {
        "sample_count": len(ordered),
        "total_ms": round(sum(ordered), 3),
        "mean_ms": round(sum(ordered) / len(ordered), 3),
        "p95_ms": round(ordered[rank - 1], 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
    }


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
    parser.add_argument("--stocks", nargs="+", default=None)
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--max-stocks", type=int)
    parser.add_argument("--max-rows-per-stock", type=int)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        report = measure_full_batch_latency(
            stock_data_file=args.stock_data_file,
            stock_ids=args.stocks,
            min_rows=args.min_rows,
            max_stocks=args.max_stocks,
            max_rows_per_stock=args.max_rows_per_stock,
            runs=args.runs,
        )
    except (OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema_version": FULL_BATCH_SCHEMA_VERSION,
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "read_only": True,
                    "write_attempted": False,
                    "sqlite_write_attempted": False,
                    "parallelism_enabled": False,
                    "observed_worker_count": 1,
                    "single_writer_required": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output_json is not None:
        target = args.output_json.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] in {"measured", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
