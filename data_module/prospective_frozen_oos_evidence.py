"""Frozen-candidate OOS evidence contract for the prospective formal clock.

This is a custody/readiness layer for PFS-09.  It does not run the existing
heavy replay engine, fit a calibrator, calculate PSI, or choose a method after
outcomes.  It accepts only already-produced, hash-addressed primary and
verification results and keeps the production boundary fail-closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from data_module.prospective_calibration_policy import (
    PROSPECTIVE_CALIBRATION_AUDIT_SCHEMA_VERSION,
    ProspectiveCalibrationPolicy,
)
from data_module.prospective_formal_clock import (
    canonical_json,
    file_sha256,
    payload_hash,
)
from data_module.prospective_formal_clock_activation import (
    ProspectiveClockActivation,
)
from data_module.prospective_shadow_maturity import (
    MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON,
    MINIMUM_SHADOW_DAYS,
)


PROSPECTIVE_FROZEN_REPLAY_RESULT_SCHEMA_VERSION = (
    "prospective-formal-frozen-oos-replay-result.v1"
)
PROSPECTIVE_FROZEN_OOS_EVIDENCE_SCHEMA_VERSION = (
    "prospective-formal-frozen-oos-evidence.v1"
)
PROSPECTIVE_PSI_REPORT_SCHEMA_VERSION = "prospective-formal-psi-report.v1"
FROZEN_OOS_HORIZONS = (5, 10, 20, 60)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")

_REPLAY_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "mode",
        "role",
        "clock_id",
        "clock_manifest_hash",
        "activation_manifest_hash",
        "maturity_report_hash",
        "model_artifact_hash",
        "candidate_feature_manifest_hash",
        "dataset_identity_hash",
        "calibration_policy_hash",
        "evaluation_policy_hash",
        "result_identity_hash",
        "replay_result_hash",
        "source_lineage_hash",
        "outcome_row_count",
        "horizon_observation_counts",
        "fit_called",
        "retrained",
        "post_outcome_method_selection",
        "teacher_future_targets_used",
        "same_day_advice_used",
        "formal_oos_allowed",
        "production_blend_alpha_bp",
        "broker_order_allowed",
        "result_hash",
    }
)
_PSI_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "clock_id",
        "model_artifact_hash",
        "dataset_identity_hash",
        "reference_identity_hash",
        "feature_count",
        "max_psi_bp",
        "psi_threshold_bp",
        "quality_pass",
        "formal_oos_allowed",
        "promotion_eligible",
        "report_hash",
    }
)
_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "mode",
        "capture_only",
        "clock_id",
        "clock_manifest_hash",
        "activation_manifest_hash",
        "maturity_report_hash",
        "candidate_model_hash",
        "candidate_feature_manifest_hash",
        "dataset_identity_hash",
        "calibration_policy_hash",
        "evaluation_policy_hash",
        "primary_replay_result_hash",
        "verification_replay_result_hash",
        "replay_identity_hash",
        "calibration_audit_hash",
        "calibration_quality_pass",
        "psi_report_hash",
        "psi_quality_pass",
        "blockers",
        "replay_fit_called",
        "retrained",
        "post_outcome_method_selection",
        "replay_used",
        "backfilled",
        "synthetic_outcomes_used",
        "formal_oos_allowed",
        "production_blend_alpha_bp",
        "promotion_eligible",
        "broker_order_allowed",
        "secret_values_emitted",
        "package_hash",
    }
)


class ProspectiveFrozenOOSEvidenceError(ValueError):
    """PFS-09 frozen-candidate evidence 不符合 custody 契約。"""


def build_prospective_frozen_oos_replay_result(
    *,
    activation: ProspectiveClockActivation,
    calibration_policy: ProspectiveCalibrationPolicy,
    role: str,
    maturity_report_hash: str,
    result_identity_hash: str,
    replay_result_hash: str,
    source_lineage_hash: str,
    outcome_row_count: int,
    horizon_observation_counts: Mapping[str, int],
) -> dict[str, object]:
    """封裝一份已完成的 primary／verification replay result。

    這個函式只建立 custody wrapper；所有結果數值必須由外部 frozen-candidate
    replay 產生，不能由這裡 fit、retrain 或重播 history。
    """

    _validate_policy_binding(activation, calibration_policy)
    if role not in {"primary", "verification"}:
        raise ProspectiveFrozenOOSEvidenceError("replay role must be primary or verification")
    _required_hash(maturity_report_hash, "maturity_report_hash")
    _required_hash(result_identity_hash, "result_identity_hash")
    _required_hash(replay_result_hash, "replay_result_hash")
    _required_hash(source_lineage_hash, "source_lineage_hash")
    _required_positive_int(outcome_row_count, "outcome_row_count")
    counts = _normalize_horizon_counts(horizon_observation_counts)
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_FROZEN_REPLAY_RESULT_SCHEMA_VERSION,
        "status": "complete",
        "mode": "prospective_formal_simulation",
        "role": role,
        "clock_id": activation.clock_id,
        "clock_manifest_hash": str(activation.payload["clock_manifest_hash"]),
        "activation_manifest_hash": activation.activation_manifest_hash,
        "maturity_report_hash": maturity_report_hash,
        "model_artifact_hash": str(calibration_policy.payload["model_artifact_hash"]),
        "candidate_feature_manifest_hash": str(
            activation.payload["candidate_feature_manifest_hash"]
        ),
        "dataset_identity_hash": str(calibration_policy.payload["dataset_identity_hash"]),
        "calibration_policy_hash": calibration_policy.policy_hash,
        "evaluation_policy_hash": str(activation.payload["evaluation_policy_hash"]),
        "result_identity_hash": result_identity_hash,
        "replay_result_hash": replay_result_hash,
        "source_lineage_hash": source_lineage_hash,
        "outcome_row_count": outcome_row_count,
        "horizon_observation_counts": counts,
        "fit_called": False,
        "retrained": False,
        "post_outcome_method_selection": False,
        "teacher_future_targets_used": False,
        "same_day_advice_used": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    return {**body, "result_hash": payload_hash(body)}


def build_prospective_frozen_oos_evidence_package(
    *,
    activation: ProspectiveClockActivation,
    calibration_policy: ProspectiveCalibrationPolicy,
    maturity_report: Mapping[str, object],
    primary_replay: Mapping[str, object] | None,
    verification_replay: Mapping[str, object] | None,
    calibration_audit: Mapping[str, object] | None,
    psi_report: Mapping[str, object] | None,
    now: datetime,
) -> dict[str, object]:
    """建立 PFS-09 evidence/readiness package；缺件只變成 blockers。"""

    _validate_now(now)
    _validate_policy_binding(activation, calibration_policy)
    maturity_hash = _validate_maturity_report(maturity_report, activation=activation, now=now)
    blockers: list[str] = []
    primary_hash: str | None = None
    verification_hash: str | None = None
    replay_identity_hash: str | None = None
    if primary_replay is None:
        blockers.append("primary_replay_missing")
    else:
        try:
            primary = validate_prospective_frozen_oos_replay_result(
                primary_replay,
                activation=activation,
                calibration_policy=calibration_policy,
                expected_maturity_report_hash=maturity_hash,
            )
            primary_hash = str(primary["replay_result_hash"])
            replay_identity_hash = str(primary["result_identity_hash"])
        except ProspectiveFrozenOOSEvidenceError as error:
            blockers.append(f"primary_replay_invalid:{str(error).splitlines()[0]}")
    if verification_replay is None:
        blockers.append("verification_replay_missing")
    else:
        try:
            verification = validate_prospective_frozen_oos_replay_result(
                verification_replay,
                activation=activation,
                calibration_policy=calibration_policy,
                expected_maturity_report_hash=maturity_hash,
            )
            verification_hash = str(verification["replay_result_hash"])
            verification_identity = str(verification["result_identity_hash"])
            if replay_identity_hash is not None and verification_identity != replay_identity_hash:
                blockers.append("primary_verification_identity_mismatch")
            if primary_hash is not None and verification_hash != primary_hash:
                blockers.append("primary_verification_replay_hash_mismatch")
        except ProspectiveFrozenOOSEvidenceError as error:
            blockers.append(f"verification_replay_invalid:{str(error).splitlines()[0]}")
    calibration_hash: str | None = None
    calibration_quality = False
    if calibration_audit is None:
        blockers.append("calibration_audit_missing")
    else:
        calibration_hash, calibration_quality = _validate_calibration_audit(
            calibration_audit,
            activation=activation,
            calibration_policy=calibration_policy,
        )
        if not calibration_quality:
            blockers.append("calibration_quality_failed")
    psi_hash: str | None = None
    psi_quality = False
    if psi_report is None:
        blockers.append("psi_report_missing")
    else:
        psi_hash, psi_quality = _validate_psi_report(
            psi_report,
            activation=activation,
            calibration_policy=calibration_policy,
        )
        if not psi_quality:
            blockers.append("psi_quality_failed")
    normalized_blockers = sorted(set(blockers))
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_FROZEN_OOS_EVIDENCE_SCHEMA_VERSION,
        "status": "ready_for_formal_review" if not normalized_blockers else "waiting_for_frozen_oos_evidence",
        "mode": "prospective_formal_simulation",
        "capture_only": True,
        "clock_id": activation.clock_id,
        "clock_manifest_hash": str(activation.payload["clock_manifest_hash"]),
        "activation_manifest_hash": activation.activation_manifest_hash,
        "maturity_report_hash": maturity_hash,
        "candidate_model_hash": str(calibration_policy.payload["model_artifact_hash"]),
        "candidate_feature_manifest_hash": str(
            activation.payload["candidate_feature_manifest_hash"]
        ),
        "dataset_identity_hash": str(calibration_policy.payload["dataset_identity_hash"]),
        "calibration_policy_hash": calibration_policy.policy_hash,
        "evaluation_policy_hash": str(activation.payload["evaluation_policy_hash"]),
        "primary_replay_result_hash": primary_hash,
        "verification_replay_result_hash": verification_hash,
        "replay_identity_hash": replay_identity_hash,
        "calibration_audit_hash": calibration_hash,
        "calibration_quality_pass": calibration_quality,
        "psi_report_hash": psi_hash,
        "psi_quality_pass": psi_quality,
        "blockers": normalized_blockers,
        "replay_fit_called": False,
        "retrained": False,
        "post_outcome_method_selection": False,
        "replay_used": True,
        "backfilled": False,
        "synthetic_outcomes_used": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    package = {**body, "package_hash": payload_hash(body)}
    validate_prospective_frozen_oos_evidence_package(
        package,
        activation=activation,
        calibration_policy=calibration_policy,
        maturity_report=maturity_report,
        now=now,
    )
    return package


def validate_prospective_frozen_oos_replay_result(
    result: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    calibration_policy: ProspectiveCalibrationPolicy,
    expected_maturity_report_hash: str,
) -> Mapping[str, object]:
    """驗證單一 replay result 的 frozen identity 與 no-fit flags。"""

    if set(result) != _REPLAY_RESULT_FIELDS:
        raise ProspectiveFrozenOOSEvidenceError("replay result fields are invalid")
    _validate_policy_binding(activation, calibration_policy)
    if result.get("schema_version") != PROSPECTIVE_FROZEN_REPLAY_RESULT_SCHEMA_VERSION:
        raise ProspectiveFrozenOOSEvidenceError("replay result schema_version is invalid")
    if result.get("status") != "complete" or result.get("mode") != "prospective_formal_simulation":
        raise ProspectiveFrozenOOSEvidenceError("replay result status/mode is invalid")
    if result.get("role") not in {"primary", "verification"}:
        raise ProspectiveFrozenOOSEvidenceError("replay result role is invalid")
    for field_name, expected in (
        ("clock_id", activation.clock_id),
        ("clock_manifest_hash", activation.payload["clock_manifest_hash"]),
        ("activation_manifest_hash", activation.activation_manifest_hash),
        ("maturity_report_hash", expected_maturity_report_hash),
        ("model_artifact_hash", calibration_policy.payload["model_artifact_hash"]),
        (
            "candidate_feature_manifest_hash",
            activation.payload["candidate_feature_manifest_hash"],
        ),
        ("dataset_identity_hash", calibration_policy.payload["dataset_identity_hash"]),
        ("calibration_policy_hash", calibration_policy.policy_hash),
        ("evaluation_policy_hash", activation.payload["evaluation_policy_hash"]),
        ("fit_called", False),
        ("retrained", False),
        ("post_outcome_method_selection", False),
        ("teacher_future_targets_used", False),
        ("same_day_advice_used", False),
        ("formal_oos_allowed", False),
        ("production_blend_alpha_bp", 0),
        ("broker_order_allowed", False),
    ):
        if result.get(field_name) is not expected if isinstance(expected, bool) else result.get(field_name) != expected:
            raise ProspectiveFrozenOOSEvidenceError(
                f"replay result {field_name} is unsafe or unbound"
            )
    for field_name in ("result_identity_hash", "replay_result_hash", "source_lineage_hash"):
        _required_hash(result.get(field_name), field_name)
    _required_positive_int(result.get("outcome_row_count"), "outcome_row_count")
    counts = result.get("horizon_observation_counts")
    if not isinstance(counts, Mapping):
        raise ProspectiveFrozenOOSEvidenceError("horizon_observation_counts must be an object")
    _normalize_horizon_counts(counts)
    supplied = _required_hash(result.get("result_hash"), "result_hash")
    body = dict(result)
    body.pop("result_hash", None)
    if payload_hash(body) != supplied:
        raise ProspectiveFrozenOOSEvidenceError("replay result hash mismatch")
    return result


def validate_prospective_frozen_oos_evidence_package(
    package: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    calibration_policy: ProspectiveCalibrationPolicy,
    maturity_report: Mapping[str, object],
    now: datetime,
) -> None:
    """驗證 PFS-09 package 的 identity、blocker 與 fail-closed flags。"""

    if set(package) != _EVIDENCE_FIELDS:
        raise ProspectiveFrozenOOSEvidenceError("frozen OOS evidence fields are invalid")
    _validate_policy_binding(activation, calibration_policy)
    maturity_hash = _validate_maturity_report(maturity_report, activation=activation, now=now)
    for field_name, expected in (
        ("schema_version", PROSPECTIVE_FROZEN_OOS_EVIDENCE_SCHEMA_VERSION),
        ("mode", "prospective_formal_simulation"),
        ("capture_only", True),
        ("clock_id", activation.clock_id),
        ("clock_manifest_hash", activation.payload["clock_manifest_hash"]),
        ("activation_manifest_hash", activation.activation_manifest_hash),
        ("maturity_report_hash", maturity_hash),
        ("candidate_model_hash", calibration_policy.payload["model_artifact_hash"]),
        (
            "candidate_feature_manifest_hash",
            activation.payload["candidate_feature_manifest_hash"],
        ),
        ("dataset_identity_hash", calibration_policy.payload["dataset_identity_hash"]),
        ("calibration_policy_hash", calibration_policy.policy_hash),
        ("evaluation_policy_hash", activation.payload["evaluation_policy_hash"]),
        ("replay_fit_called", False),
        ("retrained", False),
        ("post_outcome_method_selection", False),
        ("replay_used", True),
        ("backfilled", False),
        ("synthetic_outcomes_used", False),
        ("formal_oos_allowed", False),
        ("production_blend_alpha_bp", 0),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
        ("secret_values_emitted", False),
    ):
        if package.get(field_name) is not expected if isinstance(expected, bool) else package.get(field_name) != expected:
            raise ProspectiveFrozenOOSEvidenceError(
                f"frozen OOS evidence {field_name} is unsafe or unbound"
            )
    status = package.get("status")
    blockers = package.get("blockers")
    if status not in {"ready_for_formal_review", "waiting_for_frozen_oos_evidence"}:
        raise ProspectiveFrozenOOSEvidenceError("frozen OOS evidence status is invalid")
    if not isinstance(blockers, list) or blockers != sorted(set(blockers)):
        raise ProspectiveFrozenOOSEvidenceError("frozen OOS evidence blockers are invalid")
    if (status == "ready_for_formal_review") != (not blockers):
        raise ProspectiveFrozenOOSEvidenceError("frozen OOS evidence status/blockers mismatch")
    for field_name in (
        "primary_replay_result_hash",
        "verification_replay_result_hash",
        "replay_identity_hash",
        "calibration_audit_hash",
        "psi_report_hash",
    ):
        value = package.get(field_name)
        if value is not None:
            _required_hash(value, field_name)
    if not isinstance(package.get("calibration_quality_pass"), bool) or not isinstance(
        package.get("psi_quality_pass"), bool
    ):
        raise ProspectiveFrozenOOSEvidenceError("frozen OOS quality flags are invalid")
    _validate_hash_shape(package, "package_hash", "frozen OOS evidence package")


def write_immutable_frozen_oos_evidence_package(
    output_path: Path,
    package: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 PFS-09 package。"""

    _validate_hash_shape(package, "package_hash", "frozen OOS evidence package")
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveFrozenOOSEvidenceError("evidence output parent must exist")
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(package)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveFrozenOOSEvidenceError("evidence output already exists") from error
    return file_sha256(output)


