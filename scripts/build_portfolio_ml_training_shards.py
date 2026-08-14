"""將 raw PIT 年度 observations 組裝成配置型 ML 可直接訓練 shards。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.portfolio_ml_dataset_assembler import (  # noqa: E402
    PortfolioMLDatasetAssembler,
    PortfolioMLDatasetAssemblyRequest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--benchmark-entity", required=True)
    parser.add_argument("--sector-membership", type=Path)
    parser.add_argument("--corporate-action-manifest", type=Path)
    parser.add_argument("--formal-portfolio-ledger", type=Path)
    parser.add_argument("--formal-rule-champion-history", type=Path)
    parser.add_argument("--years", nargs="*", type=int, default=())
    parser.add_argument("--minimum-train-dates", type=int, default=252)
    parser.add_argument("--test-date-count", type=int, default=63)
    parser.add_argument("--purge-trading-days", type=int, default=60)
    parser.add_argument("--embargo-trading-days", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=2_048)
    parser.add_argument("--compression-level", type=int, default=6)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = _parser().parse_args(argv)
    try:
        publication = PortfolioMLDatasetAssembler().build(
            PortfolioMLDatasetAssemblyRequest(
                dataset_manifest_path=args.dataset_manifest,
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
                years=tuple(args.years),
                minimum_train_dates=args.minimum_train_dates,
                test_date_count=args.test_date_count,
                purge_trading_days=args.purge_trading_days,
                embargo_trading_days=args.embargo_trading_days,
                batch_size=args.batch_size,
                compression_level=args.compression_level,
            )
        )
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "direct_training_input": False,
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
            {
                "status": "published",
                "publication_id": publication.publication_id,
                "manifest_path": str(publication.manifest_path),
                "latest_manifest_path": str(publication.latest_manifest_path),
                "manifest_hash": publication.manifest_hash,
                "dataset_manifest_file_hash": (
                    publication.dataset_manifest_file_hash
                ),
                "shard_paths": [str(path) for path in publication.shard_paths],
                "sample_count": publication.sample_count,
                "fold_count": publication.fold_count,
                "direct_training_input": publication.direct_training_input,
                "production_alpha_bp": 0,
                "production_action_allowed": False,
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
