"""One-shot locked-OOS gate; never opens the OOS payload before preflight passes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.locked_oos import LockedOOSPreflight, LockedOOSPreflightRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-summary", required=True, type=Path)
    parser.add_argument("--oos-payload", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--confirm-locked-oos", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = _safe_output_root(args.output_root)
    summary = json.loads(args.freeze_summary.read_text(encoding="utf-8"))
    oos_payload_read = False

    def load_oos() -> tuple[object, ...]:
        nonlocal oos_payload_read
        payload = json.loads(args.oos_payload.read_text(encoding="utf-8"))
        oos_payload_read = True
        return tuple(payload) if isinstance(payload, list) else (payload,)

    request = LockedOOSPreflightRequest(
        confirm_locked_oos=bool(args.confirm_locked_oos),
        dataset_content_hash=str(summary["dataset_hash"]),
        model_artifact_hash=str(summary["model_artifact_hash"]),
        max_train_decision_date=str(summary["max_train_decision_date"]),
        max_train_label_available_date=str(summary["max_train_label_available_date"]),
        max_blend_selection_label_available_date=str(
            summary["max_blend_selection_label_available_date"]
        ),
        training_as_of="2024-12-31",
        formal_oos_allowed=bool(summary["formal_oos_allowed"]),
        production_alpha_bp=int(summary["production_alpha_bp"]),
    )
    result = LockedOOSPreflight().execute(request, oos_loader=load_oos)
    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "locked-oos-preflight.v1",
        "executed": result.executed,
        "blockers": list(result.blockers),
        "oos_payload_read": oos_payload_read,
        "payload_count": len(result.payload),
        "production_alpha_bp": result.production_alpha_bp,
        "shadow_only": result.shadow_only,
        "production_action_allowed": result.production_action_allowed,
    }
    (output_root / "locked_oos_preflight.json").write_text(
        json.dumps(report, sort_keys=True, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if result.executed else 2


def _safe_output_root(value: Path) -> Path:
    resolved = value.resolve()
    formal = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    if resolved == formal or formal in resolved.parents:
        raise ValueError("locked OOS output cannot be inside DATA_ROOT")
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
