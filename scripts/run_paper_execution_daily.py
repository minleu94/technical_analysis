"""建立 T+1 next-session-open research-only Paper execution candidate。

這個排程入口接受前一自然日已凍結的 recommendation，或由
``--recommendation-root`` 從 queue 依下一官方 session 選取，並讀取唯讀 Paper
snapshot 與官方下一 session 開盤行情，所有時間由主機 clock 取得。預設只輸出
TEMP candidate；只有同時提供 ``--ledger-db`` 並明確指定
``--confirm-append-paper-ledger`` 才會呼叫 append-only Paper fill writer。
``--receipt-root`` 可保存 queue attempt 的 processed／waiting／failed receipt。
工具不寫正式行情／Formal DB，不連 broker，不重訓，也不把 snapshot 反推成成交。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.paper_daily_execution_producer import (  # noqa: E402
    PaperExecutionPaths,
    persist_operational_receipt,
    run_paper_execution_daily_from_queue,
    run_paper_execution_daily,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--recommendation-json", type=Path)
    source_group.add_argument(
        "--recommendation-root",
        type=Path,
        help="從持久 recommendation queue 依下一官方 session 選取待執行決策",
    )
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ledger-db", type=Path)
    parser.add_argument("--clock-manifest", type=Path)
    parser.add_argument(
        "--receipt-root",
        type=Path,
        help="保存 operational processed／waiting／failed receipt 的目錄",
    )
    parser.add_argument(
        "--confirm-append-paper-ledger",
        action="store_true",
        help="明確要求寫入指定 append-only Paper fill ledger；省略時只預覽",
    )
    args = parser.parse_args(argv)
    if args.confirm_append_paper_ledger and args.ledger_db is None:
        parser.error("--confirm-append-paper-ledger requires --ledger-db")
    paths = PaperExecutionPaths(
        recommendation_json=(
            args.recommendation_json
            if args.recommendation_json is not None
            else args.recommendation_root / "__queue_selection__.json"
        ),
        state_db=args.state_db,
        market_db=args.market_db,
        output_root=args.output_root,
        ledger_db=args.ledger_db,
        clock_manifest=args.clock_manifest,
    )
    if args.recommendation_root is not None:
        result = run_paper_execution_daily_from_queue(
            paths,
            recommendation_root=args.recommendation_root,
            receipt_root=args.receipt_root,
            confirm_append=args.confirm_append_paper_ledger,
        )
    else:
        result = run_paper_execution_daily(
            paths,
            confirm_append=args.confirm_append_paper_ledger,
        )
        if args.receipt_root is not None:
            result = persist_operational_receipt(result, args.receipt_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {
        "machine_verified_candidate",
        "no_trade_required_candidate",
        "skipped_non_trading_day",
        "skipped_no_pending_recommendation",
        "waiting_for_execution_session",
        "waiting_for_execution_source",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
