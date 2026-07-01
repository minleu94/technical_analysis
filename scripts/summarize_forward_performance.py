from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.forward_performance_read_model import (
    SUPPORTED_GROUP_BY,
    ForwardPerformanceFilter,
    ForwardPerformanceReadModel,
)
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize read-only forward evidence aggregates.")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--event-type")
    parser.add_argument("--event-family")
    parser.add_argument("--source-type")
    parser.add_argument("--symbol")
    parser.add_argument("--regime")
    parser.add_argument("--sector")
    parser.add_argument("--profile-id")
    parser.add_argument("--strategy-version-id")
    parser.add_argument("--window", type=int)
    parser.add_argument("--group-by", choices=SUPPORTED_GROUP_BY, default="event_type")
    parser.add_argument("--min-sample-size", type=int, default=1)
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    return parser


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Any] = {}
    if args.data_root is not None:
        kwargs["data_root"] = args.data_root
    if args.output_root is not None:
        kwargs["output_root"] = args.output_root
    config = TWStockConfig(**kwargs)
    config.db_file = Path(args.db_path)
    return config


def _filter_from_args(args: argparse.Namespace) -> ForwardPerformanceFilter:
    return ForwardPerformanceFilter(
        start_date=args.start_date,
        end_date=args.end_date,
        event_type=args.event_type,
        event_family=args.event_family,
        source_type=args.source_type,
        symbol=args.symbol,
        regime=args.regime,
        sector=args.sector,
        profile_id=args.profile_id,
        strategy_version_id=args.strategy_version_id,
        window_days=args.window,
    )


def run_summary(args: argparse.Namespace) -> dict[str, Any]:
    config = _config_from_args(args)
    repository = EvidenceEventRepository(config)
    summaries = ForwardPerformanceReadModel(repository).summarize(
        group_by=args.group_by,
        filters=_filter_from_args(args),
        min_sample_size=args.min_sample_size,
    )
    rows = [summary.to_dict() for summary in summaries]
    if args.csv_output is not None:
        _write_csv(args.csv_output, rows)
    return {
        "db_path": str(config.db_file),
        "group_by": args.group_by,
        "window": args.window,
        "min_sample_size": args.min_sample_size,
        "summary_count": len(rows),
        "summaries": rows,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["group_by", "group_key", "window_days", "sample_size", "summary_status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(json.dumps(run_summary(args), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
