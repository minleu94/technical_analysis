"""Run the bounded, research-only exit effectiveness evidence producer."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.exit_effectiveness_producer import (  # noqa: E402
    DEFAULT_EXIT_HORIZON_TRADING_DAYS,
    produce_exit_effectiveness,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transition-db", type=Path, required=True)
    parser.add_argument("--paper-ledger-db", type=Path, required=True)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--calendar-cache", type=Path)
    parser.add_argument("--temporary-closure-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--horizon-trading-days",
        type=int,
        default=DEFAULT_EXIT_HORIZON_TRADING_DAYS,
        help="versioned research horizon; default is five official trading days",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = produce_exit_effectiveness(
        transition_db=args.transition_db,
        paper_ledger_db=args.paper_ledger_db,
        market_db=args.market_db,
        output=args.output,
        calendar_cache=args.calendar_cache,
        temporary_closure_cache=args.temporary_closure_cache,
        horizon_trading_days=args.horizon_trading_days,
        now=datetime.now(timezone.utc),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 2 if result.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
