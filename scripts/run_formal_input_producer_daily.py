"""執行一輪 bounded 日常 Rule／ledger／PIT input producer。

CLI 只使用當下的自然時間；不提供 ``--now`` 回填選項。來源會先做唯讀
preflight，candidate 輸出限定在呼叫端指定的 TEMP 目錄。呼叫端可另行提供
合法的 repository output／隔離 TEMP ``--publication-root``，以保存 Rule／
ledger 的 immutable manifest、PIT current-day archive 與 history handoff；
這些 publication 都不是正式 controlled input。PIT history handoff 另要求
獨立 denominator 與明確 coverage 起點，缺件會保留 candidate blocker。正式
controlled paths 只會由既有 consumer readback，不能由本入口 promotion 或改寫。
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_daily_input_producer import (  # noqa: E402
    DailyFormalInputPaths,
    run_daily_formal_input_producer,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


def _iso_date(value: str) -> date:
    """Parse a strict ISO natural date without allowing a clock override."""

    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必須是 YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("必須是 YYYY-MM-DD")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--development-output-root", type=Path, required=True)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--universe-symbols", type=Path, required=True)
    parser.add_argument("--owner-acceptance", type=Path, required=True)
    parser.add_argument("--formal-ledger-path", type=Path)
    parser.add_argument("--formal-rule-history-path", type=Path)
    parser.add_argument("--formal-sector-path", type=Path)
    parser.add_argument("--paper-snapshot-db", type=Path)
    parser.add_argument("--paper-trade-ledger-db", type=Path)
    parser.add_argument(
        "--publication-root",
        type=Path,
        help=(
            "可選的 repo output／隔離 TEMP 持久 publication root；"
            "與 candidate output 分離，按自然日與 source hash 建立 immutable run"
        ),
    )
    parser.add_argument(
        "--pit-expected-universe",
        type=Path,
        help=(
            "可選的獨立 PIT symbol denominator JSON；不得沿用由 PIT "
            "publication 自身推導的 source union"
        ),
    )
    parser.add_argument(
        "--pit-history-coverage-start",
        type=_iso_date,
        help="可選的 PIT 歷史 coverage 起點（YYYY-MM-DD，缺少時保持 blocked）",
    )
    args = parser.parse_args(argv)

    paths = DailyFormalInputPaths(
        output_root=args.output_root,
        development_output_root=args.development_output_root,
        market_db=args.market_db,
        clock_manifest=args.clock_manifest,
        universe_symbols=args.universe_symbols,
        owner_acceptance=args.owner_acceptance,
        formal_ledger_path=args.formal_ledger_path,
        formal_rule_history_path=args.formal_rule_history_path,
        formal_sector_path=args.formal_sector_path,
        paper_snapshot_db_path=args.paper_snapshot_db,
        paper_trade_ledger_db_path=args.paper_trade_ledger_db,
        publication_root=args.publication_root,
        pit_expected_universe_path=args.pit_expected_universe,
        pit_history_coverage_start=args.pit_history_coverage_start,
    )
    try:
        receipt = run_daily_formal_input_producer(paths)
    except Exception as error:  # noqa: BLE001 - CLI emits a bounded blocker
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "producer": "data_module.formal_daily_input_producer",
                    "reason": str(error),
                    "broker_order_allowed": False,
                    "writes_formal_controlled_paths": False,
                    "historical_backfill_claimed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt.get("status") in {
        "candidate_only",
        "formal_inputs_machine_verified",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
