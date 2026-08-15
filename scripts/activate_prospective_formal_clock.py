"""Fixture-only CLI for publishing a prospective PFS-07 activation manifest."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from data_module.prospective_calibration_policy import (
    load_prospective_calibration_policy,
)
from data_module.prospective_formal_clock import load_clock_manifest
from data_module.prospective_formal_clock_activation import (
    ProspectiveClockActivationError,
    build_prospective_clock_activation_manifest,
    write_immutable_clock_activation_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--portfolio-ledger-path", type=Path, required=True)
    parser.add_argument("--rule-history-path", type=Path, required=True)
    parser.add_argument("--pit-sector-path", type=Path, required=True)
    parser.add_argument("--controlled-store-id", required=True)
    parser.add_argument("--hmac-secret-store-configured", action="store_true")
    parser.add_argument("--owner-activation-id", required=True)
    parser.add_argument("--owner-activation-timestamp", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing activation CLI without explicit --fixture-only; "
            "this command never writes Windows environment variables",
            file=sys.stderr,
        )
        return 2
    try:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        activation_timestamp = datetime.fromisoformat(
            args.owner_activation_timestamp.replace("Z", "+00:00")
        )
        clock = load_clock_manifest(args.clock_manifest, now=now)
        policy = load_prospective_calibration_policy(args.calibration_policy)
        readiness = _read_json_object(args.readiness_report)
        manifest = build_prospective_clock_activation_manifest(
            clock=clock,
            calibration_policy=policy,
            readiness_report=readiness,
            controlled_paths={
                "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH": args.portfolio_ledger_path,
                "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH": args.rule_history_path,
                "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH": args.pit_sector_path,
            },
            controlled_store_id=args.controlled_store_id,
            hmac_secret_store_configured=args.hmac_secret_store_configured,
            owner_activation_id=args.owner_activation_id,
            owner_activation_timestamp=activation_timestamp,
            now=now,
        )
        file_hash = write_immutable_clock_activation_manifest(args.output, manifest)
    except (OSError, ValueError, ProspectiveClockActivationError) as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "clock_id": manifest["clock_id"],
                "activation_trading_day": manifest["activation_trading_day"],
                "manifest_hash": manifest["manifest_hash"],
                "file_hash": file_hash,
                "heavy_rebuild_launch_allowed": False,
                "formal_oos_allowed": False,
                "secret_values_emitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _read_json_object(path: Path) -> dict[str, object]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("readiness report root must be an object")
    return raw


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
