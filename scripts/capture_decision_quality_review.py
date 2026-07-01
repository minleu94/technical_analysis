from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.decision_quality_service import DecisionQualityService
from data_module.config import TWStockConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a dry-run or confirmed decision quality review.")
    parser.add_argument("--review-type", choices=["weekly", "monthly", "custom"], required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--db-path")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    parser.add_argument("--portfolio-id", default="default")
    parser.add_argument("--symbol")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--allow-production-like-db", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    return parser.parse_args()


def _config(args: argparse.Namespace) -> TWStockConfig:
    config = TWStockConfig(data_root=args.data_root, output_root=args.output_root)
    if args.db_path:
        config.db_file = Path(args.db_path)
    config.use_sqlite = True
    return config


def _production_like(path: Path, config: TWStockConfig) -> bool:
    configured = Path(config.data_root) / "sqlite" / "twstock.db"
    return path.resolve() == configured.resolve()


def main() -> int:
    args = parse_args()
    if args.confirm and not args.db_path:
        print("confirm requires explicit --db-path", file=sys.stderr)
        return 2
    config = _config(args)
    db_path = Path(config.db_file)
    if args.confirm and _production_like(db_path, config) and not args.allow_production_like_db:
        print("confirm blocked for production-like DB without --allow-production-like-db", file=sys.stderr)
        return 2
    service = DecisionQualityService(config, db_path=db_path)
    review, items = service.build_review(
        review_type=args.review_type,
        start_date=args.start_date,
        end_date=args.end_date,
        portfolio_id=args.portfolio_id,
        symbol=args.symbol,
    )
    result = service.save_review(review, items=items, confirm=bool(args.confirm))
    item_counts: dict[str, int] = {}
    for item in items:
        item_counts[item.item_type] = item_counts.get(item.item_type, 0) + 1
    payload = {
        "review_id": review.review_id,
        "review_type": review.review_type,
        "review_period_start": review.review_period_start,
        "review_period_end": review.review_period_end,
        "items_seen": len(items),
        "items_created": result.items_created,
        "items_skipped_duplicate": len(items) if result.skipped_duplicate else 0,
        "ignored_alert_count": review.ignored_alert_count,
        "manual_override_count": review.manual_override_count,
        "trade_without_source_trace_count": item_counts.get("trade_without_source_trace", 0),
        "missed_signal_count": review.missed_high_quality_signal_count,
        "unreviewed_decay_count": review.unreviewed_decay_candidate_count,
        "large_gap_count": item_counts.get("large_live_research_gap", 0),
        "decision_quality_score_bp": review.decision_quality_score_bp,
        "review_status": review.review_status,
        "warnings_count": len(review.warnings_json),
        "dry_run": not bool(args.confirm),
    }
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
