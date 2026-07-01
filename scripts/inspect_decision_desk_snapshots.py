from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
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
        config.db_file.parent.mkdir(parents=True, exist_ok=True)
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
    repository = DecisionDeskSnapshotRepository(_config_from_args(args))
    if args.decision_date:
        snapshots = repository.find_by_decision_date(args.decision_date)
    else:
        snapshots = repository.list_snapshots(limit=args.limit)
    latest = repository.latest_before_or_on(args.latest_before_or_on) if args.latest_before_or_on else (snapshots[0] if snapshots else None)
    summary = {
        "snapshots_count": len(repository.list_snapshots()),
        "latest_decision_date": latest.decision_date if latest is not None else None,
        "latest_snapshot_id": latest.snapshot_id if latest is not None else None,
        "snapshots": [_row(snapshot) for snapshot in snapshots[: args.limit]],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
