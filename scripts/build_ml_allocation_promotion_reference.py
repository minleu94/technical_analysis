"""建立配置型 ML 的 versioned calibration／PSI promotion reference。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.allocation_promotion_reference import (  # noqa: E402
    build_promotion_reference,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-artifact", type=Path, required=True)
    parser.add_argument("--training-manifest", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--promotion-policy-hash", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--bin-count", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1024)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8()
    args = _parser().parse_args(argv)
    try:
        publication = build_promotion_reference(
            model_artifact_path=args.model_artifact,
            training_manifest_path=args.training_manifest,
            dataset_manifest_path=args.dataset_manifest,
            promotion_policy_hash=args.promotion_policy_hash,
            output_root=args.output_root,
            bin_count=args.bin_count,
            batch_size=args.batch_size,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
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
                "status": "promotion_reference_ready",
                "reference_path": str(publication.reference_path),
                "reference_hash": publication.reference_hash,
                "reference_file_hash": publication.reference_file_hash,
                "row_count": publication.row_count,
                "feature_count": publication.feature_count,
                "family_count": publication.family_count,
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "broker_order_allowed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
