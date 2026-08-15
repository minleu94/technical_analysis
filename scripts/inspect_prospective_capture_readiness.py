"""Fixture-only prospective capture readiness inspector."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.prospective_capture_readiness import (  # noqa: E402
    ProspectiveCaptureReadinessError,
    build_prospective_capture_readiness_report,
    write_immutable_capture_readiness_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="required guard: no environment discovery or heavy rebuild",
    )
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--decision-timestamp", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--symbols-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--portfolio-ledger-manifest", type=Path)
    parser.add_argument("--rule-history", type=Path)
    parser.add_argument("--pit-sector-membership", type=Path)
    parser.add_argument(
        "--active-clock",
        action="store_true",
        help="use the capture-time clock loader after activation",
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
                    "capture_only": True,
                    "heavy_rebuild_launch_allowed": False,
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
        symbols: Any = json.loads(args.symbols_json.read_text(encoding="utf-8"))
        if not isinstance(symbols, list) or not all(
            isinstance(item, str) for item in symbols
        ):
            raise ProspectiveCaptureReadinessError(
                "symbols JSON must be a text array"
            )
        try:
            now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        except ValueError as error:
            raise ProspectiveCaptureReadinessError("--now is invalid") from error
        report = build_prospective_capture_readiness_report(
            clock_manifest_path=args.clock_manifest,
            calibration_policy_path=args.calibration_policy,
            decision_timestamp=args.decision_timestamp,
            now=now,
            expected_symbols=tuple(symbols),
            portfolio_ledger_manifest_path=args.portfolio_ledger_manifest,
            rule_history_path=args.rule_history,
            pit_sector_membership_path=args.pit_sector_membership,
            active_clock=args.active_clock,
        )
        file_hash = write_immutable_capture_readiness_report(args.output, report)
    except Exception as exc:  # pragma: no cover - CLI fail-closed boundary
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "capture_only": True,
                    "heavy_rebuild_launch_allowed": False,
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
    guard = cast(dict[str, object], report["heavy_rebuild_guard"])
    inputs = cast(list[dict[str, object]], report["inputs"])
    print(
        json.dumps(
            {
                "status": report["status"],
                "readiness_hash": report["readiness_hash"],
                "readiness_file_hash": file_hash,
                "ready_inputs": sum(
                    item.get("state") == "ready" for item in inputs
                ),
                "input_count": len(inputs),
                "capture_only": report["capture_only"],
                "heavy_rebuild_launch_allowed": guard["heavy_rebuild_launch_allowed"],
                "secret_values_emitted": report["secret_values_emitted"],
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "broker_order_allowed": False,
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
