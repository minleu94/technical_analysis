"""受控建立 Paper Portfolio 的 frozen-constituent Equal Weight benchmark。

預設只讀取 baseline、既有 paper snapshot 與正式行情 SQLite，建立 deterministic
preview；只有傳入 ``--confirm-build-paper-benchmark`` 才會在指定 output path
寫入新的 append-only benchmark ledger。這個入口不改市場 DB、不改 Portfolio
snapshot、不呼叫 broker，也不把手動交易當成 benchmark 成交證據。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_equal_weight_benchmark_builder import (  # noqa: E402
    PaperEqualWeightBenchmarkBuilder,
    PaperEqualWeightBenchmarkPreview,
)
from app_module.paper_equal_weight_benchmark_ledger import EqualWeightBenchmarkEntry  # noqa: E402
from app_module.paper_portfolio_time import paper_portfolio_today  # noqa: E402


SCHEMA_VERSION = "paper-equal-weight-benchmark-build.v1"
PORTFOLIO_ID = "paper-main"
BENCHMARK_ID = "paper-main-equal"


def _build_entries(
    *,
    baseline_path: Path,
    state_db: Path,
    market_db: Path,
    portfolio_id: str,
    benchmark_id: str,
) -> tuple[EqualWeightBenchmarkEntry, ...]:
    """保留舊 CLI helper，讓既有腳本／測試仍可注入交易日 clock。"""
    builder = PaperEqualWeightBenchmarkBuilder(
        portfolio_id=portfolio_id,
        benchmark_id=benchmark_id,
        today_provider=paper_portfolio_today,
    )
    return builder.build_entries(
        baseline_path=baseline_path,
        state_db_path=state_db,
        market_db_path=market_db,
    )


def _preview_payload(
    *,
    baseline_path: Path,
    state_db: Path,
    market_db: Path,
    output_ledger: Path,
    entries: tuple[EqualWeightBenchmarkEntry, ...],
    portfolio_id: str,
    benchmark_id: str,
) -> dict[str, object]:
    preview = PaperEqualWeightBenchmarkPreview(
        baseline_path=baseline_path.resolve(),
        state_db_path=state_db.resolve(),
        market_db_path=market_db.resolve(),
        output_ledger_path=output_ledger.resolve(),
        portfolio_id=portfolio_id,
        benchmark_id=benchmark_id,
        entries=entries,
    )
    return preview.to_dict()


def _write_new_ledger(path: Path, entries: tuple[EqualWeightBenchmarkEntry, ...]) -> None:
    PaperEqualWeightBenchmarkBuilder.write_new_ledger(path, entries)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--output-ledger", type=Path, required=True)
    parser.add_argument("--portfolio-id", default=PORTFOLIO_ID)
    parser.add_argument("--benchmark-id", default=BENCHMARK_ID)
    parser.add_argument("--confirm-build-paper-benchmark", action="store_true")
    args = parser.parse_args(argv)

    try:
        entries = _build_entries(
            baseline_path=args.baseline,
            state_db=args.state_db,
            market_db=args.market_db,
            portfolio_id=str(args.portfolio_id),
            benchmark_id=str(args.benchmark_id),
        )
        payload = _preview_payload(
            baseline_path=args.baseline,
            state_db=args.state_db,
            market_db=args.market_db,
            output_ledger=args.output_ledger,
            entries=entries,
            portfolio_id=str(args.portfolio_id),
            benchmark_id=str(args.benchmark_id),
        )
        if args.confirm_build_paper_benchmark:
            # Rebuild through the service so a preview cannot silently become
            # stale while the user is deciding whether to confirm.
            builder = PaperEqualWeightBenchmarkBuilder(
                portfolio_id=str(args.portfolio_id),
                benchmark_id=str(args.benchmark_id),
                today_provider=paper_portfolio_today,
            )
            preview = builder.preview(
                baseline_path=args.baseline,
                state_db_path=args.state_db,
                market_db_path=args.market_db,
                output_ledger_path=args.output_ledger,
            )
            builder.commit(preview, confirm=True)
            payload = preview.to_dict(status="built", write_performed=True)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "rejected",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "research_only": True,
                    "writes_market_db": False,
                    "broker_order_allowed": False,
                    "auto_rebalance_allowed": False,
                    "write_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


def _configure_utf8_stdio() -> None:
    """讓直接執行腳本的 Windows 主控台也能顯示繁中說明與診斷。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # 測試 capture stream 或外部 host 管理的 stream 可能禁止重設；
            # 這不應改變 benchmark readiness 結果。
            continue


if __name__ == "__main__":
    raise SystemExit(main())
