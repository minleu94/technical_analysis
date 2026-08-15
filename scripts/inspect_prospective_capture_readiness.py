"""Prospective capture readiness inspector.

The default mode is deliberately guarded by ``--fixture-only``.  An explicit
``--controlled-environment`` mode is also available for the owner handoff: it
reads the three formal input paths through the shared Windows controlled
environment reader, then runs the same read-only PFS-06 validators.  Neither
mode starts a watcher, launches Direct/OOC, changes environment variables, or
reads the HMAC secret value.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
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
from data_module.prospective_activation_environment import (  # noqa: E402
    FORMAL_PATH_ENV_NAMES,
    build_prospective_activation_environment_preflight,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="use explicit fixture paths; no environment discovery or heavy rebuild",
    )
    parser.add_argument(
        "--controlled-environment",
        action="store_true",
        help=(
            "explicit owner handoff mode: read formal paths from the shared "
            "Windows controlled environment; never launches ML"
        ),
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
    parser.add_argument(
        "--defer-until-activation",
        action="store_true",
        help=(
            "pre-activation staging mode: defer all three inputs until the "
            "future clock starts; never grants formal credit"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.fixture_only == args.controlled_environment:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "exactly one of --fixture-only or --controlled-environment is required",
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
    if args.defer_until_activation and (
        not args.fixture_only
        or args.controlled_environment
        or args.active_clock
        or any(
            value is not None
            for value in (
                args.portfolio_ledger_manifest,
                args.rule_history,
                args.pit_sector_membership,
            )
        )
    ):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": (
                        "--defer-until-activation requires fixture-only planned "
                        "mode without active clock or input paths"
                    ),
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
    if args.controlled_environment and any(
        value is not None
        for value in (
            args.portfolio_ledger_manifest,
            args.rule_history,
            args.pit_sector_membership,
        )
    ):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "controlled-environment mode forbids explicit formal input paths",
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
    try:
        controlled_paths: dict[str, Path | None] = {
            "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH": args.portfolio_ledger_manifest,
            "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH": args.rule_history,
            "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH": args.pit_sector_membership,
        }
        if args.controlled_environment:
            environment_report = build_prospective_activation_environment_preflight()
            environment_blockers = cast(list[object], environment_report["blockers"])
            if environment_blockers:
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "reason": "controlled environment preflight is not ready",
                            "environment_status": environment_report["status"],
                            "environment_blockers": environment_blockers,
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
            formal_paths = cast(dict[str, object], environment_report["formal_paths"])
            for name in FORMAL_PATH_ENV_NAMES:
                entry = formal_paths.get(name)
                if not isinstance(entry, Mapping):
                    raise ProspectiveCaptureReadinessError(
                        f"controlled environment path entry is invalid: {name}"
                    )
                path_value = entry.get("path")
                if not isinstance(path_value, str) or not path_value:
                    raise ProspectiveCaptureReadinessError(
                        f"controlled environment path is invalid: {name}"
                    )
                controlled_paths[name] = Path(path_value)
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
            portfolio_ledger_manifest_path=controlled_paths[
                "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"
            ],
            rule_history_path=controlled_paths[
                "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH"
            ],
            pit_sector_membership_path=controlled_paths[
                "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH"
            ],
            active_clock=args.active_clock,
            defer_until_activation=args.defer_until_activation,
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
                "deferred_inputs": sum(
                    item.get("state") == "deferred" for item in inputs
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
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
