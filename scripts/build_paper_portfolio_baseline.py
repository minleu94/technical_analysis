"""從已保存 Recommendation 建立 V2.4 research-only paper baseline。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_portfolio_baseline_service import PaperPortfolioBaselineService


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a research-only paper portfolio baseline from a saved Recommendation JSON."
    )
    parser.add_argument("--recommendation-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    payload = PaperPortfolioBaselineService().build(args.recommendation_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_path": str(output_path),
                "source_result_id": payload["source_result_id"],
                "research_only": True,
                "writes_positions_db": False,
                "broker_order_allowed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
