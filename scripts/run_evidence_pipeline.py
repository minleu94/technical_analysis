from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_pipeline_runner import EvidencePipelineRunner, write_pipeline_report
from app_module.evidence_pipeline_runner_dtos import EvidencePipelineRunRequest
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the manual evidence pipeline dry-run.")
    parser.add_argument("--decision-date", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--db-path")
    parser.add_argument("--sources", default="all")
    parser.add_argument("--result-id")
    parser.add_argument("--symbol")
    parser.add_argument("--windows", default="5,10,20,60")
    parser.add_argument("--group-by", default="event_type")
    parser.add_argument("--window", type=int, default=20)
    parser.add_argument("--min-sample-size", type=int, default=10)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run. This is also the default.")
    parser.add_argument("--confirm", action="store_true", help="Write to the explicit working-copy DB.")
    parser.add_argument("--skip-snapshot", action="store_true")
    parser.add_argument("--skip-capture", action="store_true")
    parser.add_argument("--skip-outcomes", action="store_true")
    parser.add_argument("--skip-summary", action="store_true")
    parser.add_argument("--json-output", action="store_true", help="Emit JSON summary. JSON is the default.")
    parser.add_argument("--report-output")
    parser.add_argument("--allow-production-db-confirm", action="store_true")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    config = TWStockConfig(**kwargs)
    if args.db_path:
        config.db_file = Path(args.db_path)
        config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _tuple_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def _windows(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in str(value or "").split(",") if item.strip())


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dry_run and args.confirm:
        parser.error("--dry-run and --confirm are mutually exclusive")
    dry_run = bool(args.dry_run or not args.confirm)
    config = _config_from_args(args)
    request = EvidencePipelineRunRequest(
        decision_date=args.decision_date,
        start_date=args.start_date,
        end_date=args.end_date,
        db_path=args.db_path,
        sources=_tuple_csv(args.sources),
        result_id=args.result_id,
        symbol=args.symbol,
        windows=_windows(args.windows),
        group_by=args.group_by,
        window=args.window,
        min_sample_size=args.min_sample_size,
        limit=args.limit,
        dry_run=dry_run,
        confirm=bool(args.confirm),
        skip_snapshot=bool(args.skip_snapshot),
        skip_capture=bool(args.skip_capture),
        skip_outcomes=bool(args.skip_outcomes),
        skip_summary=bool(args.skip_summary),
        report_output=args.report_output,
        allow_production_db_confirm=bool(args.allow_production_db_confirm),
    )
    if args.confirm:
        print("WARNING: confirm mode writes only to the explicit --db-path.", file=sys.stderr)
    try:
        summary = EvidencePipelineRunner(config, db_path=args.db_path).run(request)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
