"""建立一次 Paper-derived、research-only 的每日 position-health baseline。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from datetime import timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.position_health_daily_refresh_service import (  # noqa: E402
    PositionHealthDailyRefreshService,
)
from app_module.paper_position_identity_provider import PaperPositionIdentityProvider  # noqa: E402
from scripts.scheduled.scheduled_clock import scheduled_now  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a fresh Paper-derived, fail-closed position-health baseline."
    )
    parser.add_argument("--state-db", required=True, help="repository Paper snapshot SQLite")
    parser.add_argument("--status-path", required=True, help="repository Paper daily status JSON")
    parser.add_argument("--output-dir", required=True, help="derived position-health output directory")
    parser.add_argument(
        "--previous-baseline",
        help="optional prior baseline whose human-entered fields may be preserved",
    )
    parser.add_argument(
        "--ledger-db",
        help="optional Paper trade ledger SQLite used to prove cross-date continuity",
    )
    parser.add_argument(
        "--derive-position-identities",
        action="store_true",
        help="derive stable IDs only from verified Paper flat-to-positive entry events",
    )
    parser.add_argument("--portfolio-id", default="paper-main")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = scheduled_now()
    observed_at = now.astimezone(timezone.utc)
    output_dir = Path(args.output_dir).expanduser().resolve()
    previous = (
        Path(args.previous_baseline).expanduser().resolve()
        if args.previous_baseline
        else output_dir / "latest.json"
    )
    identity_provider = (
        PaperPositionIdentityProvider(
            state_db_path=args.state_db,
            ledger_db_path=args.ledger_db
            or str(Path(args.state_db).expanduser().resolve().parent.parent / "paper_trade_ledger.sqlite"),
            coverage_status_path=args.status_path,
            portfolio_id=args.portfolio_id,
        )
        if args.derive_position_identities
        else None
    )
    receipt = PositionHealthDailyRefreshService(
        state_db_path=args.state_db,
        status_path=args.status_path,
        ledger_db_path=args.ledger_db,
        portfolio_id=args.portfolio_id,
        position_identity_provider=identity_provider,
    ).refresh(
        as_of_date=now.date(),
        output_dir=output_dir,
        previous_baseline_path=previous,
        observed_at=observed_at,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if receipt.get("status") in {"passed", "reused"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
