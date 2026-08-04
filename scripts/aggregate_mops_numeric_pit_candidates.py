"""CLI tool to aggregate multi-candidate MOPS numeric PIT research artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.mops_numeric_pit_aggregator import build_mops_numeric_pit_aggregate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dirs", nargs="+", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--minimum-coverage-bp", type=int, default=8000)
    args = parser.parse_args(argv)

    payload = build_mops_numeric_pit_aggregate(
        candidate_dirs=args.candidate_dirs,
        output_root=args.output_root,
        run_id=args.run_id,
        minimum_coverage_bp=args.minimum_coverage_bp,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
