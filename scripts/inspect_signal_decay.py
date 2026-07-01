from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.signal_decay_service import SignalDecayService
from data_module.config import TWStockConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect saved signal decay observations.")
    parser.add_argument("--observation-date")
    parser.add_argument("--db-path")
    parser.add_argument("--scope", choices=["event_type", "event_family", "strategy_version", "profile", "all"], default="all")
    parser.add_argument("--scope-id")
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Path] = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    config = TWStockConfig(**kwargs)
    config.use_sqlite = True
    if args.db_path:
        config.db_file = Path(args.db_path)
    return config


def run_inspect(args: argparse.Namespace) -> dict[str, Any]:
    service = SignalDecayService(_config(args))
    scope_type = None if args.scope == "all" else args.scope
    rows = service.list_decay_observations(
        observation_date=args.observation_date,
        signal_scope_type=scope_type,
        signal_scope_id=args.scope_id,
        limit=args.limit,
    )
    summary = service.summarize_decay(observation_date=args.observation_date)
    return {
        "observation_date": args.observation_date,
        "observations_count": len(rows),
        "summary": summary.to_dict(),
        "observations": [row.to_dict() for row in rows],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = run_inspect(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"observations_count: {payload['observations_count']}")
        print(f"warnings_count: {payload['summary']['warnings_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

