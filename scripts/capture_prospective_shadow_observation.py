"""Fixture-only writer for one activation-bound prospective shadow observation.

This command only assembles hashes and already-observed outcome rows supplied by
the caller.  PFS-08 performs the actual clock, T-1, maturity and no-replay
validation; this wrapper never downloads data, replays history, creates a
teacher target, starts ML, or grants formal/promotion authority.
"""

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
    load_prospective_calibration_policy,
)
from data_module.prospective_formal_clock import (  # noqa: E402
    load_clock_manifest_for_capture,
)
from data_module.prospective_formal_clock_activation import (  # noqa: E402
    validate_prospective_clock_activation_manifest,
)
from data_module.prospective_shadow_maturity import (  # noqa: E402
    ProspectiveShadowMaturityError,
    build_prospective_shadow_observation,
    write_immutable_shadow_observation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--activation-manifest", type=Path, required=True)
    parser.add_argument("--capture-date", required=True)
    parser.add_argument("--decision-timestamp", required=True)
    parser.add_argument("--previous-trading-day", required=True)
    parser.add_argument("--input-state-date", required=True)
    parser.add_argument("--pit-publication-hash", required=True)
    parser.add_argument("--rule-snapshot-hash", required=True)
    parser.add_argument("--portfolio-transition-hash", required=True)
    parser.add_argument("--inference-artifact-hash", required=True)
    parser.add_argument("--source-lineage-hash", required=True)
    parser.add_argument("--outcome-rows-json", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing shadow observation capture without explicit --fixture-only; "
            "historical replay/backfill is never an input",
            file=sys.stderr,
        )
        return 2
    try:
        now = _parse_datetime(args.now, "--now")
        clock = load_clock_manifest_for_capture(args.clock_manifest, now=now)
        policy = load_prospective_calibration_policy(args.calibration_policy)
        readiness = _read_object(args.readiness_report)
        activation_raw = _read_object(args.activation_manifest)
        activation = validate_prospective_clock_activation_manifest(
            activation_raw,
            clock=clock,
            calibration_policy=policy,
            readiness_report=readiness,
            now=now,
        )
        observation = build_prospective_shadow_observation(
            activation=activation,
            capture_date=args.capture_date,
            decision_timestamp=args.decision_timestamp,
            previous_trading_day=args.previous_trading_day,
            input_state_date=args.input_state_date,
            pit_publication_hash=args.pit_publication_hash,
            rule_snapshot_hash=args.rule_snapshot_hash,
            portfolio_transition_hash=args.portfolio_transition_hash,
            inference_artifact_hash=args.inference_artifact_hash,
            source_lineage_hash=args.source_lineage_hash,
            outcome_rows=_read_rows(args.outcome_rows_json),
            now=now,
        )
        file_hash = write_immutable_shadow_observation(args.output, observation)
    except (OSError, ValueError, ProspectiveShadowMaturityError) as error:
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
                "status": observation["status"],
                "schema_version": observation["schema_version"],
                "capture_date": observation["capture_date"],
                "observation_hash": observation["observation_hash"],
                "file_hash": file_hash,
                "fixture_only": True,
                "future_teacher_target_used": False,
                "same_day_advice_used": False,
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


def _read_rows(path: Path) -> list[dict[str, object]]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("outcome_rows")
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ValueError("outcome rows JSON must be an array of objects")
    return raw


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