def _validate_maturity_report(
    report: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    now: datetime,
) -> str:
    required = {
        "schema_version", "status", "mode", "capture_only", "clock_id",
        "clock_manifest_hash", "activation_manifest_hash", "observed_capture_dates",
        "observed_day_count", "minimum_shadow_days",
        "minimum_matured_observations_per_horizon", "observation_hashes",
        "horizon_maturity", "blockers", "maturity_gate_pass", "replay_used",
        "backfilled", "synthetic_outcomes_used", "formal_oos_allowed",
        "production_blend_alpha_bp", "promotion_eligible", "broker_order_allowed",
        "secret_values_emitted", "report_hash",
    }
    if set(report) != required:
        raise ProspectiveFrozenOOSEvidenceError("maturity report fields are invalid")
    if report.get("schema_version") != "prospective-formal-shadow-maturity-report.v1":
        raise ProspectiveFrozenOOSEvidenceError("maturity report schema_version is invalid")
    for field_name, expected in (
        ("status", "maturity_gate_ready_shadow_only"),
        ("mode", "prospective_formal_simulation"),
        ("capture_only", True),
        ("clock_id", activation.clock_id),
        ("clock_manifest_hash", activation.payload["clock_manifest_hash"]),
        ("activation_manifest_hash", activation.activation_manifest_hash),
        ("minimum_shadow_days", MINIMUM_SHADOW_DAYS),
        (
            "minimum_matured_observations_per_horizon",
            MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON,
        ),
        ("maturity_gate_pass", True),
        ("replay_used", False),
        ("backfilled", False),
        ("synthetic_outcomes_used", False),
        ("formal_oos_allowed", False),
        ("production_blend_alpha_bp", 0),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
        ("secret_values_emitted", False),
    ):
        if report.get(field_name) is not expected if isinstance(expected, bool) else report.get(field_name) != expected:
            raise ProspectiveFrozenOOSEvidenceError(
                f"maturity report {field_name} is unsafe"
            )
    dates = report.get("observed_capture_dates")
    if not isinstance(dates, list) or len(dates) < MINIMUM_SHADOW_DAYS:
        raise ProspectiveFrozenOOSEvidenceError("maturity report shadow days are insufficient")
    now_day = _parse_now(now).astimezone(TAIPEI_TIMEZONE).date()
    for item in dates:
        parsed = _parse_date(item, "observed_capture_date")
        if parsed < activation.activation_trading_day or parsed > now_day:
            raise ProspectiveFrozenOOSEvidenceError("maturity report date is outside clock")
    maturity = report.get("horizon_maturity")
    if not isinstance(maturity, Mapping):
        raise ProspectiveFrozenOOSEvidenceError("maturity report horizon_maturity is invalid")
    for horizon in (5, 10, 20, 60):
        detail = maturity.get(str(horizon))
        if not isinstance(detail, Mapping):
            raise ProspectiveFrozenOOSEvidenceError("maturity report horizon is missing")
        count = detail.get("matured_observation_count")
        if not isinstance(count, int) or count < MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON:
            raise ProspectiveFrozenOOSEvidenceError("maturity report horizon is insufficient")
        classes = detail.get("rebalance_worthwhile_class_counts")
        if not isinstance(classes, Mapping) or not isinstance(classes.get("0"), int) or not isinstance(classes.get("1"), int) or classes["0"] <= 0 or classes["1"] <= 0:
            raise ProspectiveFrozenOOSEvidenceError("maturity report class coverage is incomplete")
    supplied = _required_hash(report.get("report_hash"), "report_hash")
    body = dict(report)
    body.pop("report_hash", None)
    if payload_hash(body) != supplied:
        raise ProspectiveFrozenOOSEvidenceError("maturity report hash mismatch")
    return supplied


