from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.forward_performance_service import ForwardPerformanceService
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calculate forward research outcomes for evidence events.")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--decision-date", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--event-type", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--windows", default="5,10,20,60")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _parse_windows(value: str) -> tuple[int, ...]:
    windows = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not windows:
        raise ValueError("--windows must include at least one integer")
    return windows


def main() -> int:
    args = build_parser().parse_args()
    config_kwargs = {}
    if args.data_root is not None:
        config_kwargs["data_root"] = args.data_root
    if args.output_root is not None:
        config_kwargs["output_root"] = args.output_root
    config = TWStockConfig(**config_kwargs)
    repo = EvidenceEventRepository(config)
    service = ForwardPerformanceService(config, repo)
    summary = service.calculate(
        windows=_parse_windows(args.windows),
        dry_run=args.dry_run,
        decision_date=args.decision_date,
        start_date=args.start_date,
        end_date=args.end_date,
        event_type=args.event_type,
        symbol=args.symbol,
        limit=args.limit,
    )
    print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
