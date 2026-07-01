from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.live_research_gap_service import LiveResearchGapService, is_production_like_db
from data_module.config import TWStockConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture read-only live vs research gap observations.")
    parser.add_argument("--observation-date", required=True)
    parser.add_argument("--db-path")
    parser.add_argument("--portfolio-id", default="default")
    parser.add_argument("--symbol")
    parser.add_argument("--strategy-version-id")
    parser.add_argument("--source-type")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--allow-production-db-confirm", action="store_true")
    parser.add_argument("--json-output", action="store_true")
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


def run_capture(args: argparse.Namespace) -> dict[str, Any]:
    confirm = bool(args.confirm)
    if args.dry_run and args.confirm:
        raise ValueError("--dry-run and --confirm are mutually exclusive")
    if confirm and not args.db_path:
        raise ValueError("confirm requires explicit --db-path")
    config = _config(args)
    if confirm and is_production_like_db(config, args.db_path) and not args.allow_production_db_confirm:
        raise ValueError("production-like DB confirm requires --allow-production-db-confirm")
    service = LiveResearchGapService(config)
    return service.capture_gaps(
        observation_date=args.observation_date,
        confirm=confirm,
        portfolio_id=args.portfolio_id,
        symbol=args.symbol,
        strategy_version_id=args.strategy_version_id,
        source_type=args.source_type,
        limit=args.limit,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = run_capture(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"positions_seen: {payload['positions_seen']}")
        print(f"gap_observations_created: {payload['gap_observations_created']}")
        print(f"dry_run: {payload['dry_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
