"""建立 official overlay→Research/PIT/Direct 的唯讀研究 readback。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_research_shadow_overlay_integration import (  # noqa: E402
    INTEGRATION_STATUS,
    build_research_shadow_overlay_direct_readback,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only research integration of the official label overlay "
            "with ResearchShadowUnion, shared PIT, and Direct numeric rows."
        )
    )
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--label-replay", type=Path, required=True)
    parser.add_argument("--research-union-manifest", type=Path, required=True)
    parser.add_argument("--pit-manifest", type=Path, required=True)
    parser.add_argument("--pit-shared-store", type=Path, required=True)
    parser.add_argument("--direct-manifest", type=Path, required=True)
    parser.add_argument(
        "--direct-shared-store",
        type=Path,
        help="Only needed when the selected Direct annual artifacts are shared.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_research_shadow_overlay_direct_readback(
            overlay_path=args.overlay,
            label_replay_path=args.label_replay,
            research_union_manifest_path=args.research_union_manifest,
            pit_manifest_path=args.pit_manifest,
            pit_shared_store_root=args.pit_shared_store,
            direct_manifest_path=args.direct_manifest,
            output_path=args.output,
            direct_shared_store_root=args.direct_shared_store,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "read_only": True,
                    "research_only": True,
                    "formal_training_allowed": False,
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
        "output_path": str(result.output_path),
        "status": INTEGRATION_STATUS,
        "read_only": True,
        "research_only": True,
        "formal_training_allowed": False,
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


if __name__ == "__main__":
    raise SystemExit(main())