def _validate_calibration_audit(
    audit: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    calibration_policy: ProspectiveCalibrationPolicy,
) -> tuple[str, bool]:
    if audit.get("schema_version") != PROSPECTIVE_CALIBRATION_AUDIT_SCHEMA_VERSION:
        raise ProspectiveFrozenOOSEvidenceError("calibration audit schema_version is invalid")
    for field_name, expected in (
        ("policy_hash", calibration_policy.policy_hash),
        ("clock_id", activation.clock_id),
        ("model_artifact_hash", calibration_policy.payload["model_artifact_hash"]),
        ("dataset_identity_hash", calibration_policy.payload["dataset_identity_hash"]),
        ("promotion_pass", False),
        ("promotion_eligible", False),
        ("formal_oos_allowed", False),
        ("production_blend_alpha_bp", 0),
        ("broker_order_allowed", False),
        ("post_outcome_method_selection", "forbidden"),
        ("secret_values_emitted", False),
    ):
        if audit.get(field_name) is not expected if isinstance(expected, bool) else audit.get(field_name) != expected:
            raise ProspectiveFrozenOOSEvidenceError("calibration audit is unbound or unsafe")
    quality = audit.get("quality_pass")
    if not isinstance(quality, bool):
        raise ProspectiveFrozenOOSEvidenceError("calibration audit quality_pass is invalid")
    supplied = _required_hash(audit.get("audit_hash"), "audit_hash")
    body = dict(audit)
    body.pop("audit_hash", None)
    if payload_hash(body) != supplied:
        raise ProspectiveFrozenOOSEvidenceError("calibration audit hash mismatch")
    return supplied, quality


