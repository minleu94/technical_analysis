"""建立正式 Portfolio ML 全市場 out-of-core 數值 store。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.portfolio_ml_out_of_core_store import (  # noqa: E402
    PortfolioMLOutOfCoreStoreBuilder,
    PortfolioMLOutOfCoreStoreRequest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--training-manifest",
        type=Path,
        required=True,
        help="portfolio-ml-training-shards.v2 manifest",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument(
        "--lane",
        choices=("formal", "research-shadow"),
        default="formal",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="若已有不完整 run，直接 fail closed。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = _parser().parse_args(argv)
    try:
        publication = PortfolioMLOutOfCoreStoreBuilder().build(
            PortfolioMLOutOfCoreStoreRequest(
                training_manifest_path=args.training_manifest,
                output_root=args.output_dir,
                batch_size=args.batch_size,
                workers=args.workers,
                memory_budget_mb=args.memory_budget_mb,
                resume=not args.no_resume,
                lane=(
                    "research_shadow"
                    if args.lane == "research-shadow"
                    else "formal"
                ),
            )
        )
    except (OSError, TypeError, ValueError, KeyError, OverflowError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
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
                "lane": args.lane,
                "research_only": args.lane == "research-shadow",
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
