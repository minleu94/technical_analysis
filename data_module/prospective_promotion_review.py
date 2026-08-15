"""Promotion review package for the prospective formal simulation clock.

PFS-10 is an aggregation and human-review boundary.  It never turns machine
metrics into production authority, never sets a non-zero alpha, and never
places a broker order.  A package can be ``ready_for_owner_review`` while
``promotion_eligible`` remains false until a separate governed decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import os
from pathlib import Path

from data_module.prospective_calibration_policy import ProspectiveCalibrationPolicy
from data_module.prospective_formal_clock import canonical_json, file_sha256, payload_hash
from data_module.prospective_formal_clock_activation import ProspectiveClockActivation
from data_module.prospective_frozen_oos_evidence import (
    ProspectiveFrozenOOSEvidenceError,
    validate_prospective_frozen_oos_evidence_package,
)


PROSPECTIVE_PROMOTION_REVIEW_SCHEMA_VERSION = (
    "prospective-formal-promotion-review-package.v1"
)
REQUIRED_MACHINE_GATES = (
    "formal_oos_replay_ready",
    "dual_replay_identity_match",
    "inference_calibration_pass",
    "psi_pass",
    "rebalance_class_coverage_pass",
    "lookahead_safety_pass",
    "source_lineage_pass",
    "cost_after_fee_pass",
    "drawdown_cvar_pass",
    "turnover_liquidity_pass",
)
OPTIONAL_INTEGER_METRICS = (
    "matured_shadow_days",
    "max_ece_bp",
    "max_brier_bp",
    "max_psi_bp",
    "net_alpha_bp",
    "max_drawdown_bp",
    "cvar_bp",
    "turnover_bp",
)

_REVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "mode",
        "clock_id",
        "clock_manifest_hash",
        "activation_manifest_hash",
        "candidate_model_hash",
        "calibration_policy_hash",
        "evaluation_policy_hash",
        "oos_evidence_package_hash",
        "machine_gates",
        "machine_metrics",
        "blockers",
        "owner_review_required",
        "owner_review_received",
        "owner_authorization_received",
        "promotion_eligible",
        "formal_oos_allowed",
        "production_blend_alpha_bp",
        "broker_order_allowed",
        "secret_values_emitted",
        "review_hash",
    }
)


class ProspectivePromotionReviewError(ValueError):
    """Promotion review package 不符合 fail-closed contract。"""


def build_prospective_promotion_review_package(
    *,
    activation: ProspectiveClockActivation,
    calibration_policy: ProspectiveCalibrationPolicy,
    maturity_report: Mapping[str, object],
    oos_evidence_package: Mapping[str, object],
    machine_gates: Mapping[str, bool] | None,
    machine_metrics: Mapping[str, int] | None,
    now: datetime,
) -> dict[str, object]:
    """聚合 PFS-09 與獨立 machine gates，保留 owner review boundary。"""

    _validate_now(now)
    try:
        validate_prospective_frozen_oos_evidence_package(
            oos_evidence_package,
            activation=activation,
            calibration_policy=calibration_policy,
            maturity_report=maturity_report,
            now=now,
        )
    except ProspectiveFrozenOOSEvidenceError as error:
        raise ProspectivePromotionReviewError(
            f"OOS evidence package is invalid: {error}"
        ) from error
    oos_hash = _required_hash(
        oos_evidence_package.get("package_hash"), "oos_evidence_package_hash"
    )
    blockers: list[str] = []
    if oos_evidence_package.get("status") != "ready_for_formal_review":
        blockers.append("oos_evidence_not_ready_for_formal_review")
    gate_payload, gate_blockers = _normalize_machine_gates(machine_gates)
    blockers.extend(gate_blockers)
    metrics = _normalize_machine_metrics(machine_metrics)
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_PROMOTION_REVIEW_SCHEMA_VERSION,
        "status": "ready_for_owner_review" if not blockers else "blocked_for_owner_review",
        "mode": "prospective_formal_simulation",
        "clock_id": activation.clock_id,
        "clock_manifest_hash": str(activation.payload["clock_manifest_hash"]),
        "activation_manifest_hash": activation.activation_manifest_hash,
        "candidate_model_hash": str(calibration_policy.payload["model_artifact_hash"]),
        "calibration_policy_hash": calibration_policy.policy_hash,
        "evaluation_policy_hash": str(activation.payload["evaluation_policy_hash"]),
        "oos_evidence_package_hash": oos_hash,
        "machine_gates": gate_payload,
        "machine_metrics": metrics,
        "blockers": sorted(set(blockers)),
        "owner_review_required": True,
        "owner_review_received": False,
        "owner_authorization_received": False,
        "promotion_eligible": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    review = {**body, "review_hash": payload_hash(body)}
    validate_prospective_promotion_review_package(
        review,
        activation=activation,
        calibration_policy=calibration_policy,
        oos_evidence_package=oos_evidence_package,
    )
    return review


def validate_prospective_promotion_review_package(
    review: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    calibration_policy: ProspectiveCalibrationPolicy,
    oos_evidence_package: Mapping[str, object],
) -> None:
    """驗證 review package 不會自動越過 human promotion authority。"""

    if set(review) != _REVIEW_FIELDS:
        raise ProspectivePromotionReviewError("promotion review fields are invalid")
    if review.get("schema_version") != PROSPECTIVE_PROMOTION_REVIEW_SCHEMA_VERSION:
        raise ProspectivePromotionReviewError("promotion review schema_version is invalid")
    for field_name, expected in (
        ("mode", "prospective_formal_simulation"),
        ("clock_id", activation.clock_id),
        ("clock_manifest_hash", activation.payload["clock_manifest_hash"]),
        ("activation_manifest_hash", activation.activation_manifest_hash),
        ("candidate_model_hash", calibration_policy.payload["model_artifact_hash"]),
        ("calibration_policy_hash", calibration_policy.policy_hash),
        ("evaluation_policy_hash", activation.payload["evaluation_policy_hash"]),
        ("oos_evidence_package_hash", oos_evidence_package.get("package_hash")),
        ("owner_review_required", True),
        ("owner_review_received", False),
        ("owner_authorization_received", False),
        ("promotion_eligible", False),
        ("formal_oos_allowed", False),
        ("production_blend_alpha_bp", 0),
        ("broker_order_allowed", False),
        ("secret_values_emitted", False),
    ):
        if review.get(field_name) is not expected if isinstance(expected, bool) else review.get(field_name) != expected:
            raise ProspectivePromotionReviewError(
                f"promotion review {field_name} is unsafe or unbound"
            )
    status = review.get("status")
    blockers = review.get("blockers")
    if status not in {"ready_for_owner_review", "blocked_for_owner_review"}:
        raise ProspectivePromotionReviewError("promotion review status is invalid")
    if not isinstance(blockers, list) or blockers != sorted(set(blockers)):
        raise ProspectivePromotionReviewError("promotion review blockers are invalid")
    if (status == "ready_for_owner_review") != (not blockers):
        raise ProspectivePromotionReviewError("promotion review status/blockers mismatch")
    gates = review.get("machine_gates")
    if not isinstance(gates, Mapping) or set(gates) != set(REQUIRED_MACHINE_GATES):
        raise ProspectivePromotionReviewError("promotion review machine gates are invalid")
    if any(not isinstance(value, bool) for value in gates.values()):
        raise ProspectivePromotionReviewError("promotion review machine gates must be boolean")
    metrics = review.get("machine_metrics")
    if not isinstance(metrics, Mapping) or set(metrics) - set(OPTIONAL_INTEGER_METRICS):
        raise ProspectivePromotionReviewError("promotion review machine metrics are invalid")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in metrics.values()):
        raise ProspectivePromotionReviewError("promotion review machine metrics must be integer")
    _validate_hash_shape(review, "review_hash", "promotion review")


def write_immutable_promotion_review_package(
    output_path: Path,
    review: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 review package。"""

    _validate_hash_shape(review, "review_hash", "promotion review")
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectivePromotionReviewError("review output parent must exist")
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(review)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectivePromotionReviewError("review output already exists") from error
    return file_sha256(output)


