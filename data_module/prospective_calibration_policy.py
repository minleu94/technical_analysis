"""Prospective formal inference-level calibration policy and audit.

這個模組把 calibration 的方法、fold lineage、horizon aggregation 與
``rebalance_worthwhile`` class coverage 固定成可 hash 驗證的 policy。它不 fit
模型、不修改現有 OOC／inference artifact，也不把 audit 結果接成 production
calibrator；所有輸出都維持 shadow-only、alpha=0、broker disabled。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    canonical_json,
    file_sha256,
)


PROSPECTIVE_CALIBRATION_POLICY_SCHEMA_VERSION = (
    "prospective-formal-inference-calibration-policy.v1"
)
PROSPECTIVE_CALIBRATION_AUDIT_SCHEMA_VERSION = (
    "prospective-formal-inference-calibration-audit.v1"
)
CALIBRATION_HORIZONS = (5, 10, 20, 60)
CALIBRATION_METHODS = ("identity", "isotonic_integer_bp")
PRIMARY_CALIBRATION_METHOD = "isotonic_integer_bp"
CALIBRATION_ECE_THRESHOLD_BP = 500
MINIMUM_PRIOR_FOLD_COUNT = 2

_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "formal_source_only",
        "research_only",
        "formal_consumer_compatible",
        "promotion_eligible",
        "mode",
        "policy_id",
        "clock_id",
        "model_artifact_hash",
        "dataset_identity_hash",
        "horizons_trading_sessions",
        "methods",
        "primary_method",
        "fit_boundary",
        "minimum_prior_fold_count",
        "aggregation",
        "ece_threshold_bp",
        "require_primary_not_worse",
        "require_both_classes_per_horizon",
        "rebalance_head",
        "require_rebalance_both_classes",
        "post_outcome_method_selection",
        "formal_oos_allowed",
        "production_blend_alpha_bp",
        "broker_order_allowed",
    }
)
_RECORD_FIELDS = frozenset(
    {
        "policy_hash",
        "fold_id",
        "fold_rank",
        "fit_fold_ids",
        "fit_fold_ranks",
        "horizon_trading_days",
        "sample_count",
        "class_counts",
        "rebalance_worthwhile_class_counts",
        "identity_metrics",
        "isotonic_metrics",
        "model_artifact_hash",
        "dataset_identity_hash",
        "inference_identity_hash",
        "source_lineage_hash",
    }
)


class ProspectiveCalibrationError(ValueError):
    """Prospective calibration policy／audit 不符合 strict contract。"""


@dataclass(frozen=True)
class ProspectiveCalibrationPolicy:
    """Immutable policy payload and its canonical hash."""

    payload: Mapping[str, object]
    policy_hash: str

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


@dataclass(frozen=True)
class ProspectiveCalibrationPolicyPublication:
    policy_path: Path
    policy_hash: str
    policy_file_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PROSPECTIVE_CALIBRATION_POLICY_SCHEMA_VERSION,
            "status": "accepted",
            "policy_path": str(self.policy_path),
            "policy_hash": self.policy_hash,
            "policy_file_hash": self.policy_file_hash,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
            "secret_values_emitted": False,
        }


def build_prospective_calibration_policy(
    *,
    policy_id: str,
    clock_id: str,
    model_artifact_hash: str,
    dataset_identity_hash: str,
) -> ProspectiveCalibrationPolicy:
    """建立預註冊 inference-level calibration policy。

    policy hash 不包含 clock manifest hash，避免 clock 的
    ``calibration_policy_hash`` 與 clock 自身 manifest hash 形成循環；clock
    binding 由 :func:`validate_policy_against_clock` 以 clock id／policy hash
    重新驗證。
    """

    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_CALIBRATION_POLICY_SCHEMA_VERSION,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "mode": "prospective_formal_simulation",
        "policy_id": _required_text(policy_id, "policy_id"),
        "clock_id": _required_text(clock_id, "clock_id"),
        "model_artifact_hash": _required_hash(
            model_artifact_hash, "model_artifact_hash"
        ),
        "dataset_identity_hash": _required_hash(
            dataset_identity_hash, "dataset_identity_hash"
        ),
        "horizons_trading_sessions": list(CALIBRATION_HORIZONS),
        "methods": list(CALIBRATION_METHODS),
        "primary_method": PRIMARY_CALIBRATION_METHOD,
        "fit_boundary": "prior_validation_folds_only",
        "minimum_prior_fold_count": MINIMUM_PRIOR_FOLD_COUNT,
        "aggregation": "per_horizon_then_conservative_max",
        "ece_threshold_bp": CALIBRATION_ECE_THRESHOLD_BP,
        "require_primary_not_worse": True,
        "require_both_classes_per_horizon": True,
        "rebalance_head": "rebalance_worthwhile",
        "require_rebalance_both_classes": True,
        "post_outcome_method_selection": "forbidden",
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    policy_hash = _payload_hash(body)
    payload = {**body, "policy_hash": policy_hash}
    return ProspectiveCalibrationPolicy(payload=payload, policy_hash=policy_hash)


def publish_prospective_calibration_policy(
    policy: ProspectiveCalibrationPolicy,
    output_path: Path,
) -> ProspectiveCalibrationPolicyPublication:
    """以 create-only bytes 保存 policy；parent 必須已存在。"""

    validated = validate_prospective_calibration_policy(policy.to_dict())
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveCalibrationError(
            "calibration policy output parent directory must already exist"
        )
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(validated.to_dict()).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveCalibrationError(
            "calibration policy output already exists"
        ) from error
    return ProspectiveCalibrationPolicyPublication(
        policy_path=output,
        policy_hash=validated.policy_hash,
        policy_file_hash=file_sha256(output),
    )


def load_prospective_calibration_policy(
    path: Path,
) -> ProspectiveCalibrationPolicy:
    """唯讀載入 canonical policy JSON。"""

    resolved = path.expanduser().resolve()
    try:
        raw_text = resolved.read_text(encoding="utf-8")
        raw: Any = json.loads(
            raw_text,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except FileNotFoundError as error:
        raise ProspectiveCalibrationError("calibration policy is missing") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ProspectiveCalibrationError("calibration policy is unreadable") from error
    if not isinstance(raw, Mapping):
        raise ProspectiveCalibrationError("calibration policy root must be an object")
    if canonical_json(raw) != raw_text:
        raise ProspectiveCalibrationError("calibration policy must use canonical JSON")
    return validate_prospective_calibration_policy(raw)


def validate_prospective_calibration_policy(
    value: Mapping[str, object],
) -> ProspectiveCalibrationPolicy:
    """重新計算 canonical hash 並驗證 policy flags／方法邊界。"""

    if not isinstance(value, Mapping):
        raise ProspectiveCalibrationError("calibration policy must be an object")
    if set(value) != _POLICY_FIELDS | {"policy_hash"}:
        raise ProspectiveCalibrationError("calibration policy fields are invalid")
    if value.get("schema_version") != PROSPECTIVE_CALIBRATION_POLICY_SCHEMA_VERSION:
        raise ProspectiveCalibrationError("calibration policy schema_version is invalid")
    if value.get("status") != "complete":
        raise ProspectiveCalibrationError("calibration policy is incomplete")
    for field_name, expected in (
        ("formal_source_only", True),
        ("research_only", False),
        ("formal_consumer_compatible", True),
        ("promotion_eligible", False),
        ("formal_oos_allowed", False),
        ("broker_order_allowed", False),
        ("require_primary_not_worse", True),
        ("require_both_classes_per_horizon", True),
        ("require_rebalance_both_classes", True),
    ):
        if value.get(field_name) is not expected:
            raise ProspectiveCalibrationError(
                f"calibration policy {field_name} is invalid"
            )
    if value.get("mode") != "prospective_formal_simulation":
        raise ProspectiveCalibrationError("calibration policy mode is invalid")
    _required_text(value.get("policy_id"), "policy_id")
    _required_text(value.get("clock_id"), "clock_id")
    _required_hash(value.get("model_artifact_hash"), "model_artifact_hash")
    _required_hash(value.get("dataset_identity_hash"), "dataset_identity_hash")
    if value.get("horizons_trading_sessions") != list(CALIBRATION_HORIZONS):
        raise ProspectiveCalibrationError("calibration policy horizons are invalid")
    if value.get("methods") != list(CALIBRATION_METHODS):
        raise ProspectiveCalibrationError("calibration policy methods are invalid")
    if value.get("primary_method") != PRIMARY_CALIBRATION_METHOD:
        raise ProspectiveCalibrationError("calibration policy primary method is invalid")
    if value.get("fit_boundary") != "prior_validation_folds_only":
        raise ProspectiveCalibrationError("calibration policy fit boundary is invalid")
    if value.get("minimum_prior_fold_count") != MINIMUM_PRIOR_FOLD_COUNT:
        raise ProspectiveCalibrationError("calibration policy prior fold minimum is invalid")
    if value.get("aggregation") != "per_horizon_then_conservative_max":
        raise ProspectiveCalibrationError("calibration policy aggregation is invalid")
    if value.get("ece_threshold_bp") != CALIBRATION_ECE_THRESHOLD_BP:
        raise ProspectiveCalibrationError("calibration policy ECE threshold is invalid")
    if value.get("rebalance_head") != "rebalance_worthwhile":
        raise ProspectiveCalibrationError("calibration policy rebalance head is invalid")
    if value.get("post_outcome_method_selection") != "forbidden":
        raise ProspectiveCalibrationError(
            "post-outcome calibration method selection is forbidden"
        )
    if value.get("production_blend_alpha_bp") != 0:
        raise ProspectiveCalibrationError(
            "calibration policy production alpha must be zero"
        )
    supplied_hash = _required_hash(value.get("policy_hash"), "policy_hash")
    body = dict(value)
    body.pop("policy_hash", None)
    if _payload_hash(body) != supplied_hash:
        raise ProspectiveCalibrationError("calibration policy hash mismatch")
    return ProspectiveCalibrationPolicy(payload=dict(value), policy_hash=supplied_hash)


def validate_policy_against_clock(
    policy: ProspectiveCalibrationPolicy,
    clock: ProspectiveFormalClock,
) -> None:
    """確認 policy hash／clock id／model identity 與 frozen clock 一致。"""

    validated = validate_prospective_calibration_policy(policy.to_dict())
    if validated.payload["clock_id"] != clock.clock_id:
        raise ProspectiveCalibrationError("calibration policy clock_id mismatch")
    if clock.payload.get("calibration_policy_hash") != validated.policy_hash:
        raise ProspectiveCalibrationError(
            "clock calibration_policy_hash does not match policy"
        )
    if clock.payload.get("candidate_model_hash") != validated.payload[
        "model_artifact_hash"
    ]:
        raise ProspectiveCalibrationError(
            "calibration policy model_artifact_hash does not match clock"
        )


def audit_prospective_inference_calibration(
    *,
    policy: ProspectiveCalibrationPolicy | Mapping[str, object],
    fold_records: Sequence[Mapping[str, object]],
    clock: ProspectiveFormalClock | None = None,
    expected_inference_identity_hash: str | None = None,
) -> dict[str, object]:
    """稽核 inference-level identity／isotonic metrics 與 fold lineage。

    ``fold_records`` 是 inference adapter 提供的已量化結果，不在此處重新 fit
    模型。每個 target fold 必須攜帶完整 zero-based prior fold ranks；這讓
    audit 能拒絕把 target fold 自身或未來 fold 帶入 calibrator fit。
    """

    validated_policy = (
        policy
        if isinstance(policy, ProspectiveCalibrationPolicy)
        else validate_prospective_calibration_policy(policy)
    )
    validate_prospective_calibration_policy(validated_policy.to_dict())
    if clock is not None:
        validate_policy_against_clock(validated_policy, clock)
    expected_inference = None
    if expected_inference_identity_hash is not None:
        expected_inference = _required_hash(
            expected_inference_identity_hash,
            "expected_inference_identity_hash",
        )
    if not isinstance(fold_records, (list, tuple)) or not fold_records:
        raise ProspectiveCalibrationError("calibration fold records are required")

    normalized: list[dict[str, object]] = []
    for record in fold_records:
        normalized.append(
            _normalize_fold_record(
                record,
                policy=validated_policy,
                expected_inference_identity_hash=expected_inference,
            )
        )

    by_horizon: dict[int, list[dict[str, object]]] = {
        horizon: [] for horizon in CALIBRATION_HORIZONS
    }
    inference_ids: set[str] = set()
    for record in normalized:
        horizon = _required_int(record["horizon_trading_days"], "horizon")
        by_horizon[horizon].append(record)
        inference_ids.add(str(record["inference_identity_hash"]))
    blockers: set[str] = set()
    horizon_reports: list[dict[str, object]] = []
    aggregate_methods: dict[str, dict[str, int]] = {
        method: {"ece_bp": 0, "brier_bp": 0}
        for method in CALIBRATION_METHODS
    }

    for horizon in CALIBRATION_HORIZONS:
        records = sorted(
            by_horizon[horizon],
            key=lambda item: _required_int(item["fold_rank"], "fold_rank"),
        )
        report = _audit_horizon(
            horizon=horizon,
            records=records,
            policy=validated_policy,
            blockers=blockers,
        )
        horizon_reports.append(report)
        report_methods = cast(
            Mapping[str, Mapping[str, object]],
            report["methods"],
        )
        for method in CALIBRATION_METHODS:
            metrics = report_methods[method]
            aggregate_methods[method]["ece_bp"] = max(
                aggregate_methods[method]["ece_bp"],
                _required_int(metrics["ece_bp"], f"{method}.ece_bp"),
            )
            aggregate_methods[method]["brier_bp"] = max(
                aggregate_methods[method]["brier_bp"],
                _required_int(metrics["brier_bp"], f"{method}.brier_bp"),
            )

    if len(inference_ids) != 1:
        blockers.add("multiple_inference_identities")
    primary = aggregate_methods[PRIMARY_CALIBRATION_METHOD]
    identity = aggregate_methods["identity"]
    if primary["ece_bp"] > CALIBRATION_ECE_THRESHOLD_BP:
        blockers.add("primary_calibration_ece_threshold_failed")
    if validated_policy.payload["require_primary_not_worse"] is True:
        if primary["ece_bp"] > identity["ece_bp"]:
            blockers.add("primary_calibration_ece_not_improved")
        if primary["brier_bp"] > identity["brier_bp"]:
            blockers.add("primary_calibration_brier_not_improved")

    quality_pass = not blockers
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_CALIBRATION_AUDIT_SCHEMA_VERSION,
        "status": "complete_shadow_diagnostic",
        "policy_id": validated_policy.payload["policy_id"],
        "policy_hash": validated_policy.policy_hash,
        "clock_id": validated_policy.payload["clock_id"],
        "model_artifact_hash": validated_policy.payload["model_artifact_hash"],
        "dataset_identity_hash": validated_policy.payload["dataset_identity_hash"],
        "inference_identity_hash": (
            next(iter(inference_ids)) if len(inference_ids) == 1 else None
        ),
        "primary_method": PRIMARY_CALIBRATION_METHOD,
        "methods": aggregate_methods,
        "horizons": horizon_reports,
        "quality_pass": quality_pass,
        "promotion_pass": False,
        "promotion_eligible": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "fit_boundary": "prior_validation_folds_only",
        "post_outcome_method_selection": "forbidden",
        "blockers": sorted(blockers),
        "secret_values_emitted": False,
    }
    return {**body, "audit_hash": _payload_hash(body)}


def write_immutable_calibration_audit(
    output_path: Path,
    audit: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 shadow audit。"""

    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveCalibrationError(
            "calibration audit output parent directory must already exist"
        )
    body = dict(audit)
    audit_hash = _required_hash(body.get("audit_hash"), "audit_hash")
    without_hash = dict(body)
    without_hash.pop("audit_hash", None)
    if _payload_hash(without_hash) != audit_hash:
        raise ProspectiveCalibrationError("calibration audit hash mismatch")
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(body).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveCalibrationError(
            "calibration audit output already exists"
        ) from error
    return file_sha256(output)


