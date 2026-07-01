from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_scheduler_readiness import evaluate_evidence_scheduler_readiness
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate manual evidence scheduler readiness.")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--decision-date")
    parser.add_argument("--result-id")
    parser.add_argument("--smoke-report")
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    return TWStockConfig(**kwargs)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = evaluate_evidence_scheduler_readiness(
        _config_from_args(args),
        db_path=args.db_path,
        smoke_report_path=args.smoke_report,
        decision_date=args.decision_date,
        result_id=args.result_id,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
