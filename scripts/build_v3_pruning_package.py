"""Build a review-only V3 pruning proposal package from metric JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.v3_pruning_decision_service import V3PruningDecisionService


def build_package(payload: dict[str, Any], *, minimum_sample: int) -> dict[str, Any]:
    service = V3PruningDecisionService(minimum_sample=minimum_sample)
    validation_status = str(payload.get("manual_validation_status", "PENDING_MANUAL_VALIDATION"))
    proposals = [
        service.propose(
            slice_id=str(item.get("slice_id", "unknown")),
            metrics=item,
            manual_validation_status=validation_status,
        ).to_dict()
        for item in payload.get("slices", ())
    ]
    return {
        "schema_version": "v3-pruning-package.v1",
        "manual_validation_status": validation_status,
        "access_boundary": {
            "apply_action": False,
            "auto_trading": False,
            "review_required": True,
        },
        "proposals": proposals,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-sample", type=int, default=30)
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    package = build_package(payload, minimum_sample=args.minimum_sample)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(package, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
