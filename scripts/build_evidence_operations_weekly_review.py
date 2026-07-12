from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_operations_service import EvidenceOperationsService
from app_module.evidence_operations_history_repository import (
    EvidenceOperationsHistoryReadOnlyError,
    EvidenceOperationsHistoryRepository,
)
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
    parser.add_argument("--save-history", action="store_true")
    parser.add_argument("--list-history", action="store_true")
    parser.add_argument("--history-limit", type=int, default=20)
    parser.add_argument("--action-owner", default="human")
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--markdown-output")
    return parser.parse_args()


def _config(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Any] = {}
    if args.data_root is not None:
        kwargs["data_root"] = args.data_root
    if args.output_root is not None:
        kwargs["output_root"] = args.output_root
    config = TWStockConfig(**kwargs)
    if args.db_path:
        config.db_file = Path(args.db_path)
    config.use_sqlite = True
    return config


_DEFAULT_PRODUCTION_DATA_ROOT = Path("D:/Min/Python/Project/FA_Data")


def _canonical_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _production_like(path: Path, config: TWStockConfig) -> bool:
    actual_db_path = _canonical_path(path)
    production_roots = {
        _canonical_path(Path(config.data_root)),
        _canonical_path(Path(os.environ.get("DATA_ROOT", _DEFAULT_PRODUCTION_DATA_ROOT))),
        _canonical_path(_DEFAULT_PRODUCTION_DATA_ROOT),
    }
    return actual_db_path in {_canonical_path(root / "sqlite" / "twstock.db") for root in production_roots}


def main() -> int:
    args = parse_args()
    config = _config(args)
    if args.save_history and not args.db_path:
        print("save history requires explicit --db-path", file=sys.stderr)
        return 2
    if args.confirm_action_items and not args.db_path:
        print("confirm action items requires explicit --db-path", file=sys.stderr)
        return 2
    if (args.confirm_action_items or args.save_history) and _production_like(Path(config.db_file), config):
        print("production-like DB is not permitted for action confirmation or history saving; use an approved working-copy DB", file=sys.stderr)
        return 2
    if args.list_history:
        diagnostics: list[str] = []
        try:
            records = EvidenceOperationsHistoryRepository(
                config,
                db_path=Path(config.db_file),
                read_only=True,
            ).list_weekly_reviews(
                start_date=args.start_date,
                end_date=args.end_date,
                limit=args.history_limit,
            )
        except EvidenceOperationsHistoryReadOnlyError as exc:
            records = []
            diagnostics.append(str(exc))
        history_payload: dict[str, Any] = {
            "history_records": [record.to_dict() for record in records],
            "diagnostics": diagnostics,
            "write_performed": False,
        }
        if args.json_output:
            print(json.dumps(history_payload, ensure_ascii=False, sort_keys=True))
        else:
            for record in history_payload["history_records"]:
                print(
                    f"{record['period_start']}..{record['period_end']} "
                    f"{record['review_status']} {record['review_id']}"
                )
        return 0
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
        if action_plan.write_performed:
            report = service.build_weekly_review(
                start_date=args.start_date,
                end_date=args.end_date,
                smoke_report_path=args.smoke_report_path,
                result_id=args.result_id,
            )
            payload = report.to_dict()
        payload["action_owner"] = args.action_owner
        payload["action_item_plan"] = action_plan.to_dict()
        payload["write_performed"] = payload["write_performed"] or action_plan.write_performed
    if args.save_history:
        payload["write_performed"] = True
        record = EvidenceOperationsHistoryRepository(config, db_path=Path(config.db_file)).save_weekly_review(
            report,
            generated_by="build_evidence_operations_weekly_review.py",
            payload_json=payload,
        )
        payload["history_record"] = record.to_dict()
        payload["write_performed"] = True
    if args.markdown_output:
        Path(args.markdown_output).write_text(service.render_markdown(report), encoding="utf-8")
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(service.render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
