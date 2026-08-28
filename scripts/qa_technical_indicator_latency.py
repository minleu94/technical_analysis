"""唯讀量測逐股技術指標計算 latency，並固定 future worker 的安全邊界。

這個 probe 只讀取呼叫端明確指定的 ``*_indicators.csv``，以記憶體中的尾端
資料執行 ``calculate_all_indicators``；不呼叫 ``calculate_and_store_indicators``，
不建立備份、不寫 CSV／SQLite，也不會改變目前的單執行緒更新行為。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sys
import time
from typing import Any, Sequence

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis_module.technical_analysis.technical_indicators import (  # noqa: E402
    TechnicalIndicatorCalculator,
)


_SAFE_STOCK_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue


def _summarize(samples_ms: Sequence[float]) -> dict[str, int | float | None]:
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
        p95 = minimum = maximum = None
    else:
        rank = max(1, (95 * len(warm) + 99) // 100)
        p95 = warm[rank - 1]
        minimum = warm[0]
        maximum = warm[-1]
    return {
        "sample_count": len(samples),
        "cold_ms": samples[0],
        "warm_sample_count": len(warm),
        "warm_p95_ms": p95,
        "warm_min_ms": minimum,
        "warm_max_ms": maximum,
    }


def _stock_file(technical_dir: Path, stock_id: str) -> Path:
    if not _SAFE_STOCK_ID.fullmatch(stock_id):
        raise ValueError(f"invalid stock id for read-only probe: {stock_id!r}")
    candidate = (technical_dir / f"{stock_id}_indicators.csv").resolve()
    if not candidate.is_relative_to(technical_dir.resolve()):
        raise ValueError("technical indicator path escapes the explicit directory")
    return candidate


def measure_technical_indicator_latency(
    *,
    technical_dir: Path,
    stock_ids: Sequence[str],
    rows: int = 500,
    runs: int = 3,
) -> dict[str, Any]:
    """量測明確檔案的 CSV read 與 indicator calculation stages。"""

    resolved_dir = technical_dir.expanduser().resolve()
    if rows < 1:
        raise ValueError("rows must be at least 1")
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if not resolved_dir.is_dir():
        return {
            "status": "missing",
            "technical_dir": str(resolved_dir),
            "items": [],
            "read_only": True,
            "write_attempted": False,
            "parallelism_enabled": False,
            "observed_worker_count": 1,
            "single_writer_required": True,
            "blocker": "technical_indicator_directory_missing",
        }

    logger = logging.getLogger("qa_technical_indicator_latency")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    calculator: TechnicalIndicatorCalculator | None = None
    items: list[dict[str, Any]] = []
    for raw_stock_id in stock_ids:
        stock_id = str(raw_stock_id).strip()
        item: dict[str, Any] = {
            "stock_id": stock_id,
            "status": "blocked",
            "read_only": True,
            "write_attempted": False,
        }
        try:
            path = _stock_file(resolved_dir, stock_id)
        except ValueError as error:
            item["reason"] = str(error)
            items.append(item)
            continue
        item["path"] = str(path)
        if not path.is_file():
            item["status"] = "missing"
            item["reason"] = "indicator_file_missing"
            items.append(item)
            continue

        started = time.perf_counter()
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig").tail(rows)
        except Exception as error:
            item["status"] = "invalid"
            item["reason"] = "indicator_file_read_failed"
            item["error_type"] = type(error).__name__
            items.append(item)
            continue
        item["csv_read_ms"] = round((time.perf_counter() - started) * 1000, 3)
        item["input_rows"] = len(frame)
        if calculator is None:
            calculator = TechnicalIndicatorCalculator(logger=logger)
        calculation_samples: list[float] = []
        output_rows: int | None = None
        calculation_error: Exception | None = None
        for _ in range(runs):
            started = time.perf_counter()
            try:
                result = calculator.calculate_all_indicators(
                    frame.copy(),
                    stock_id,
                )
                if result is None:
                    raise ValueError("calculate_all_indicators returned None")
                output_rows = len(result)
            except Exception as error:  # pragma: no cover - defensive boundary
                calculation_error = error
                break
            calculation_samples.append((time.perf_counter() - started) * 1000)
        if calculation_error is not None:
            item["status"] = "invalid"
            item["reason"] = "indicator_calculation_failed"
            item["error_type"] = type(calculation_error).__name__
            items.append(item)
            continue
        item.update(
            {
                "status": "measured",
                "output_rows": output_rows,
                "calculation": _summarize(calculation_samples),
            }
        )
        items.append(item)

    measured = [item for item in items if item["status"] == "measured"]
    return {
        "status": "measured" if measured else "blocked",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "technical_dir": str(resolved_dir),
        "requested_stock_ids": list(stock_ids),
        "tail_rows": rows,
        "runs": runs,
        "items": items,
        "read_only": True,
        "write_attempted": False,
        "parallelism_enabled": False,
        "observed_worker_count": 1,
        "single_writer_required": True,
        "next_safe_step": (
            "measure full-batch CPU, CSV write and SQLite contention before any "
            "bounded worker change"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--technical-dir", type=Path, required=True)
    parser.add_argument(
        "--stocks",
        nargs="+",
        default=("0050", "2330", "3008"),
    )
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    try:
        report = measure_technical_indicator_latency(
            technical_dir=args.technical_dir,
            stock_ids=args.stocks,
            rows=args.rows,
            runs=args.runs,
        )
    except Exception as error:  # pragma: no cover - CLI fail-closed boundary
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "read_only": True,
                    "write_attempted": False,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
