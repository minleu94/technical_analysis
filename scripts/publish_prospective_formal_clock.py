"""Fixture-only publisher for an explicitly owner-bound prospective clock."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.prospective_formal_clock import (  # noqa: E402
    ProspectiveFormalClockError,
    build_clock_manifest,
    validate_clock_manifest,
    write_immutable_clock_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-id", required=True)
    parser.add_argument("--owner-decision-id", required=True)
    parser.add_argument("--owner-decision-timestamp", required=True)
    parser.add_argument("--activation-trading-day", required=True)
    parser.add_argument("--calendar-evidence-json", type=Path, required=True)
    parser.add_argument("--seed-state-json", type=Path, required=True)
    parser.add_argument("--virtual-notional-minor-units", type=int, required=True)
    parser.add_argument("--strategy-version", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--policy-hash", required=True)
    parser.add_argument("--universe-hash", required=True)
    parser.add_argument("--source-policy-hash", required=True)
    parser.add_argument("--candidate-model-hash", required=True)
    parser.add_argument("--candidate-feature-manifest-hash", required=True)
    parser.add_argument("--candidate-training-cutoff", required=True)
    parser.add_argument("--calibration-policy-hash", required=True)
    parser.add_argument("--evaluation-policy-hash", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing prospective clock publication without explicit --fixture-only",
            file=sys.stderr,
        )
        return 2
    try:
        now = _parse_datetime(args.now, "--now")
        calendar = _read_object(args.calendar_evidence_json)
        seed = _read_object(args.seed_state_json)
        body: dict[str, object] = {
            "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
            "status": "planned",
            "clock_id": args.clock_id,
            "mode": "prospective_formal_simulation",
            "owner_decision_id": args.owner_decision_id,
            "owner_decision_timestamp": args.owner_decision_timestamp,
            "activation_trading_day": args.activation_trading_day,
            "decision_timezone": "Asia/Taipei",
            "decision_time": "08:30:00",
            "activation_calendar_evidence": calendar,
            "seed_state": seed,
            "virtual_notional_minor_units": args.virtual_notional_minor_units,
            "strategy_version": args.strategy_version,
            "policy_version": args.policy_version,
            "policy_hash": args.policy_hash,
            "universe_hash": args.universe_hash,
            "source_policy_hash": args.source_policy_hash,
            "candidate_model_hash": args.candidate_model_hash,
            "candidate_feature_manifest_hash": args.candidate_feature_manifest_hash,
            "candidate_training_cutoff": args.candidate_training_cutoff,
            "calibration_policy_hash": args.calibration_policy_hash,
            "evaluation_policy_hash": args.evaluation_policy_hash,
            "real_money": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
        }
        manifest = build_clock_manifest(body)
        validate_clock_manifest(
            manifest,
            now=now,
            calendar_evidence=calendar,
        )
        file_hash = write_immutable_clock_manifest(args.output, manifest)
    except (OSError, ValueError, ProspectiveFormalClockError) as error:
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
                "clock_id": manifest["clock_id"],
                "activation_trading_day": manifest["activation_trading_day"],
                "manifest_hash": manifest["manifest_hash"],
                "file_hash": file_hash,
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


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed


def _read_object(path: Path) -> dict[str, object]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} root must be an object")
    return raw


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
