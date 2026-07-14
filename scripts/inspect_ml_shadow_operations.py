"""Inspect explicit ML shadow registries without creating or mutating them."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.model_lifecycle_registry import ModelLifecycleRegistry
from ml_module.model_prediction_registries import MLShadowPredictionRegistry


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-registry", type=Path, required=True)
    parser.add_argument("--lifecycle-registry", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        predictions = MLShadowPredictionRegistry(
            args.prediction_registry, data_root=args.data_root
        ).list_for_model(args.model_id)
        lifecycle = ModelLifecycleRegistry(
            args.lifecycle_registry, data_root=args.data_root
        )
        events = lifecycle.list_events(args.model_id)
        status = lifecycle.current_status(args.model_id)
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"status": "shadow_registry_unavailable", "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "model_id": args.model_id,
                "lifecycle_status": status,
                "prediction_count": len(predictions),
                "predictions": [asdict(row) for row in predictions],
                "lifecycle_events": [asdict(event) for event in events],
                "formal_rule_unchanged": True,
                "production_action_allowed": False,
                "production_scheduler_allowed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
