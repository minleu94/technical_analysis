"""Fixture-only CLI for the PFS-09 frozen-candidate OOS evidence package."""

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
from data_module.prospective_formal_clock import load_clock_manifest_for_capture
from data_module.prospective_formal_clock_activation import (
    validate_prospective_clock_activation_manifest,
)
from data_module.prospective_frozen_oos_evidence import (
    ProspectiveFrozenOOSEvidenceError,
    build_prospective_frozen_oos_evidence_package,
    write_immutable_frozen_oos_evidence_package,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--activation-manifest", type=Path, required=True)
    parser.add_argument("--maturity-report", type=Path, required=True)
    parser.add_argument("--primary-replay", type=Path)
    parser.add_argument("--verification-replay", type=Path)
    parser.add_argument("--calibration-audit", type=Path)
    parser.add_argument("--psi-report", type=Path)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing frozen OOS inspection without explicit --fixture-only; "
            "this command never starts the heavy replay engine",
            file=sys.stderr,
        )
        return 2
    try:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        clock = load_clock_manifest_for_capture(args.clock_manifest, now=now)
        policy = load_prospective_calibration_policy(args.calibration_policy)
        readiness = _read_json_object(args.readiness_report)
        activation = validate_prospective_clock_activation_manifest(
            _read_json_object(args.activation_manifest),
            clock=clock,
            calibration_policy=policy,
            readiness_report=readiness,
            now=now,
        )
        package = build_prospective_frozen_oos_evidence_package(
            activation=activation,
            calibration_policy=policy,
            maturity_report=_read_json_object(args.maturity_report),
            primary_replay=_read_optional_object(args.primary_replay),
            verification_replay=_read_optional_object(args.verification_replay),
            calibration_audit=_read_optional_object(args.calibration_audit),
            psi_report=_read_optional_object(args.psi_report),
            now=now,
        )
        file_hash = write_immutable_frozen_oos_evidence_package(args.output, package)
    except (OSError, ValueError, ProspectiveFrozenOOSEvidenceError) as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": package["status"],
                "blockers": package["blockers"],
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "promotion_eligible": False,
                "heavy_rebuild_launch_allowed": False,
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


def _read_optional_object(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    return _read_json_object(path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
