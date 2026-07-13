"""Build a non-applying Gate 7 ML promotion-review JSON package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.promotion_review_package import MLPromotionReviewPackageService


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-shadow-days", type=int, default=20)
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    package = MLPromotionReviewPackageService(
        minimum_shadow_days=args.minimum_shadow_days
    ).build(
        model_id=str(payload["model_id"]),
        dataset_id=str(payload["dataset_id"]),
        champion_model_id=str(payload["champion_model_id"]),
        shadow_observed_days=int(payload["shadow_observed_days"]),
        comparison_status=str(payload["comparison_status"]),
        drift_statuses=tuple(payload.get("drift_statuses", ())),
        calibration_status=str(payload["calibration_status"]),
        rollback_artifact=str(payload.get("rollback_artifact", "")),
        verification_artifacts=tuple(payload.get("verification_artifacts", ())),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(package.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(package.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
