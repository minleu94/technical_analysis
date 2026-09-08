"""在任何 confirmatory fold 讀取前驗證已發布的 ML comparison freeze。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.allocation_base_expert_comparison_freeze_gate import (  # noqa: E402
    ConfirmatoryFreezeGateError,
    authorize_confirmatory_scope,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--published-comparison",
        type=Path,
        required=True,
        help="已發布的 exploratory fold-004 comparison.json receipt",
    )
    parser.add_argument(
        "--fold-id",
        default="fold-005",
        help="只能驗證預先登記的 confirmatory fold-005",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        gate = authorize_confirmatory_scope(
            args.published_comparison,
            fold_id=args.fold_id,
        )
        result = gate.as_dict()
    except (ConfirmatoryFreezeGateError, OSError, TypeError, ValueError) as exc:
        result = {
            "status": "blocked",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "price_data_read": False,
            "label_data_read": False,
            "result_data_read": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
