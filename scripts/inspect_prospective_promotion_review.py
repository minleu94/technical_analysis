"""Fixture-only CLI for the PFS-10 promotion review package."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, cast

from data_module.prospective_calibration_policy import (
    load_prospective_calibration_policy,
)
from data_module.prospective_formal_clock import load_clock_manifest_for_capture
from data_module.prospective_formal_clock_activation import (
    validate_prospective_clock_activation_manifest,
)
from data_module.prospective_promotion_review import (
    REQUIRED_MACHINE_GATES,
    ProspectivePromotionReviewError,
    build_prospective_promotion_review_package,
    write_immutable_promotion_review_package,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--activation-manifest", type=Path, required=True)
    parser.add_argument("--maturity-report", type=Path, required=True)
    parser.add_argument("--oos-evidence-package", type=Path, required=True)
    parser.add_argument("--machine-gates", type=Path)
    parser.add_argument("--machine-metrics", type=Path)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing promotion review without explicit --fixture-only; "
            "this command never grants promotion authority",
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
        gates = _read_optional_object(args.machine_gates)
        metrics = _read_optional_object(args.machine_metrics)
        machine_gate_values = None if gates is None else _read_bool_mapping(gates)
        machine_metric_values = None if metrics is None else _read_int_mapping(metrics)
        review = build_prospective_promotion_review_package(
            activation=activation,
            calibration_policy=policy,
            maturity_report=_read_json_object(args.maturity_report),
            oos_evidence_package=_read_json_object(args.oos_evidence_package),
            machine_gates=machine_gate_values,
            machine_metrics=machine_metric_values,
            now=now,
        )
        file_hash = write_immutable_promotion_review_package(args.output, review)
    except (OSError, ValueError, ProspectivePromotionReviewError) as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": review["status"],
                "blockers": review["blockers"],
                "owner_review_required": True,
                "promotion_eligible": False,
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "broker_order_allowed": False,
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


def _read_bool_mapping(value: dict[str, object]) -> dict[str, bool]:
    if set(value) != set(REQUIRED_MACHINE_GATES) or any(
        not isinstance(item, bool) for item in value.values()
    ):
        raise ValueError("machine gates JSON must contain exact boolean gate fields")
    return {key: cast(bool, value[key]) for key in value}


def _read_int_mapping(value: dict[str, object]) -> dict[str, int]:
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value.values()):
        raise ValueError("machine metrics JSON must contain integer values")
    return {key: cast(int, value[key]) for key in value}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