def _validate_psi_report(
    report: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    calibration_policy: ProspectiveCalibrationPolicy,
) -> tuple[str, bool]:
    if set(report) != _PSI_FIELDS:
        raise ProspectiveFrozenOOSEvidenceError("PSI report fields are invalid")
    if report.get("schema_version") != PROSPECTIVE_PSI_REPORT_SCHEMA_VERSION:
        raise ProspectiveFrozenOOSEvidenceError("PSI report schema_version is invalid")
    for field_name, expected in (
        ("clock_id", activation.clock_id),
        ("model_artifact_hash", calibration_policy.payload["model_artifact_hash"]),
        ("dataset_identity_hash", calibration_policy.payload["dataset_identity_hash"]),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
    ):
        if report.get(field_name) is not expected if isinstance(expected, bool) else report.get(field_name) != expected:
            raise ProspectiveFrozenOOSEvidenceError("PSI report is unbound or unsafe")
    _required_hash(report.get("reference_identity_hash"), "reference_identity_hash")
    _required_positive_int(report.get("feature_count"), "feature_count")
    _required_nonnegative_int(report.get("max_psi_bp"), "max_psi_bp")
    _required_nonnegative_int(report.get("psi_threshold_bp"), "psi_threshold_bp")
    quality = report.get("quality_pass")
    if not isinstance(quality, bool):
        raise ProspectiveFrozenOOSEvidenceError("PSI quality_pass is invalid")
    if quality and _required_nonnegative_int(
        report.get("max_psi_bp"), "max_psi_bp"
    ) > _required_nonnegative_int(
        report.get("psi_threshold_bp"), "psi_threshold_bp"
    ):
        raise ProspectiveFrozenOOSEvidenceError("PSI quality_pass contradicts threshold")
    supplied = _required_hash(report.get("report_hash"), "report_hash")
    body = dict(report)
    body.pop("report_hash", None)
    if payload_hash(body) != supplied:
        raise ProspectiveFrozenOOSEvidenceError("PSI report hash mismatch")
    return supplied, quality


