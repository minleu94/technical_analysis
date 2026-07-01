from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.live_research_gap_repository import LiveResearchGapRepository
from data_module.config import TWStockConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect saved live vs research gap observations.")
    parser.add_argument("--observation-date")
    parser.add_argument("--db-path")
    parser.add_argument("--portfolio-id", default="default")
    parser.add_argument("--symbol")
    parser.add_argument("--strategy-version-id")
    parser.add_argument("--source-type")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--group-by", default="source_type")
    parser.add_argument("--min-sample-size", type=int, default=1)
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


def run_inspect(args: argparse.Namespace) -> dict[str, Any]:
    repo = LiveResearchGapRepository(_config(args))
    observations = repo.list_observations(
        observation_date=args.observation_date,
        symbol=args.symbol,
        source_type=args.source_type,
        strategy_version_id=args.strategy_version_id,
        limit=args.limit,
    )
    summary = repo.summarize_live_research_gaps(
        group_by=args.group_by,
        min_sample_size=args.min_sample_size,
    )
    return {
        "observations_count": len(observations),
        "observations": [item.to_dict() for item in observations],
        "summary": [item.to_dict() for item in summary],
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
        for item in payload["summary"]:
            print(f"{item['group_by']}={item['group_key']} sample_size={item['sample_size']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