def _audit_horizon(
    *,
    horizon: int,
    records: Sequence[Mapping[str, object]],
    policy: ProspectiveCalibrationPolicy,
    blockers: set[str],
) -> dict[str, object]:
    if not records:
        blockers.add(f"calibration_horizon_missing:h{horizon}")
        return {
            "horizon_trading_days": horizon,
            "fold_count": 0,
            "sample_count": 0,
            "class_counts": {"0": 0, "1": 0},
            "rebalance_worthwhile_class_counts": {"0": 0, "1": 0},
            "methods": {
                method: {"ece_bp": 0, "brier_bp": 0}
                for method in CALIBRATION_METHODS
            },
            "quality_pass": False,
        }
    ranks = [_required_int(record["fold_rank"], "fold_rank") for record in records]
    if len(set(ranks)) != len(ranks):
        blockers.add(f"duplicate_calibration_fold_rank:h{horizon}")
    expected_ranks = tuple(range(MINIMUM_PRIOR_FOLD_COUNT, max(ranks) + 1))
    if tuple(ranks) != expected_ranks:
        blockers.add(f"calibration_fold_ranks_not_contiguous:h{horizon}")
    fold_ids = [str(record["fold_id"]) for record in records]
    if len(set(fold_ids)) != len(fold_ids):
        blockers.add(f"duplicate_calibration_fold_id:h{horizon}")

    class_counts = {"0": 0, "1": 0}
    rebalance_counts = {"0": 0, "1": 0}
    methods: dict[str, dict[str, int]] = {
        method: {"ece_bp": 0, "brier_bp": 0}
        for method in CALIBRATION_METHODS
    }
    sample_count = 0
    for record in records:
        rank = _required_int(record["fold_rank"], "fold_rank")
        fit_ids = _required_str_list(record["fit_fold_ids"], "fit_fold_ids")
        fit_ranks = _required_int_list(record["fit_fold_ranks"], "fit_fold_ranks")
        if len(fit_ids) != len(fit_ranks) or len(fit_ranks) < MINIMUM_PRIOR_FOLD_COUNT:
            blockers.add(f"calibration_prior_fold_count_failed:h{horizon}:f{rank}")
        if tuple(fit_ranks) != tuple(range(rank)):
            blockers.add(f"calibration_fit_boundary_failed:h{horizon}:f{rank}")
        if len(set(fit_ids)) != len(fit_ids):
            blockers.add(f"duplicate_calibration_fit_fold_id:h{horizon}:f{rank}")
        for key in ("0", "1"):
            class_counts[key] += _required_nonnegative_int(
                cast(Mapping[str, object], record["class_counts"])[key],
                f"class_counts[{key}]",
            )
            rebalance_counts[key] += _required_nonnegative_int(
                cast(Mapping[str, object], record["rebalance_worthwhile_class_counts"])[key],
                f"rebalance_worthwhile_class_counts[{key}]",
            )
        sample_count += _required_int(record["sample_count"], "sample_count")
        for method in CALIBRATION_METHODS:
            metrics_field = (
                "identity_metrics" if method == "identity" else "isotonic_metrics"
            )
            metrics = cast(Mapping[str, object], record[metrics_field])
            methods[method]["ece_bp"] = max(
                methods[method]["ece_bp"],
                _required_int(metrics["ece_bp"], f"{method}.ece_bp"),
            )
            methods[method]["brier_bp"] = max(
                methods[method]["brier_bp"],
                _required_int(metrics["brier_bp"], f"{method}.brier_bp"),
            )
    if class_counts["0"] == 0 or class_counts["1"] == 0:
        blockers.add(f"calibration_class_coverage_missing:h{horizon}")
    if rebalance_counts["0"] == 0 or rebalance_counts["1"] == 0:
        blockers.add(f"rebalance_worthwhile_class_coverage_missing:h{horizon}")
    primary = methods[PRIMARY_CALIBRATION_METHOD]
    identity = methods["identity"]
    horizon_quality = (
        primary["ece_bp"] <= CALIBRATION_ECE_THRESHOLD_BP
        and primary["ece_bp"] <= identity["ece_bp"]
        and primary["brier_bp"] <= identity["brier_bp"]
        and class_counts["0"] > 0
        and class_counts["1"] > 0
        and rebalance_counts["0"] > 0
        and rebalance_counts["1"] > 0
    )
    if primary["ece_bp"] > CALIBRATION_ECE_THRESHOLD_BP:
        blockers.add(f"primary_calibration_ece_threshold_failed:h{horizon}")
    if primary["ece_bp"] > identity["ece_bp"]:
        blockers.add(f"primary_calibration_ece_not_improved:h{horizon}")
    if primary["brier_bp"] > identity["brier_bp"]:
        blockers.add(f"primary_calibration_brier_not_improved:h{horizon}")
    return {
        "horizon_trading_days": horizon,
        "fold_count": len(records),
        "sample_count": sample_count,
        "class_counts": class_counts,
        "rebalance_worthwhile_class_counts": rebalance_counts,
        "methods": methods,
        "quality_pass": horizon_quality,
    }


