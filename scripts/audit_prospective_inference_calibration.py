"""Fixture-only audit for the prospective inference-level calibration policy."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.prospective_calibration_policy import (  # noqa: E402
    ProspectiveCalibrationError,
    audit_prospective_inference_calibration,
    load_prospective_calibration_policy,
    write_immutable_calibration_audit,
)
from data_module.prospective_formal_clock import (  # noqa: E402
    load_clock_manifest_for_capture,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="required guard: this CLI never discovers or writes formal inputs",
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--fold-records-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--clock-manifest",
        type=Path,
        help="optional clock binding checked read-only",
    )
    parser.add_argument(
        "--now",
        help="timezone-aware ISO timestamp required with --clock-manifest",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.fixture_only:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "--fixture-only is required",
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        policy = load_prospective_calibration_policy(args.policy)
        records_raw: Any = json.loads(
            args.fold_records_json.read_text(encoding="utf-8")
        )
        if not isinstance(records_raw, list) or not all(
            isinstance(item, dict) for item in records_raw
        ):
            raise ProspectiveCalibrationError(
                "fold records JSON must be an array of objects"
            )
        clock = None
        if args.clock_manifest is not None:
            if not args.now:
                raise ProspectiveCalibrationError(
                    "--now is required with --clock-manifest"
                )
            try:
                now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
            except ValueError as error:
                raise ProspectiveCalibrationError("--now is invalid") from error
            clock = load_clock_manifest_for_capture(args.clock_manifest, now=now)
        audit = audit_prospective_inference_calibration(
            policy=policy,
            fold_records=records_raw,
            clock=clock,
        )
        audit_file_hash = write_immutable_calibration_audit(args.output, audit)
    except Exception as exc:  # pragma: no cover - CLI fail-closed boundary
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                    "secret_values_emitted": False,
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
                "status": audit["status"],
                "audit_hash": audit["audit_hash"],
                "audit_file_hash": audit_file_hash,
                "quality_pass": audit["quality_pass"],
                "blockers": audit["blockers"],
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "broker_order_allowed": False,
                "secret_values_emitted": False,
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
