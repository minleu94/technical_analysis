from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_operations_service import EvidenceOperationsService
from data_module.config import TWStockConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a read-only V1.3 evidence operations weekly review.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--db-path")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    parser.add_argument("--smoke-report-path")
    parser.add_argument("--result-id")
    parser.add_argument("--plan-action-items", action="store_true")
    parser.add_argument("--confirm-action-items", action="store_true")
    parser.add_argument("--action-owner", default="human")
    parser.add_argument("--allow-production-like-db", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--markdown-output")
    return parser.parse_args()


def _config(args: argparse.Namespace) -> TWStockConfig:
    kwargs = {}
    if args.data_root is not None:
        kwargs["data_root"] = args.data_root
    if args.output_root is not None:
        kwargs["output_root"] = args.output_root
    config = TWStockConfig(**kwargs)
    if args.db_path:
        config.db_file = Path(args.db_path)
    config.use_sqlite = True
    return config


def _production_like(path: Path, config: TWStockConfig) -> bool:
    configured = Path(config.data_root) / "sqlite" / "twstock.db"
    return path.resolve() == configured.resolve()


def main() -> int:
    args = parse_args()
    config = _config(args)
    if args.confirm_action_items and not args.db_path:
        print("confirm action items requires explicit --db-path", file=sys.stderr)
        return 2
    if args.confirm_action_items and _production_like(Path(config.db_file), config) and not args.allow_production_like_db:
        print("confirm action items blocked for production-like DB without --allow-production-like-db", file=sys.stderr)
        return 2
    service = EvidenceOperationsService(config, db_path=Path(config.db_file))
    report = service.build_weekly_review(
        start_date=args.start_date,
        end_date=args.end_date,
        smoke_report_path=args.smoke_report_path,
        result_id=args.result_id,
    )
    payload = report.to_dict()
    if args.plan_action_items or args.confirm_action_items:
        action_plan = service.plan_action_items(
            start_date=args.start_date,
            end_date=args.end_date,
            owner=args.action_owner,
            confirm=bool(args.confirm_action_items),
        )
        payload["action_item_plan"] = action_plan.to_dict()
        payload["write_performed"] = payload["write_performed"] or action_plan.write_performed
    if args.markdown_output:
        Path(args.markdown_output).write_text(service.render_markdown(report), encoding="utf-8")
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(service.render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
