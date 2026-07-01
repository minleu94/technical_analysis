from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_event_repository import EvidenceEventRepository
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect evidence event store research records.")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--event-type", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--decision-date", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_kwargs = {}
    if args.data_root is not None:
        config_kwargs["data_root"] = args.data_root
    if args.output_root is not None:
        config_kwargs["output_root"] = args.output_root
    config = TWStockConfig(**config_kwargs)
    repo = EvidenceEventRepository(config)
    events = repo.list_events(
        symbol=args.symbol,
        event_type=args.event_type,
        decision_date=args.decision_date,
        start_date=args.start_date,
        end_date=args.end_date,
        limit=args.limit,
    )
    event_ids = {event.event_id for event in events}
    outcomes = [
        outcome
        for outcome in repo.list_outcomes()
        if outcome.event_id in event_ids
    ]
    payload = {
        "events_count": len(events),
        "outcomes_count": len(outcomes),
        "event_types": dict(Counter(event.event_type.value for event in events)),
        "outcome_statuses": dict(Counter(outcome.outcome_status.value for outcome in outcomes)),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
