"""Fixture-only CLI for a low-CPU prospective daily capture start record."""

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

from data_module.prospective_calibration_policy import (
    load_prospective_calibration_policy,
)
from data_module.prospective_formal_clock import load_clock_manifest_for_capture
from data_module.prospective_formal_clock_activation import (
    ProspectiveClockActivation,
    ProspectiveClockActivationError,
    build_daily_capture_activation_record,
    validate_prospective_clock_activation_manifest,
    write_immutable_daily_capture_activation_record,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--activation-manifest", type=Path, required=True)
    parser.add_argument("--capture-date", required=True)
    parser.add_argument("--decision-timestamp", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing daily capture CLI without explicit --fixture-only",
            file=sys.stderr,
        )
        return 2
    try:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        started_at = datetime.fromisoformat(args.started_at.replace("Z", "+00:00"))
        clock = load_clock_manifest_for_capture(args.clock_manifest, now=now)
        policy = load_prospective_calibration_policy(args.calibration_policy)
        readiness = _read_json_object(args.readiness_report)
        activation_raw = _read_json_object(args.activation_manifest)
        activation = validate_prospective_clock_activation_manifest(
            activation_raw,
            clock=clock,
            calibration_policy=policy,
            readiness_report=readiness,
            now=now,
        )
        record = build_daily_capture_activation_record(
            activation=activation,
            capture_date=args.capture_date,
            decision_timestamp=args.decision_timestamp,
            started_at=started_at,
            now=now,
        )
        file_hash = write_immutable_daily_capture_activation_record(args.output, record)
    except (OSError, ValueError, ProspectiveClockActivationError) as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": record["status"],
                "capture_id": record["capture_id"],
                "record_hash": record["record_hash"],
                "file_hash": file_hash,
                "elapsed_day_credit": 0,
                "formal_credit": 0,
                "heavy_rebuild_launch_allowed": False,
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
        raise ValueError("JSON root must be an object")
    return raw


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