def _validate_policy_binding(
    activation: ProspectiveClockActivation,
    policy: ProspectiveCalibrationPolicy,
) -> None:
    # PFS-07 activation already validated the full clock.  Re-check the three
    # non-cyclic policy identities here without manufacturing a fake clock.
    if policy.payload.get("clock_id") != activation.clock_id:
        raise ProspectiveFrozenOOSEvidenceError("calibration policy clock_id mismatch")
    if policy.payload.get("model_artifact_hash") != activation.payload.get("candidate_model_hash"):
        raise ProspectiveFrozenOOSEvidenceError("calibration policy model identity mismatch")
    if policy.policy_hash != activation.payload.get("calibration_policy_hash"):
        raise ProspectiveFrozenOOSEvidenceError("calibration policy hash mismatch")


def _normalize_horizon_counts(value: Mapping[str, int]) -> dict[str, int]:
    if set(value) != {str(horizon) for horizon in FROZEN_OOS_HORIZONS}:
        raise ProspectiveFrozenOOSEvidenceError("horizon observation counts are invalid")
    result: dict[str, int] = {}
    for key in sorted(value):
        count = value[key]
        _required_positive_int(count, f"horizon_count_{key}")
        if count < MINIMUM_MATURED_OBSERVATIONS_PER_HORIZON:
            raise ProspectiveFrozenOOSEvidenceError("horizon observation count is insufficient")
        result[key] = count
    return result


def _validate_hash_shape(value: Mapping[str, object], field_name: str, label: str) -> None:
    supplied = _required_hash(value.get(field_name), field_name)
    body = dict(value)
    body.pop(field_name, None)
    if payload_hash(body) != supplied:
        raise ProspectiveFrozenOOSEvidenceError(f"{label} hash mismatch")


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ProspectiveFrozenOOSEvidenceError(f"{field_name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ProspectiveFrozenOOSEvidenceError(f"{field_name} is invalid") from error
    return parsed


def _parse_now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveFrozenOOSEvidenceError("now must include timezone")
    return value


def _validate_now(value: datetime) -> None:
    _parse_now(value)


def _required_hash(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in value[7:]
    ):
        raise ProspectiveFrozenOOSEvidenceError(f"{field_name} must be sha256")
    return value


def _required_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProspectiveFrozenOOSEvidenceError(f"{field_name} must be positive integer")
    return value


def _required_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProspectiveFrozenOOSEvidenceError(f"{field_name} must be nonnegative integer")
    return value
