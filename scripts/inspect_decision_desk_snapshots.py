from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.paper_portfolio_time import taiwan_market_today
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect durable Daily Decision Desk snapshots.")
    parser.add_argument("--db-path")
    parser.add_argument("--decision-date")
    parser.add_argument("--latest-before-or-on")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json-output", action="store_true", help="Emit JSON summary. JSON is the default output.")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Any] = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    config = TWStockConfig(**kwargs)
    if args.db_path:
        config.db_file = Path(args.db_path)
    return config


def _row(snapshot: Any) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "decision_date": snapshot.decision_date,
        "as_of_date": snapshot.as_of_date,
        "quality": snapshot.data_quality,
        "status": snapshot.snapshot_status,
        "created_at": snapshot.created_at,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repository = DecisionDeskSnapshotRepository(_config_from_args(args), read_only=True)
    today = taiwan_market_today()
    if args.decision_date:
        snapshots = repository.find_by_decision_date(args.decision_date)
    else:
        snapshots = repository.list_snapshots(limit=args.limit)
    all_snapshots = repository.list_snapshots()
    future_dates = sorted(
        {
            snapshot.decision_date
            for snapshot in all_snapshots
            if snapshot.snapshot_status == "active" and _is_future_date(snapshot.decision_date, today)
        }
    )
    cutoff = args.latest_before_or_on or today.isoformat()
    if _is_future_date(cutoff, today):
        cutoff = today.isoformat()
    latest = next(
        (
            snapshot
            for snapshot in all_snapshots
            if snapshot.snapshot_status == "active"
            and snapshot.decision_date <= cutoff
        ),
        None,
    )
    summary = {
        "snapshots_count": len(all_snapshots),
        "latest_date_cutoff": cutoff,
        "future_decision_desk_snapshot_dates": future_dates,
        "latest_decision_date": latest.decision_date if latest is not None else None,
        "latest_snapshot_id": latest.snapshot_id if latest is not None else None,
        "snapshots": [_row(snapshot) for snapshot in snapshots[: args.limit]],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _is_future_date(value: str, today: date) -> bool:
    try:
        return date.fromisoformat(str(value)[:10]) > today
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
