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
    parser = argparse.ArgumentParser(description="Inspect decision quality review coverage without writing data.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--db-path")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    parser.add_argument("--portfolio-id", default="default")
    parser.add_argument("--symbol")
    parser.add_argument("--json-output", action="store_true")
    return parser.parse_args()


def _config(args: argparse.Namespace) -> TWStockConfig:
    config = TWStockConfig(data_root=args.data_root, output_root=args.output_root)
    if args.db_path:
        config.db_file = Path(args.db_path)
    config.use_sqlite = True
    return config


def main() -> int:
    args = parse_args()
    config = _config(args)
    service = DecisionQualityService(config, db_path=Path(config.db_file))
    review, items = service.build_review(
        review_type="custom",
        start_date=args.start_date,
        end_date=args.end_date,
        portfolio_id=args.portfolio_id,
        symbol=args.symbol,
    )
    saved = service.list_reviews(start_date=args.start_date, end_date=args.end_date)
    summary = service.summarize_reviews()
    payload = {
        "saved_reviews_count": len(saved),
        "summary": summary.to_dict(),
        "candidate_review": review.to_dict(),
        "candidate_items_seen": len(items),
        "candidate_item_counts": dict(sorted(Counter(item.item_type for item in items).items())),
        "write_performed": False,
    }
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


from collections import Counter


if __name__ == "__main__":
    raise SystemExit(main())
