"""以既有配置核心訓練 research-shadow challenger，永久鎖定 alpha=0。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_research_shadow_union import (  # noqa: E402
    RESEARCH_TRAINING_DATASET_IDS,
    lock_research_training_manifest,
    validate_research_training_publication,
)
from scripts.train_ml_allocation_copilot import _run as _run_core_training  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Train the isolated all-field research challenger. The output "
            "manifest schema is intentionally rejected by the formal release "
            "loader and can never authorize non-zero alpha."
        )
    )
    parser.add_argument(
        "--dataset-manifest", type=Path, required=True
    )
    parser.add_argument(
        "--input", type=Path, action="append", required=True
    )
    parser.add_argument("--artifact-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--hgb-max-iter", type=int, default=60)
    parser.add_argument("--ridge-alpha", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8()
    args = build_parser().parse_args(argv)
    try:
        union = validate_research_training_publication(
            args.dataset_manifest,
            tuple(args.input),
        )
        if union.get("dataset_id") not in RESEARCH_TRAINING_DATASET_IDS:
            raise ValueError("research dataset identity mismatch")
        core = _run_core_training(
            input_paths=tuple(args.input),
            artifact_output=args.artifact_output,
            audit_output=args.audit_output,
            manifest_output=args.manifest_output,
            random_state=args.random_state,
            hgb_max_iter=args.hgb_max_iter,
            ridge_alpha=args.ridge_alpha,
        )
        locked = lock_research_training_manifest(
            generic_manifest_path=args.manifest_output,
            union_manifest_path=args.dataset_manifest,
        )
    except (OSError, TypeError, ValueError, KeyError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "research_only": True,
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "promotion_eligible": False,
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
                **core,
                "status": "research_training_completed",
                "training_manifest_schema_version": locked[
                    "schema_version"
                ],
                "research_only": True,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "promotion_eligible": False,
                "formal_consumer_compatible": False,
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
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
