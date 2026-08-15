"""Fixture-only publisher for a prospective simulated Portfolio ledger manifest."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.prospective_simulated_ledger_manifest import (  # noqa: E402
    ProspectiveSimulatedLedgerManifestError,
    load_clock_for_ledger_manifest,
    build_prospective_simulated_ledger_manifest,
    publish_prospective_simulated_ledger_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing ledger manifest publication without explicit --fixture-only",
            file=sys.stderr,
        )
        return 2
    try:
        now = _parse_datetime(args.now)
        clock = load_clock_for_ledger_manifest(args.clock_manifest, now=now)
        manifest = build_prospective_simulated_ledger_manifest(
            clock=clock,
            sqlite_path=args.sqlite,
            manifest_path=args.output,
            now=now,
        )
        file_hash = publish_prospective_simulated_ledger_manifest(args.output, manifest)
    except (OSError, ValueError, ProspectiveSimulatedLedgerManifestError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "fixture_only": True,
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "promotion_eligible": False,
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
                "status": manifest["status"],
                "schema_version": manifest["schema_version"],
                "manifest_hash": manifest["manifest_hash"],
                "file_hash": file_hash,
                "decision_date_count": manifest["decision_date_count"],
                "non_cash_state_day_count": manifest["non_cash_state_day_count"],
                "fixture_only": True,
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "promotion_eligible": False,
                "broker_order_allowed": False,
                "secret_values_emitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("--now is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include timezone")
    return parsed


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