def _normalize_machine_gates(
    value: Mapping[str, bool] | None,
) -> tuple[dict[str, bool], list[str]]:
    if value is None:
        return {name: False for name in REQUIRED_MACHINE_GATES}, [
            "machine_gate_input_missing"
        ]
    if set(value) != set(REQUIRED_MACHINE_GATES):
        missing = sorted(set(REQUIRED_MACHINE_GATES) - set(value))
        extra = sorted(set(value) - set(REQUIRED_MACHINE_GATES))
        blockers = [f"machine_gate_missing:{name}" for name in missing]
        blockers.extend(f"machine_gate_unknown:{name}" for name in extra)
        normalized = {name: bool(value.get(name, False)) for name in REQUIRED_MACHINE_GATES}
    else:
        normalized = dict(value)
        blockers = []
    for name, gate in normalized.items():
        if not isinstance(gate, bool):
            blockers.append(f"machine_gate_not_boolean:{name}")
        elif gate is False:
            blockers.append(f"machine_gate_failed:{name}")
    return normalized, blockers


def _normalize_machine_metrics(value: Mapping[str, int] | None) -> dict[str, int]:
    if value is None:
        return {}
    if set(value) - set(OPTIONAL_INTEGER_METRICS):
        raise ProspectivePromotionReviewError("machine_metrics contains unknown fields")
    normalized: dict[str, int] = {}
    for name, metric in value.items():
        if isinstance(metric, bool) or not isinstance(metric, int):
            raise ProspectivePromotionReviewError(
                f"machine metric {name} must be an integer"
            )
        normalized[name] = metric
    return normalized


def _validate_hash_shape(value: Mapping[str, object], field_name: str, label: str) -> None:
    supplied = _required_hash(value.get(field_name), field_name)
    body = dict(value)
    body.pop(field_name, None)
    if payload_hash(body) != supplied:
        raise ProspectivePromotionReviewError(f"{label} hash mismatch")


def _required_hash(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in value[7:]
    ):
        raise ProspectivePromotionReviewError(f"{field_name} must be sha256")
    return value


def _validate_now(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectivePromotionReviewError("now must include timezone")