def _normalize_fold_record(
    value: Mapping[str, object],
    *,
    policy: ProspectiveCalibrationPolicy,
    expected_inference_identity_hash: str | None,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS:
        raise ProspectiveCalibrationError("calibration fold record fields are invalid")
    if value.get("policy_hash") != policy.policy_hash:
        raise ProspectiveCalibrationError("calibration fold policy hash mismatch")
    fold_id = _required_text(value.get("fold_id"), "fold_id")
    fold_rank = _required_nonnegative_int(value.get("fold_rank"), "fold_rank")
    horizon = _required_int(value.get("horizon_trading_days"), "horizon_trading_days")
    if horizon not in CALIBRATION_HORIZONS:
        raise ProspectiveCalibrationError("calibration fold horizon is unsupported")
    fit_ids = _required_str_list(value.get("fit_fold_ids"), "fit_fold_ids")
    fit_ranks = _required_int_list(value.get("fit_fold_ranks"), "fit_fold_ranks")
    if len(fit_ids) != len(fit_ranks):
        raise ProspectiveCalibrationError("fit fold ids/ranks length mismatch")
    sample_count = _required_positive_int(value.get("sample_count"), "sample_count")
    class_counts = _validate_count_pair(value.get("class_counts"), "class_counts")
    if class_counts["0"] + class_counts["1"] != sample_count:
        raise ProspectiveCalibrationError("class counts do not equal sample_count")
    rebalance_counts = _validate_count_pair(
        value.get("rebalance_worthwhile_class_counts"),
        "rebalance_worthwhile_class_counts",
    )
    identity_metrics = _validate_metrics(value.get("identity_metrics"), "identity_metrics")
    isotonic_metrics = _validate_metrics(
        value.get("isotonic_metrics"), "isotonic_metrics"
    )
    model_hash = _required_hash(value.get("model_artifact_hash"), "model_artifact_hash")
    dataset_hash = _required_hash(
        value.get("dataset_identity_hash"), "dataset_identity_hash"
    )
    if model_hash != policy.payload["model_artifact_hash"]:
        raise ProspectiveCalibrationError("calibration fold model identity mismatch")
    if dataset_hash != policy.payload["dataset_identity_hash"]:
        raise ProspectiveCalibrationError("calibration fold dataset identity mismatch")
    inference_hash = _required_hash(
        value.get("inference_identity_hash"), "inference_identity_hash"
    )
    if expected_inference_identity_hash is not None and inference_hash != expected_inference_identity_hash:
        raise ProspectiveCalibrationError("calibration fold inference identity mismatch")
    source_hash = _required_hash(value.get("source_lineage_hash"), "source_lineage_hash")
    return {
        "policy_hash": policy.policy_hash,
        "fold_id": fold_id,
        "fold_rank": fold_rank,
        "fit_fold_ids": fit_ids,
        "fit_fold_ranks": fit_ranks,
        "horizon_trading_days": horizon,
        "sample_count": sample_count,
        "class_counts": class_counts,
        "rebalance_worthwhile_class_counts": rebalance_counts,
        "identity_metrics": identity_metrics,
        "isotonic_metrics": isotonic_metrics,
        "model_artifact_hash": model_hash,
        "dataset_identity_hash": dataset_hash,
        "inference_identity_hash": inference_hash,
        "source_lineage_hash": source_hash,
    }


def _validate_count_pair(value: object, field_name: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"0", "1"}:
        raise ProspectiveCalibrationError(f"{field_name} must contain class 0 and 1")
    return {
        key: _required_nonnegative_int(value[key], f"{field_name}.{key}")
        for key in ("0", "1")
    }


def _validate_metrics(value: object, field_name: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"ece_bp", "brier_bp"}:
        raise ProspectiveCalibrationError(
            f"{field_name} must contain ece_bp and brier_bp"
        )
    result = {
        key: _required_nonnegative_int(value[key], f"{field_name}.{key}")
        for key in ("ece_bp", "brier_bp")
    }
    if any(item > 10_000 for item in result.values()):
        raise ProspectiveCalibrationError(f"{field_name} is outside integer bp range")
    return result


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveCalibrationError(f"{field_name} must be non-empty text")
    return value.strip()


def _required_hash(value: object, field_name: str) -> str:
    text = _required_text(value, field_name)
    if len(text) != 71 or not text.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in text[7:]
    ):
        raise ProspectiveCalibrationError(f"{field_name} must be sha256")
    return text


def _required_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveCalibrationError(f"{field_name} must be an integer")
    return value


def _required_nonnegative_int(value: object, field_name: str) -> int:
    result = _required_int(value, field_name)
    if result < 0:
        raise ProspectiveCalibrationError(f"{field_name} must be non-negative")
    return result


def _required_positive_int(value: object, field_name: str) -> int:
    result = _required_int(value, field_name)
    if result <= 0:
        raise ProspectiveCalibrationError(f"{field_name} must be positive")
    return result


def _required_str_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ProspectiveCalibrationError(f"{field_name} must be a text array")
    return [item.strip() for item in value]


def _required_int_list(value: object, field_name: str) -> list[int]:
    if not isinstance(value, list):
        raise ProspectiveCalibrationError(f"{field_name} must be an integer array")
    return [_required_nonnegative_int(item, field_name) for item in value]


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
