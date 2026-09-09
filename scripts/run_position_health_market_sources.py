"""建立每日 position-health PIT condition／Decimal metrics derived sources。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.position_health_market_source_producer import (  # noqa: E402
    PositionHealthMarketSourceError,
    PositionHealthMarketSourceProducer,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read verified daily technical market rows and create isolated "
            "PIT condition and Decimal metric artifacts."
        )
    )
    parser.add_argument("--baseline", required=True, help="position-health baseline JSON")
    parser.add_argument("--market-db", required=True, help="read-only market SQLite")
    parser.add_argument("--quick-status", required=True, help="data-update quick status JSON")
    parser.add_argument("--freshness-status", required=True, help="data-freshness status JSON")
    parser.add_argument("--output-dir", required=True, help="isolated derived output directory")
    parser.add_argument("--decision-date", required=True, help="health decision date YYYY-MM-DD")
    parser.add_argument("--decision-at", help="timezone-aware health cutoff")
    parser.add_argument("--observed-at", help="timezone-aware observation time")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # With no explicit historical clock, the producer captures a real start
    # and completion time around the SQLite read and adopts completion as the
    # effective health cutoff.  Explicit clocks remain fail-closed inputs.
    observed = args.observed_at
    decision_at = args.decision_at
    try:
        result = PositionHealthMarketSourceProducer(
            market_db_path=args.market_db,
            quick_status_path=args.quick_status,
            freshness_status_path=args.freshness_status,
        ).produce(
            baseline_path=args.baseline,
            output_dir=args.output_dir,
            decision_date=args.decision_date,
            decision_at=decision_at,
            observed_at=observed,
        )
    except (OSError, ValueError, PositionHealthMarketSourceError) as exc:
        result = {
            "status": "blocked",
            "producer": "scripts.run_position_health_market_sources",
            "error_type": type(exc).__name__,
            "blockers": [str(exc)],
            "read_only": True,
            "writes_market_database": False,
            "writes_paper_state": False,
            "writes_formal_state": False,
            "research_only": True,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {"passed", "degraded"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
