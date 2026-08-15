"""Fixture-only CLI for the prospective shadow maturity gate."""

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
    validate_prospective_clock_activation_manifest,
)
from data_module.prospective_shadow_maturity import (
    ProspectiveShadowMaturityError,
    build_prospective_shadow_maturity_report,
    write_immutable_shadow_maturity_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--activation-manifest", type=Path, required=True)
    parser.add_argument("--observations-json", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing maturity inspection without explicit --fixture-only; "
            "historical replay/backfill is never an input",
            file=sys.stderr,
        )
        return 2
    try:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
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
        observations = _read_observations(args.observations_json)
        report = build_prospective_shadow_maturity_report(
            activation=activation,
            observations=observations,
            now=now,
        )
        file_hash = write_immutable_shadow_maturity_report(args.output, report)
    except (OSError, ValueError, ProspectiveShadowMaturityError) as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "observed_day_count": report["observed_day_count"],
                "maturity_gate_pass": report["maturity_gate_pass"],
                "blockers": report["blockers"],
                "formal_oos_allowed": False,
                "file_hash": file_hash,
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


def _read_observations(path: Path) -> list[dict[str, object]]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("observations")
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ValueError("observations JSON must be an array of objects")
    return raw


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
