"""Raw PIT 年度 shards 直接建立 numeric OOC store（無全期 spool/JSONL）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.portfolio_ml_direct_numeric_store import (  # noqa: E402
    PortfolioMLDirectNumericRequest,
    PortfolioMLDirectNumericStoreBuilder,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--benchmark-entity", required=True)
    parser.add_argument("--sector-membership", type=Path)
    parser.add_argument("--corporate-action-manifest", type=Path)
    parser.add_argument("--formal-portfolio-ledger", type=Path)
    parser.add_argument("--formal-rule-champion-history", type=Path)
    parser.add_argument("--minimum-train-dates", type=int, default=252)
    parser.add_argument("--test-date-count", type=int, default=63)
    parser.add_argument("--purge-trading-days", type=int, default=60)
    parser.add_argument("--embargo-trading-days", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument("--temporary-storage-budget-bytes", type=int)
    parser.add_argument("--no-resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = _parser().parse_args(argv)
    try:
        publication = PortfolioMLDirectNumericStoreBuilder().build(
            PortfolioMLDirectNumericRequest(
                raw_manifest_path=args.raw_manifest,
                output_root=args.output_dir,
                training_as_of=args.training_as_of,
                benchmark_entity_id=args.benchmark_entity,
                sector_membership_path=args.sector_membership,
                corporate_action_manifest_path=(
                    args.corporate_action_manifest
                ),
                formal_portfolio_ledger_path=args.formal_portfolio_ledger,
                formal_rule_champion_history_path=(
                    args.formal_rule_champion_history
                ),
                minimum_train_dates=args.minimum_train_dates,
                test_date_count=args.test_date_count,
                purge_trading_days=args.purge_trading_days,
                embargo_trading_days=args.embargo_trading_days,
                batch_size=args.batch_size,
                workers=args.workers,
                memory_budget_mb=args.memory_budget_mb,
                temporary_storage_budget_bytes=(
                    args.temporary_storage_budget_bytes
                ),
                resume=not args.no_resume,
            )
        )
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        OverflowError,
        RuntimeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "direct_numeric_store": True,
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": "complete",
                "run_id": publication.run_id,
                "manifest_path": str(publication.manifest_path),
                "manifest_hash": publication.manifest_hash,
                "manifest_file_hash": publication.manifest_file_hash,
                "row_count": publication.row_count,
                "feature_count": publication.feature_count,
                "fold_count": publication.fold_count,
                "direct_numeric_store": True,
                "full_market_ready": publication.full_market_ready,
                "readiness_failed_checks": list(
                    publication.readiness_failed_checks
                ),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
