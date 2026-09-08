"""以既有 public producers 建立 33 檔 ResearchShadowUnion bounded slice。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_research_shadow_union_bounded import (  # noqa: E402
    BoundedResearchShadowUnionRequest,
    build_bounded_research_shadow_union,
)
from data_module.ml_storage_capacity import (  # noqa: E402
    BYTES_PER_GIB,
    CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--benchmark-entity", default="TAIEX")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--history-start-date", default="2014-01-01")
    parser.add_argument("--years", nargs="*", type=int, default=())
    parser.add_argument("--corporate-action-manifest", type=Path)
    parser.add_argument("--sector-membership", type=Path)
    parser.add_argument("--formal-portfolio-ledger", type=Path)
    parser.add_argument("--formal-rule-champion-history", type=Path)
    parser.add_argument("--minimum-train-dates", type=int, default=20)
    parser.add_argument("--test-date-count", type=int, default=10)
    parser.add_argument("--purge-trading-days", type=int, default=60)
    parser.add_argument("--embargo-trading-days", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=2_048)
    parser.add_argument("--compression-level", type=int, default=6)
    parser.add_argument(
        "--persistent-new-bytes-budget",
        type=int,
        default=BYTES_PER_GIB,
    )
    parser.add_argument(
        "--temporary-peak-bytes-budget",
        type=int,
        default=BYTES_PER_GIB,
    )
    parser.add_argument(
        "--safety-reserve-bytes",
        type=int,
        default=CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
    )
    parser.add_argument("--heavy-lock-path", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_bounded_research_shadow_union(
            BoundedResearchShadowUnionRequest(
                database_path=args.database,
                output_root=args.output_dir,
                decision_at=args.decision_at,
                training_as_of=args.training_as_of,
                benchmark_entity_id=args.benchmark_entity,
                symbols=tuple(args.symbols),
                history_start_date=args.history_start_date,
                years=tuple(args.years),
                corporate_action_manifest_path=args.corporate_action_manifest,
                sector_membership_path=args.sector_membership,
                formal_portfolio_ledger_path=args.formal_portfolio_ledger,
                formal_rule_champion_history_path=(
                    args.formal_rule_champion_history
                ),
                minimum_train_dates=args.minimum_train_dates,
                test_date_count=args.test_date_count,
                purge_trading_days=args.purge_trading_days,
                embargo_trading_days=args.embargo_trading_days,
                batch_size=args.batch_size,
                compression_level=args.compression_level,
                persistent_new_bytes_budget=args.persistent_new_bytes_budget,
                temporary_peak_bytes_budget=args.temporary_peak_bytes_budget,
                safety_reserve_bytes=args.safety_reserve_bytes,
                heavy_lock_path=args.heavy_lock_path,
            )
        )
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "research_only": True,
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "production_action_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
