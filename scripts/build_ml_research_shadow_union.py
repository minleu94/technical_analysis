"""建立永遠不可 Promotion 的全欄位 Research 配置訓練資料集。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_research_shadow_union import (  # noqa: E402
    ResearchShadowUnionBuilder,
    ResearchShadowUnionRequest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Join verified formal allocation rows with research-shadow "
            "features by symbol/decision_at. Output is permanently "
            "research-only, alpha=0 and promotion-ineligible."
        )
    )
    parser.add_argument(
        "--formal-raw-manifest", type=Path, required=True
    )
    parser.add_argument(
        "--shadow-raw-manifest", type=Path, required=True
    )
    parser.add_argument(
        "--base-training-manifest", type=Path, required=True
    )
    parser.add_argument(
        "--corporate-action-manifest",
        type=Path,
        help=(
            "Optional official-market-event-publication.v1. Only PIT "
            "halt/resume events may become research features; result-only "
            "corporate actions remain label/ledger-only."
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--years", nargs="+", type=int, default=())
    parser.add_argument("--batch-size", type=int, default=2_048)
    parser.add_argument(
        "--compression-level",
        type=int,
        choices=range(0, 10),
        default=6,
        metavar="0..9",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8()
    args = build_parser().parse_args(argv)
    try:
        result = ResearchShadowUnionBuilder().build(
            ResearchShadowUnionRequest(
                formal_raw_manifest_path=args.formal_raw_manifest,
                shadow_raw_manifest_path=args.shadow_raw_manifest,
                base_training_manifest_path=args.base_training_manifest,
                corporate_action_manifest_path=(
                    args.corporate_action_manifest
                ),
                output_root=args.output_dir,
                symbols=(
                    None
                    if args.symbols is None
                    else tuple(args.symbols)
                ),
                years=tuple(args.years),
                batch_size=args.batch_size,
                compression_level=args.compression_level,
            )
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
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
    payload = {
        **asdict(result),
        "publication_directory": str(result.publication_directory),
        "manifest_path": str(result.manifest_path),
        "latest_manifest_path": str(result.latest_manifest_path),
        "shard_paths": [str(path) for path in result.shard_paths],
        "status": "research_union_built",
        "research_only": True,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "promotion_eligible": False,
    }
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
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
