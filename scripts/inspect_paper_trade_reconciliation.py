"""唯讀檢查外部 Paper fills CSV 與 snapshot 邊界的對帳結果。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_trade_reconciliation import (  # noqa: E402
    PaperTradeReconciliationService,
    render_markdown,
)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--ledger-db", type=Path)
    parser.add_argument("--portfolio-id", default="paper-main")
    parser.add_argument("--period-start")
    parser.add_argument("--period-end")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    result = PaperTradeReconciliationService(
        state_db_path=args.state_db,
        portfolio_id=args.portfolio_id,
        existing_ledger_db_path=args.ledger_db,
    ).inspect(
        args.input_csv,
        period_start=args.period_start,
        period_end=args.period_end,
    )
    payload: dict[str, Any] = result.to_dict()
    if args.format == "markdown":
        print(render_markdown(result), end="")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.status == "ready" else 2


def _configure_utf8_stdio() -> None:
    """讓 Windows CP1252 主控台也能顯示繁中 help／診斷。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
