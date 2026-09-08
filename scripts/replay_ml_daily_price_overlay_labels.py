"""以既有 label spool 重播官方 daily-price overlay 的 research labels。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_daily_price_research_pipeline import (  # noqa: E402
    build_research_label_replay_from_overlay,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the existing assembler label spool in an isolated, "
            "research-only official overlay scenario."
        )
    )
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--reference-impact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_research_label_replay_from_overlay(
        overlay_path=args.overlay,
        sqlite_path=args.sqlite,
        reference_impact_path=args.reference_impact,
        output_path=args.output,
    )
    print(
        {
            "status": "completed_research_label_replay",
            "output_path": str(result.output_path),
            "replay_hash": result.replay_hash,
            "row_count": result.row_count,
            "reference_rows_matched": result.reference_rows_matched,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
