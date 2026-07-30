"""配置型 ML Promotion 的凍結 calibration／PSI 參考契約。

本模組只在兩個明確隔離的邊界使用浮點：

* 載入既有 sklearn 分類器並執行 ``predict_proba``；
* 把 PIT 特徵的 ``value_int / scale`` 轉為模型矩陣。

所有公開契約、持久化機率、分箱、PSI、ECE 與 Brier 均為整數 bp／整數
count。凍結參考只可由已雜湊綁定的 training dataset 與 model artifact 建立；
每日 observation 只接受 ``available_at <= decision_at`` 的 post-freeze rows。
未滿 20 個成熟 decision dates 時，評估固定回傳 ``not_evaluated``，不得以 0
冒充尚未存在的正式證據。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping, Sequence, cast

import joblib
import numpy as np
from numpy.typing import NDArray

from ml_module.allocation_contracts import PITFeatureValue, PortfolioMLDatasetRow


REFERENCE_SCHEMA_VERSION = "ml-allocation-promotion-reference-v2"
OBSERVATION_SCHEMA_VERSION = (
    "ml-allocation-promotion-reference-observation-v2"
)
METRICS_SCHEMA_VERSION = "ml-allocation-promotion-reference-metrics-v2"
PROBABILITY_BIN_UPPER_BOUNDS_BP = tuple(range(1_000, 10_000, 1_000))
FAMILY_COVERAGE_BIN_UPPER_BOUNDS_BP = PROBABILITY_BIN_UPPER_BOUNDS_BP
TOTAL_BP = 10_000
PROMOTION_HORIZONS = (5, 10, 20, 60)
OUTCOME_CONTRACT_VERSION = "ml-allocation-downside-outcome-contract-v1"
OUTCOME_CONTRACT_BODY: Mapping[str, object] = {
    "contract_version": OUTCOME_CONTRACT_VERSION,
    "horizons_trading_sessions": list(PROMOTION_HORIZONS),
    "decision_timestamp": "08:30:00 Asia/Taipei",
    "stock_calendar": "per_symbol_observed_market_sessions",
    "entry": "next_tradable_session_open_at_or_after_decision_date",
    "exit": "close_of_hth_symbol_market_session_including_entry_session",
    "benchmark_id": "TAIEX",
    "benchmark_interval": "same_stock_entry_date_open_to_exit_date_close",
    "buy_cost_bp": 25,
    "sell_cost_bp": 55,
    "label_formula": (
        "actual_downside=int(("
        "stock_open_to_close_return_bp-25-55-"
        "taiex_same_interval_open_to_close_return_bp)<0)"
    ),
    "required_custody": [
        "stock_source_rows_hash",
        "benchmark_source_rows_hash",
        "available_at",
        "revision_id",
        "calendar_hash",
        "corporate_action_manifest_hash",
        "corporate_action_canonical_events_hash",
    ],
    "fail_closed_if_missing": [
        "stock_open",
        "stock_close",
        "benchmark_open",
        "benchmark_close",
        "source_availability",
        "source_revision",
        "symbol_session_calendar",
        "corporate_action_custody",
    ],
}
OUTCOME_CONTRACT_HASH = "sha256:" + hashlib.sha256(
    json.dumps(
        OUTCOME_CONTRACT_BODY,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
_SHA256_PREFIX = "sha256:"


@dataclass(frozen=True)
class PromotionReferencePublication:
    """Immutable promotion reference publication identity."""

    reference_path: Path
    reference_hash: str
    reference_file_hash: str
    row_count: int
    feature_count: int
    family_count: int


@dataclass(frozen=True)
class _NumericRow:
    row_id: str
    decision_at: str
    symbol: str
    values: Mapping[str, tuple[int | None, int, bool]]


def build_promotion_reference(
    *,
    model_artifact_path: Path,
    training_manifest_path: Path,
    dataset_manifest_path: Path,
    promotion_policy_hash: str,
    output_root: Path,
    bin_count: int = 10,
    batch_size: int = 1_024,
) -> PromotionReferencePublication:
    """由 frozen dataset 與 model 建立 deterministic promotion reference。

    ``dataset_manifest_path`` 必須是 ``portfolio-ml-training-shards.v2`` 的
    immutable manifest；每個 gzip shard 的壓縮內容 hash 會在讀取前重算。
    """

    _require_sha256(promotion_policy_hash, "promotion_policy_hash")
    if isinstance(bin_count, bool) or not isinstance(bin_count, int) or bin_count < 2:
        raise ValueError("bin_count must be an integer >= 2")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")

    model_path = model_artifact_path.resolve()
    training_path = training_manifest_path.resolve()
    dataset_path = dataset_manifest_path.resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"model artifact is missing: {model_path}")
    training = _read_json_object(training_path, "training manifest")
    dataset = _read_json_object(dataset_path, "dataset manifest")
    _validate_dataset_manifest_hash(dataset)

    model_hash = _file_hash(model_path)
    training_file_hash = _file_hash(training_path)
    dataset_file_hash = _file_hash(dataset_path)
    if training.get("artifact_hash") != model_hash:
        raise ValueError("training manifest artifact_hash mismatch")
    if training.get("dataset_manifest_file_hash") != dataset_file_hash:
        raise ValueError("training manifest dataset_manifest_file_hash mismatch")
    _validate_cross_artifact_custody(training=training, dataset=dataset)

    artifact = _load_model_artifact(model_path, expected_hash=model_hash)
    _validate_model_custody(
        artifact=artifact,
        training=training,
        dataset=dataset,
    )
    feature_packs = _feature_packs(artifact)
    horizons = _artifact_horizons(artifact)
    if horizons != PROMOTION_HORIZONS:
        raise ValueError(
            "promotion reference requires exact horizons 5/10/20/60"
        )
    feature_metadata = _feature_metadata(dataset, feature_packs)
    shard_specs = _validated_shard_specs(
        training=training,
        dataset=dataset,
        dataset_manifest_path=dataset_path,
    )

    values_by_feature: dict[str, list[int]] = {
        feature_id: [] for _, feature_ids in feature_packs for feature_id in feature_ids
    }
    missing_by_feature = {feature_id: 0 for feature_id in values_by_feature}
    family_coverage_values: dict[str, list[int]] = {
        pack_id: [] for pack_id, _ in feature_packs
    }
    calibrated_probabilities: dict[int, list[int]] = {
        horizon: [] for horizon in horizons
    }
    uncalibrated_probabilities: dict[int, list[int]] = {
        horizon: [] for horizon in horizons
    }
    row_count = 0
    seen_row_ids: set[str] = set()

    for shard_path, expected_rows in shard_specs:
        shard_rows = 0
        batch: list[_NumericRow] = []
        for row in _iter_training_rows(
            shard_path,
            artifact=artifact,
            expected_feature_ids=frozenset(values_by_feature),
        ):
            if row.row_id in seen_row_ids:
                raise ValueError(f"duplicate frozen row_id: {row.row_id}")
            seen_row_ids.add(row.row_id)
            row_count += 1
            shard_rows += 1
            for pack_id, feature_ids in feature_packs:
                observed_count = 0
                for feature_id in feature_ids:
                    value_int, _scale, observed = row.values[feature_id]
                    if observed:
                        assert value_int is not None
                        values_by_feature[feature_id].append(value_int)
                        observed_count += 1
                    else:
                        missing_by_feature[feature_id] += 1
                family_coverage_values[pack_id].append(
                    _round_ratio(observed_count * TOTAL_BP, len(feature_ids))
                )
            batch.append(row)
            if len(batch) >= batch_size:
                by_horizon = _predict_downside_probabilities_by_horizon_bp(
                    artifact=artifact,
                    rows=tuple(batch),
                    feature_packs=feature_packs,
                )
                for horizon in horizons:
                    calibrated, uncalibrated = by_horizon[horizon]
                    calibrated_probabilities[horizon].extend(calibrated)
                    uncalibrated_probabilities[horizon].extend(uncalibrated)
                batch.clear()
        if batch:
            by_horizon = _predict_downside_probabilities_by_horizon_bp(
                artifact=artifact,
                rows=tuple(batch),
                feature_packs=feature_packs,
            )
            for horizon in horizons:
                calibrated, uncalibrated = by_horizon[horizon]
                calibrated_probabilities[horizon].extend(calibrated)
                uncalibrated_probabilities[horizon].extend(uncalibrated)
        if shard_rows != expected_rows:
            raise ValueError(
                f"shard sample_count mismatch: {shard_path.name} "
                f"{shard_rows} != {expected_rows}"
            )

    expected_row_count = _require_int(dataset.get("sample_count"), "sample_count")
    if row_count != expected_row_count:
        raise ValueError(
            f"dataset sample_count mismatch: {row_count} != {expected_row_count}"
        )
    for horizon in horizons:
        if len(calibrated_probabilities[horizon]) != row_count:
            raise ValueError(
                f"calibrated frozen prediction count mismatch: h{horizon}"
            )
        if len(uncalibrated_probabilities[horizon]) != row_count:
            raise ValueError(
                f"uncalibrated frozen prediction count mismatch: h{horizon}"
            )

    feature_distributions: list[dict[str, object]] = []
    for feature_id in sorted(values_by_feature):
        values = values_by_feature[feature_id]
        cuts = _quantile_cut_points(values, bin_count=bin_count)
        counts = _histogram_counts(
            values,
            upper_bounds=cuts,
            missing_count=missing_by_feature[feature_id],
        )
        metadata = feature_metadata[feature_id]
        feature_distributions.append(
            {
                "feature_id": feature_id,
                "family_id": metadata["family_id"],
                "source_id": metadata["source_id"],
                "scale": metadata["scale"],
                "numeric_upper_bounds_value_int": list(cuts),
                "bucket_counts": counts,
                "numeric_observation_count": len(values),
                "missing_observation_count": missing_by_feature[feature_id],
                "total_observation_count": row_count,
                "missing_bucket_is_last": True,
            }
        )

    family_distributions = [
        {
            "family_id": family_id,
            "coverage_upper_bounds_bp": list(
                FAMILY_COVERAGE_BIN_UPPER_BOUNDS_BP
            ),
            "bucket_counts": _histogram_counts(
                family_coverage_values[family_id],
                upper_bounds=FAMILY_COVERAGE_BIN_UPPER_BOUNDS_BP,
                missing_count=0,
                append_missing_bucket=False,
            ),
            "total_observation_count": row_count,
        }
        for family_id in sorted(family_coverage_values)
    ]

    custody = {
        "model_artifact_hash": model_hash,
        "model_artifact_size_bytes": model_path.stat().st_size,
        "training_manifest_file_hash": training_file_hash,
        "dataset_manifest_hash": _require_sha256(
            dataset.get("manifest_hash"),
            "dataset.manifest_hash",
        ),
        "dataset_manifest_file_hash": dataset_file_hash,
        "dataset_id": _require_text(training.get("dataset_id"), "dataset_id"),
        "dataset_identity_hash": _require_sha256(
            training.get("dataset_identity_hash"),
            "dataset_identity_hash",
        ),
        "feature_registry_hash": _require_sha256(
            training.get("feature_registry_hash"),
            "feature_registry_hash",
        ),
        "source_manifest_hashes": _canonical_hash_pairs(
            training.get("source_manifest_hashes"),
            "source_manifest_hashes",
        ),
        "training_as_of": _require_text(
            training.get("training_as_of"),
            "training_as_of",
        ),
        "promotion_policy_hash": promotion_policy_hash,
    }
    body: dict[str, object] = {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "status": "ready",
        "reference_scope": "frozen_training_distribution_not_formal_oos",
        "custody": custody,
        "row_count": row_count,
        "feature_count": len(feature_distributions),
        "family_count": len(family_distributions),
        "feature_distributions": feature_distributions,
        "family_distributions": family_distributions,
        "uncalibrated_probability_contract": {
            "head_id": "downside_probability_bp",
            "method": (
                "mean_predict_proba_of_calibrated_classifier_fold_estimators"
            ),
            "positive_class": 1,
            "expert_aggregation": (
                "family_weighted_active_algorithm_experts_within_each_horizon"
            ),
            "quantization": "integer_bp_round_half_even",
            "fallback_probability_bp": 5_000,
            "model_artifact_hash": model_hash,
            "horizons_trading_sessions": list(horizons),
        },
        "frozen_probability_distributions_by_horizon": [
            {
                "horizon_trading_sessions": horizon,
                "probability_upper_bounds_bp": list(
                    PROBABILITY_BIN_UPPER_BOUNDS_BP
                ),
                "calibrated_bucket_counts": _histogram_counts(
                    calibrated_probabilities[horizon],
                    upper_bounds=PROBABILITY_BIN_UPPER_BOUNDS_BP,
                    missing_count=0,
                    append_missing_bucket=False,
                ),
                "uncalibrated_bucket_counts": _histogram_counts(
                    uncalibrated_probabilities[horizon],
                    upper_bounds=PROBABILITY_BIN_UPPER_BOUNDS_BP,
                    missing_count=0,
                    append_missing_bucket=False,
                ),
                "observation_count": row_count,
            }
            for horizon in horizons
        ],
        "psi_contract": {
            "smoothing_count_per_bucket": 1,
            "formula": (
                "sum((current_share-reference_share)"
                "*ln(current_share/reference_share))*10000"
            ),
            "feature_aggregation": "maximum_feature_or_family_psi_bp",
        },
        "calibration_contract": {
            "ece_bin_upper_bounds_bp": list(
                PROBABILITY_BIN_UPPER_BOUNDS_BP
            ),
            "brier_unit": "integer_bp",
            "minimum_unique_matured_decision_dates": 20,
            "outcomes_are_post_decision_supervised_evidence_only": True,
            "aggregation": (
                "per_horizon_then_conservative_max_across_horizons"
            ),
        },
        "outcome_contract": {
            "contract_version": OUTCOME_CONTRACT_VERSION,
            "contract_hash": OUTCOME_CONTRACT_HASH,
            "contract_body": dict(OUTCOME_CONTRACT_BODY),
        },
        "safety": {
            "strict_pit_availability_verified": True,
            "reference_uses_frozen_training_features_only": True,
            "current_observations_cannot_become_reference": True,
            "future_outcomes_used_in_reference": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
        },
    }
    reference_hash = _payload_hash(body)
    payload = {**body, "reference_hash": reference_hash}
    reference_dir = output_root.resolve() / "runs" / (
        f"promotion-reference-{reference_hash[7:23]}"
    )
    reference_path = reference_dir / "promotion_reference.json"
    _atomic_write_immutable_json(reference_path, payload)
    reference_file_hash = _file_hash(reference_path)
    pointer_payload = {
        "schema_version": "ml-allocation-promotion-reference-pointer-v1",
        "reference_hash": reference_hash,
        "reference_file_hash": reference_file_hash,
        "reference_path": str(reference_path),
        "model_artifact_hash": model_hash,
        "dataset_identity_hash": custody["dataset_identity_hash"],
        "promotion_policy_hash": promotion_policy_hash,
    }
    _atomic_write_json(output_root.resolve() / "latest_reference.json", pointer_payload)
    return PromotionReferencePublication(
        reference_path=reference_path,
        reference_hash=reference_hash,
        reference_file_hash=reference_file_hash,
        row_count=row_count,
        feature_count=len(feature_distributions),
        family_count=len(family_distributions),
    )


def load_promotion_reference(
    reference_path: Path,
    *,
    expected_reference_file_hash: str | None = None,
    expected_model_artifact_hash: str | None = None,
    expected_dataset_identity_hash: str | None = None,
    expected_promotion_policy_hash: str | None = None,
) -> Mapping[str, Any]:
    """載入並完整重算 reference canonical hash 與可選外部 custody。"""

    path = reference_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"promotion reference is missing: {path}")
    if expected_reference_file_hash is not None:
        _require_sha256(
            expected_reference_file_hash,
            "expected_reference_file_hash",
        )
        if _file_hash(path) != expected_reference_file_hash:
            raise ValueError("promotion reference file hash mismatch")
    payload = _read_json_object(path, "promotion reference")
    if payload.get("schema_version") != REFERENCE_SCHEMA_VERSION:
        raise ValueError("promotion reference schema_version mismatch")
    reference_hash = _require_sha256(
        payload.get("reference_hash"),
        "reference_hash",
    )
    body = dict(payload)
    body.pop("reference_hash", None)
    if _payload_hash(body) != reference_hash:
        raise ValueError("promotion reference canonical hash mismatch")
    custody = _mapping(payload.get("custody"), "custody")
    expected_values = (
        (
            "model_artifact_hash",
            expected_model_artifact_hash,
        ),
        (
            "dataset_identity_hash",
            expected_dataset_identity_hash,
        ),
        (
            "promotion_policy_hash",
            expected_promotion_policy_hash,
        ),
    )
    for field_name, expected in expected_values:
        if expected is None:
            continue
        _require_sha256(expected, f"expected_{field_name}")
        if custody.get(field_name) != expected:
            raise ValueError(f"promotion reference {field_name} mismatch")
    _validate_reference_distributions(payload)
    return payload


def build_promotion_observation(
    *,
    reference_path: Path,
    expected_reference_file_hash: str,
    model_artifact_path: Path,
    rows: Sequence[PortfolioMLDatasetRow],
    calibrated_probability_by_symbol_bp: Mapping[str, int],
    inference_input_hash: str,
    proposal_hash: str,
    promotion_policy_hash: str,
) -> dict[str, object]:
    """建立每日 calibrated/raw probability 與 current distribution custody。"""

    _require_sha256(inference_input_hash, "inference_input_hash")
    _require_sha256(proposal_hash, "proposal_hash")
    _require_sha256(promotion_policy_hash, "promotion_policy_hash")
    reference = load_promotion_reference(
        reference_path,
        expected_reference_file_hash=expected_reference_file_hash,
        expected_promotion_policy_hash=promotion_policy_hash,
    )
    custody = _mapping(reference.get("custody"), "reference.custody")
    model_hash = _require_sha256(
        custody.get("model_artifact_hash"),
        "reference.model_artifact_hash",
    )
    artifact = _load_model_artifact(
        model_artifact_path.resolve(),
        expected_hash=model_hash,
    )
    if not rows:
        raise ValueError("promotion observation requires inference rows")
    if any(not isinstance(row, PortfolioMLDatasetRow) for row in rows):
        raise TypeError("rows must contain PortfolioMLDatasetRow values")
    canonical_rows = tuple(sorted(rows, key=lambda item: (item.symbol, item.row_id)))
    if len({row.row_id for row in canonical_rows}) != len(canonical_rows):
        raise ValueError("promotion observation row ids must be unique")
    if len({row.symbol for row in canonical_rows}) != len(canonical_rows):
        raise ValueError("promotion observation symbols must be unique")
    decision_values = {row.decision_at for row in canonical_rows}
    if len(decision_values) != 1:
        raise ValueError("promotion observation rows must share decision_at")
    decision_at = next(iter(decision_values))
    decision_dt = _parse_datetime(decision_at, "row.decision_at")
    training_dt = _parse_datetime(
        _require_text(custody.get("training_as_of"), "training_as_of"),
        "training_as_of",
    )
    if decision_dt <= training_dt:
        raise ValueError("promotion observation must be strictly post-freeze")
    if {
        row.symbol for row in canonical_rows
    } != set(calibrated_probability_by_symbol_bp):
        raise ValueError("calibrated probability symbols must equal inference rows")

    feature_packs = _feature_packs(artifact)
    expected_feature_ids = frozenset(
        feature_id
        for _, feature_ids in feature_packs
        for feature_id in feature_ids
    )
    numeric_rows: list[_NumericRow] = []
    for row in canonical_rows:
        if row.targets is not None:
            raise ValueError("promotion observation cannot contain teacher targets")
        if row.dataset_identity_hash != custody.get("dataset_identity_hash"):
            raise ValueError("promotion observation dataset identity mismatch")
        if row.feature_registry_hash != custody.get("feature_registry_hash"):
            raise ValueError("promotion observation feature registry mismatch")
        runtime_values = _validated_runtime_features(
            row.features,
            decision_at=row.decision_at,
            expected_feature_ids=expected_feature_ids,
        )
        numeric_rows.append(
            _NumericRow(
                row_id=row.row_id,
                decision_at=row.decision_at,
                symbol=row.symbol,
                values=runtime_values,
            )
        )

    calibrated_model_bp, _uncalibrated_aggregate_bp = (
        _predict_downside_probabilities_bp(
            artifact=artifact,
            rows=tuple(numeric_rows),
            feature_packs=feature_packs,
        )
    )
    probabilities_by_horizon = (
        _predict_downside_probabilities_by_horizon_bp(
            artifact=artifact,
            rows=tuple(numeric_rows),
            feature_packs=feature_packs,
        )
    )
    if tuple(sorted(probabilities_by_horizon)) != PROMOTION_HORIZONS:
        raise ValueError(
            "promotion observation requires exact horizons 5/10/20/60"
        )
    prediction_rows: list[dict[str, object]] = []
    for row_index, (row, calibrated_from_model) in enumerate(
        zip(
        canonical_rows,
        calibrated_model_bp,
        strict=True,
        )
    ):
        calibrated_from_proposal = _require_bp(
            calibrated_probability_by_symbol_bp[row.symbol],
            f"calibrated_probability_by_symbol_bp[{row.symbol}]",
        )
        if calibrated_from_model != calibrated_from_proposal:
            raise ValueError(
                "proposal calibrated probability does not replay frozen model"
            )
        feature_snapshot_hash = _runtime_feature_snapshot_hash(row)
        for horizon in PROMOTION_HORIZONS:
            calibrated, uncalibrated = probabilities_by_horizon[horizon]
            prediction_rows.append(
                {
                    "row_id": row.row_id,
                    "symbol": row.symbol,
                    "horizon_trading_sessions": horizon,
                    "calibrated_downside_probability_bp": (
                        calibrated[row_index]
                    ),
                    "uncalibrated_downside_probability_bp": (
                        uncalibrated[row_index]
                    ),
                    "feature_snapshot_hash": feature_snapshot_hash,
                }
            )

    feature_reference = {
        _require_text(item.get("feature_id"), "feature_id"): item
        for item in _mapping_sequence(
            reference.get("feature_distributions"),
            "feature_distributions",
        )
    }
    current_features: list[dict[str, object]] = []
    for feature_id in sorted(feature_reference):
        item = feature_reference[feature_id]
        upper_bounds = _signed_integer_tuple(
            item.get("numeric_upper_bounds_value_int"),
            f"{feature_id}.numeric_upper_bounds_value_int",
            allow_empty=True,
        )
        observed_values: list[int] = []
        missing = 0
        for numeric_row in numeric_rows:
            value_int, scale, observed = numeric_row.values[feature_id]
            if scale != _require_int(item.get("scale"), f"{feature_id}.scale"):
                raise ValueError(f"promotion observation scale mismatch: {feature_id}")
            if observed:
                assert value_int is not None
                observed_values.append(value_int)
            else:
                missing += 1
        current_features.append(
            {
                "feature_id": feature_id,
                "bucket_counts": _histogram_counts(
                    observed_values,
                    upper_bounds=upper_bounds,
                    missing_count=missing,
                ),
                "total_observation_count": len(numeric_rows),
            }
        )

    current_families: list[dict[str, object]] = []
    for family_id, feature_ids in feature_packs:
        coverages = [
            _round_ratio(
                sum(
                    1
                    for feature_id in feature_ids
                    if numeric_row.values[feature_id][2]
                )
                * TOTAL_BP,
                len(feature_ids),
            )
            for numeric_row in numeric_rows
        ]
        current_families.append(
            {
                "family_id": family_id,
                "bucket_counts": _histogram_counts(
                    coverages,
                    upper_bounds=FAMILY_COVERAGE_BIN_UPPER_BOUNDS_BP,
                    missing_count=0,
                    append_missing_bucket=False,
                ),
                "total_observation_count": len(numeric_rows),
            }
        )

    distribution_body = {
        "feature_distributions": current_features,
        "family_distributions": current_families,
    }
    body: dict[str, object] = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "decision_at": decision_at,
        "decision_date": decision_at[:10],
        "reference_hash": reference["reference_hash"],
        "reference_file_hash": expected_reference_file_hash,
        "model_artifact_hash": model_hash,
        "dataset_identity_hash": custody["dataset_identity_hash"],
        "dataset_manifest_file_hash": custody["dataset_manifest_file_hash"],
        "feature_registry_hash": custody["feature_registry_hash"],
        "promotion_policy_hash": promotion_policy_hash,
        "inference_input_hash": inference_input_hash,
        "proposal_hash": proposal_hash,
        "prediction_rows": prediction_rows,
        "prediction_horizons_trading_sessions": list(PROMOTION_HORIZONS),
        "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
        "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
        "current_distribution": distribution_body,
        "current_distribution_hash": _payload_hash(distribution_body),
        "strict_pit_availability_verified": True,
        "future_prefix_violation_count": 0,
        "pit_violation_count": 0,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    return {**body, "observation_hash": _payload_hash(body)}


def evaluate_matured_promotion_reference(
    *,
    reference_path: Path,
    expected_reference_file_hash: str,
    observations: Sequence[Mapping[str, object]],
    downside_outcomes: Sequence[Mapping[str, object]],
    minimum_unique_dates: int = 20,
) -> dict[str, object]:
    """計算成熟 observation 的 ECE／Brier／PSI；證據不足時不填 0。"""

    if (
        isinstance(minimum_unique_dates, bool)
        or not isinstance(minimum_unique_dates, int)
        or minimum_unique_dates < 1
    ):
        raise ValueError("minimum_unique_dates must be a positive integer")
    reference = load_promotion_reference(
        reference_path,
        expected_reference_file_hash=expected_reference_file_hash,
    )
    reference_hash = _require_sha256(
        reference.get("reference_hash"),
        "reference_hash",
    )
    validated_observations = tuple(
        _validate_observation(
            item,
            reference_hash=reference_hash,
            reference_file_hash=expected_reference_file_hash,
        )
        for item in observations
    )
    latest_by_date: dict[str, Mapping[str, Any]] = {}
    for observation in validated_observations:
        decision_date = _require_text(
            observation.get("decision_date"),
            "observation.decision_date",
        )
        existing = latest_by_date.get(decision_date)
        if existing is not None and existing != observation:
            raise ValueError(
                f"multiple promotion observations for decision date: {decision_date}"
            )
        latest_by_date[decision_date] = observation

    outcome_by_key: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for item in downside_outcomes:
        outcome = _mapping(item, "downside_outcome")
        if (
            outcome.get("outcome_contract_version")
            != OUTCOME_CONTRACT_VERSION
            or outcome.get("outcome_contract_hash") != OUTCOME_CONTRACT_HASH
        ):
            raise ValueError("downside outcome contract mismatch")
        decision_date = _require_text(
            outcome.get("decision_date"),
            "outcome.decision_date",
        )
        symbol = _require_text(outcome.get("symbol"), "outcome.symbol")
        horizon = _require_positive_int(
            outcome.get("horizon_trading_sessions"),
            "outcome.horizon_trading_sessions",
        )
        if horizon not in PROMOTION_HORIZONS:
            raise ValueError("downside outcome horizon is unsupported")
        actual = _require_binary(
            outcome.get("actual_downside"),
            "actual_downside",
        )
        stock_return = _require_int(
            outcome.get("stock_open_to_close_return_bp"),
            "outcome.stock_open_to_close_return_bp",
        )
        benchmark_return = _require_int(
            outcome.get("taiex_open_to_close_return_bp"),
            "outcome.taiex_open_to_close_return_bp",
        )
        buy_cost = _require_int(
            outcome.get("buy_cost_bp"),
            "outcome.buy_cost_bp",
        )
        sell_cost = _require_int(
            outcome.get("sell_cost_bp"),
            "outcome.sell_cost_bp",
        )
        if buy_cost != 25 or sell_cost != 55:
            raise ValueError("downside outcome transaction cost contract mismatch")
        benchmark_excess = _require_int(
            outcome.get("benchmark_excess_return_bp"),
            "outcome.benchmark_excess_return_bp",
        )
        if benchmark_excess != (
            stock_return - benchmark_return - buy_cost - sell_cost
        ):
            raise ValueError("downside outcome excess return formula mismatch")
        if actual != int(benchmark_excess < 0):
            raise ValueError("downside outcome label formula mismatch")
        for field_name in (
            "stock_source_rows_hash",
            "benchmark_source_rows_hash",
            "calendar_hash",
            "corporate_action_manifest_hash",
            "corporate_action_canonical_events_hash",
        ):
            _require_sha256(outcome.get(field_name), f"outcome.{field_name}")
        entry_date = _parse_iso_date(
            outcome.get("entry_date"),
            "outcome.entry_date",
        )
        end_date = _parse_iso_date(
            outcome.get("horizon_end_date"),
            "outcome.horizon_end_date",
        )
        if end_date < entry_date:
            raise ValueError("downside outcome horizon dates are reversed")
        available_at = _parse_datetime(
            _require_text(outcome.get("available_at"), "outcome.available_at"),
            "outcome.available_at",
        )
        if available_at.date() < end_date:
            raise ValueError("downside outcome availability predates horizon end")
        _require_sha256(outcome.get("revision_id"), "outcome.revision_id")
        _validate_downside_outcome_source_custody(
            outcome=outcome,
            decision_date=decision_date,
            symbol=symbol,
            horizon=horizon,
            entry_date=entry_date,
            end_date=end_date,
            available_at=available_at,
            stock_return_bp=stock_return,
            benchmark_return_bp=benchmark_return,
        )
        outcome_hash = _require_sha256(
            outcome.get("outcome_hash"),
            "outcome.outcome_hash",
        )
        outcome_body = dict(outcome)
        outcome_body.pop("outcome_hash", None)
        if _payload_hash(outcome_body) != outcome_hash:
            raise ValueError("downside outcome canonical hash mismatch")
        key = (decision_date, symbol, horizon)
        existing_outcome = outcome_by_key.get(key)
        if existing_outcome is not None and existing_outcome != outcome:
            raise ValueError(f"conflicting downside outcome: {key}")
        outcome_by_key[key] = outcome

    matured_dates_by_horizon: dict[int, set[str]] = {
        horizon: set() for horizon in PROMOTION_HORIZONS
    }
    for decision_date in sorted(latest_by_date):
        observation = latest_by_date[decision_date]
        prediction_rows = _mapping_sequence(
            observation.get("prediction_rows"),
            "prediction_rows",
        )
        prediction_keys: set[tuple[str, str, int]] = set()
        for item in prediction_rows:
            horizon = _require_positive_int(
                item.get("horizon_trading_sessions"),
                "prediction.horizon_trading_sessions",
            )
            if horizon not in PROMOTION_HORIZONS:
                raise ValueError("promotion prediction horizon is unsupported")
            key = (
                decision_date,
                _require_text(item.get("symbol"), "symbol"),
                horizon,
            )
            if key in prediction_keys:
                raise ValueError(f"duplicate promotion prediction: {key}")
            prediction_keys.add(key)
        for horizon in PROMOTION_HORIZONS:
            horizon_keys = {
                key for key in prediction_keys if key[2] == horizon
            }
            if horizon_keys and horizon_keys.issubset(outcome_by_key):
                matured_dates_by_horizon[horizon].add(decision_date)
    fully_matured_dates = set(latest_by_date)
    for horizon in PROMOTION_HORIZONS:
        fully_matured_dates &= matured_dates_by_horizon[horizon]
    matured = [
        latest_by_date[decision_date]
        for decision_date in sorted(fully_matured_dates)
    ]
    matured_count = len(matured)
    base: dict[str, object] = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "reference_hash": reference_hash,
        "reference_file_hash": expected_reference_file_hash,
        "matured_unique_decision_date_count": matured_count,
        "matured_unique_decision_date_count_by_horizon": {
            str(horizon): len(matured_dates_by_horizon[horizon])
            for horizon in PROMOTION_HORIZONS
        },
        "minimum_unique_decision_dates": minimum_unique_dates,
        "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
        "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
        "promotion_reference_status": {
            "uncalibrated_probability_baseline": "ready",
            "frozen_feature_distribution": "ready",
            "automatic_nonzero_alpha_possible_after_all_gates": True,
        },
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    if matured_count < minimum_unique_dates:
        blockers = [
            (
                "matured_shadow_days_insufficient:"
                f"h{horizon}:"
                f"{len(matured_dates_by_horizon[horizon])}/"
                f"{minimum_unique_dates}"
            )
            for horizon in PROMOTION_HORIZONS
            if len(matured_dates_by_horizon[horizon]) < minimum_unique_dates
        ]
        if not blockers:
            blockers.append(
                "fully_matured_shadow_days_insufficient:"
                f"{matured_count}/{minimum_unique_dates}"
            )
        body = {
            **base,
            "status": "not_evaluated",
            "calibration_ece_bp": None,
            "calibrated_brier_bp": None,
            "uncalibrated_brier_bp": None,
            "feature_psi_bp": None,
            "family_psi_bp": None,
            "psi_bp": None,
            "horizon_metrics": {
                str(horizon): {
                    "status": "not_evaluated",
                    "matured_unique_decision_date_count": len(
                        matured_dates_by_horizon[horizon]
                    ),
                    "calibration_ece_bp": None,
                    "calibrated_brier_bp": None,
                    "uncalibrated_brier_bp": None,
                }
                for horizon in PROMOTION_HORIZONS
            },
            "blockers": blockers,
        }
        return {**body, "metrics_hash": _payload_hash(body)}

    horizon_metrics: dict[str, dict[str, object]] = {}
    calibrated_ece_values: list[int] = []
    calibrated_brier_values: list[int] = []
    uncalibrated_brier_values: list[int] = []
    prediction_outcome_count = 0
    for horizon in PROMOTION_HORIZONS:
        calibrated_rows: list[tuple[int, int]] = []
        uncalibrated_rows: list[tuple[int, int]] = []
        for observation in matured:
            decision_date = _require_text(
                observation.get("decision_date"),
                "decision_date",
            )
            for item in _mapping_sequence(
                observation.get("prediction_rows"),
                "prediction_rows",
            ):
                item_horizon = _require_positive_int(
                    item.get("horizon_trading_sessions"),
                    "prediction.horizon_trading_sessions",
                )
                if item_horizon != horizon:
                    continue
                symbol = _require_text(item.get("symbol"), "symbol")
                outcome = outcome_by_key[(decision_date, symbol, horizon)]
                actual = _require_binary(
                    outcome.get("actual_downside"),
                    "actual_downside",
                )
                calibrated_rows.append(
                    (
                        _require_bp(
                            item.get(
                                "calibrated_downside_probability_bp"
                            ),
                            "calibrated_downside_probability_bp",
                        ),
                        actual,
                    )
                )
                uncalibrated_rows.append(
                    (
                        _require_bp(
                            item.get(
                                "uncalibrated_downside_probability_bp"
                            ),
                            "uncalibrated_downside_probability_bp",
                        ),
                        actual,
                    )
                )
        calibrated_metrics = calibration_metrics_bp(calibrated_rows)
        uncalibrated_metrics = calibration_metrics_bp(uncalibrated_rows)
        horizon_metrics[str(horizon)] = {
            "status": "evaluated",
            "matured_unique_decision_date_count": len(matured),
            "calibration_ece_bp": calibrated_metrics["ece_bp"],
            "calibrated_brier_bp": calibrated_metrics["brier_bp"],
            "uncalibrated_brier_bp": uncalibrated_metrics["brier_bp"],
            "prediction_outcome_count": len(calibrated_rows),
        }
        calibrated_ece_values.append(calibrated_metrics["ece_bp"])
        calibrated_brier_values.append(calibrated_metrics["brier_bp"])
        uncalibrated_brier_values.append(
            uncalibrated_metrics["brier_bp"]
        )
        prediction_outcome_count += len(calibrated_rows)
    psi = population_stability_metrics_bp(
        reference=reference,
        observations=matured,
    )
    body = {
        **base,
        "status": "evaluated",
        "calibration_ece_bp": max(calibrated_ece_values),
        "calibrated_brier_bp": max(calibrated_brier_values),
        "uncalibrated_brier_bp": max(uncalibrated_brier_values),
        "horizon_metrics": horizon_metrics,
        "feature_psi_bp": psi["feature_psi_bp"],
        "feature_psi_id": psi["feature_psi_id"],
        "family_psi_bp": psi["family_psi_bp"],
        "family_psi_id": psi["family_psi_id"],
        "psi_bp": psi["psi_bp"],
        "prediction_outcome_count": prediction_outcome_count,
        "blockers": [],
    }
    return {**body, "metrics_hash": _payload_hash(body)}


def _validate_downside_outcome_source_custody(
    *,
    outcome: Mapping[str, Any],
    decision_date: str,
    symbol: str,
    horizon: int,
    entry_date: date,
    end_date: date,
    available_at: datetime,
    stock_return_bp: int,
    benchmark_return_bp: int,
) -> None:
    decision = _parse_iso_date(decision_date, "outcome.decision_date")
    if entry_date < decision:
        raise ValueError("downside outcome entry predates decision")
    custody = _mapping(outcome.get("source_custody"), "outcome.source_custody")
    if custody.get("benchmark_id") != "TAIEX":
        raise ValueError("downside outcome benchmark custody mismatch")
    if custody.get("label_formula") != (
        "stock_return_bp-taiex_return_bp-25-55"
    ):
        raise ValueError("downside outcome custody formula mismatch")
    if custody.get("revision_basis") != (
        "content_addressed_source_row_snapshot"
    ):
        raise ValueError("downside outcome revision basis mismatch")
    stock_rows = _mapping_sequence(
        custody.get("stock_rows"),
        "outcome.source_custody.stock_rows",
    )
    benchmark_rows = _mapping_sequence(
        custody.get("benchmark_rows"),
        "outcome.source_custody.benchmark_rows",
    )
    if len(stock_rows) != 2 or len(benchmark_rows) != 2:
        raise ValueError("downside outcome source row width mismatch")
    stock_entry_hash = _validated_outcome_source_row(
        stock_rows[0],
        source_id="sqlite.daily_prices",
        table_name="daily_prices",
        expected_date=entry_date,
        symbol=symbol,
    )
    stock_exit_hash = _validated_outcome_source_row(
        stock_rows[1],
        source_id="sqlite.daily_prices",
        table_name="daily_prices",
        expected_date=end_date,
        symbol=symbol,
    )
    benchmark_entry_hash = _validated_outcome_source_row(
        benchmark_rows[0],
        source_id="sqlite.market_indices",
        table_name="market_indices",
        expected_date=entry_date,
        symbol=None,
    )
    benchmark_exit_hash = _validated_outcome_source_row(
        benchmark_rows[1],
        source_id="sqlite.market_indices",
        table_name="market_indices",
        expected_date=end_date,
        symbol=None,
    )
    expected_stock_rows_hash = _payload_hash(
        {
            "source_id": "sqlite.daily_prices",
            "entry_source_row_hash": stock_entry_hash,
            "exit_source_row_hash": stock_exit_hash,
        }
    )
    if outcome.get("stock_source_rows_hash") != expected_stock_rows_hash:
        raise ValueError("downside outcome stock source rows hash mismatch")
    expected_benchmark_rows_hash = _payload_hash(
        {
            "source_id": "sqlite.market_indices",
            "benchmark_id": "TAIEX",
            "entry_source_row_hash": benchmark_entry_hash,
            "exit_source_row_hash": benchmark_exit_hash,
        }
    )
    if (
        outcome.get("benchmark_source_rows_hash")
        != expected_benchmark_rows_hash
    ):
        raise ValueError("downside outcome benchmark source rows hash mismatch")
    calendar = tuple(
        _require_text(item, "symbol_session_calendar[]")
        for item in _sequence(
            custody.get("symbol_session_calendar"),
            "outcome.source_custody.symbol_session_calendar",
        )
    )
    if len(calendar) != horizon:
        raise ValueError("downside outcome symbol calendar horizon mismatch")
    parsed_calendar = tuple(
        _parse_iso_date(item, "symbol_session_calendar[]")
        for item in calendar
    )
    if (
        parsed_calendar[0] != entry_date
        or parsed_calendar[-1] != end_date
        or tuple(sorted(set(parsed_calendar))) != parsed_calendar
    ):
        raise ValueError("downside outcome symbol calendar is invalid")
    expected_calendar_hash = _payload_hash(
        {
            "calendar_type": "per_symbol_market_sessions",
            "symbol": symbol,
            "decision_date": decision_date,
            "horizon_trading_sessions": horizon,
            "dates": list(calendar),
        }
    )
    if outcome.get("calendar_hash") != expected_calendar_hash:
        raise ValueError("downside outcome calendar hash mismatch")
    stock_entry = _positive_decimal_text(
        stock_rows[0].get("open"),
        "stock entry open",
    )
    stock_exit = _positive_decimal_text(
        stock_rows[1].get("close"),
        "stock exit close",
    )
    benchmark_entry = _positive_decimal_text(
        benchmark_rows[0].get("open"),
        "benchmark entry open",
    )
    benchmark_exit = _positive_decimal_text(
        benchmark_rows[1].get("close"),
        "benchmark exit close",
    )
    if _decimal_return_bp(stock_entry, stock_exit) != stock_return_bp:
        raise ValueError("downside outcome stock return source mismatch")
    if (
        _decimal_return_bp(benchmark_entry, benchmark_exit)
        != benchmark_return_bp
    ):
        raise ValueError("downside outcome benchmark return source mismatch")
    source_available = max(
        _parse_datetime(
            _require_text(row.get("available_at"), "source row available_at"),
            "source row available_at",
        )
        for row in (*stock_rows, *benchmark_rows)
    )
    if source_available != available_at:
        raise ValueError("downside outcome source availability mismatch")
    expected_revision = _payload_hash(
        {
            "stock_entry_revision_id": stock_entry_hash,
            "stock_exit_revision_id": stock_exit_hash,
            "benchmark_entry_revision_id": benchmark_entry_hash,
            "benchmark_exit_revision_id": benchmark_exit_hash,
            "corporate_action_manifest_hash": outcome.get(
                "corporate_action_manifest_hash"
            ),
            "corporate_action_canonical_events_hash": outcome.get(
                "corporate_action_canonical_events_hash"
            ),
        }
    )
    if outcome.get("revision_id") != expected_revision:
        raise ValueError("downside outcome revision custody mismatch")


def _validated_outcome_source_row(
    row: Mapping[str, Any],
    *,
    source_id: str,
    table_name: str,
    expected_date: date,
    symbol: str | None,
) -> str:
    if row.get("source_id") != source_id or row.get("table") != table_name:
        raise ValueError("downside outcome source row identity mismatch")
    if _parse_iso_date(row.get("event_date"), "source row event_date") != (
        expected_date
    ):
        raise ValueError("downside outcome source row date mismatch")
    if symbol is not None and row.get("symbol") != symbol:
        raise ValueError("downside outcome stock source row symbol mismatch")
    if symbol is None and row.get("benchmark_id") != "TAIEX":
        raise ValueError("downside outcome benchmark source row id mismatch")
    _parse_datetime(
        _require_text(row.get("available_at"), "source row available_at"),
        "source row available_at",
    )
    return _payload_hash(row)


def _positive_decimal_text(value: object, field_name: str) -> Decimal:
    text = _require_text(value, field_name)
    try:
        result = Decimal(text)
    except Exception as exc:
        raise ValueError(f"{field_name} must be Decimal text") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{field_name} must be positive")
    return result


def _decimal_return_bp(entry: Decimal, exit_value: Decimal) -> int:
    return int(
        (((exit_value / entry) - Decimal(1)) * Decimal(TOTAL_BP)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def calibration_metrics_bp(
    rows: Sequence[tuple[int, int]],
) -> dict[str, int]:
    """以固定 1,000 bp bins 計算 ECE 與 Brier。"""

    if not rows:
        raise ValueError("calibration rows are required")
    bins: dict[int, list[tuple[int, int]]] = {}
    squared_error = 0
    for probability_bp, actual in rows:
        probability = _require_bp(probability_bp, "probability_bp")
        outcome = _require_binary(actual, "actual_downside")
        bucket = bisect_right(PROBABILITY_BIN_UPPER_BOUNDS_BP, probability)
        bins.setdefault(bucket, []).append((probability, outcome))
        error = probability - outcome * TOTAL_BP
        squared_error += error * error
    ece_numerator = sum(
        abs(
            sum(probability for probability, _ in values)
            - sum(actual for _, actual in values) * TOTAL_BP
        )
        for values in bins.values()
    )
    return {
        "ece_bp": ece_numerator // len(rows),
        "brier_bp": squared_error // len(rows) // TOTAL_BP,
        "observation_count": len(rows),
    }


def population_stability_index_bp(
    reference_counts: Sequence[int],
    current_counts: Sequence[int],
    *,
    smoothing_count: int = 1,
) -> int:
    """以 Decimal 計算 PSI 並輸出整數 bp。"""

    if len(reference_counts) != len(current_counts) or not reference_counts:
        raise ValueError("PSI count vectors must be non-empty and equal length")
    if (
        isinstance(smoothing_count, bool)
        or not isinstance(smoothing_count, int)
        or smoothing_count < 1
    ):
        raise ValueError("smoothing_count must be a positive integer")
    reference = tuple(
        _require_nonnegative_int(value, "reference_count")
        for value in reference_counts
    )
    current = tuple(
        _require_nonnegative_int(value, "current_count")
        for value in current_counts
    )
    bucket_count = len(reference)
    reference_total = sum(reference) + smoothing_count * bucket_count
    current_total = sum(current) + smoothing_count * bucket_count
    psi = Decimal("0")
    for reference_count, current_count in zip(reference, current, strict=True):
        reference_share = Decimal(reference_count + smoothing_count) / Decimal(
            reference_total
        )
        current_share = Decimal(current_count + smoothing_count) / Decimal(
            current_total
        )
        psi += (current_share - reference_share) * (
            current_share / reference_share
        ).ln()
    return int(
        (psi * Decimal(TOTAL_BP)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def population_stability_metrics_bp(
    *,
    reference: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """聚合 matured current histograms，保守採最大 feature/family PSI。"""

    if not observations:
        raise ValueError("PSI observations are required")
    current_feature_counts: dict[str, list[int]] = {}
    current_family_counts: dict[str, list[int]] = {}
    for observation in observations:
        current_distribution = _mapping(
            observation.get("current_distribution"),
            "current_distribution",
        )
        for item in _mapping_sequence(
            current_distribution.get("feature_distributions"),
            "current.feature_distributions",
        ):
            feature_id = _require_text(item.get("feature_id"), "feature_id")
            _accumulate_counts(
                current_feature_counts,
                feature_id,
                _integer_tuple(item.get("bucket_counts"), "bucket_counts"),
            )
        for item in _mapping_sequence(
            current_distribution.get("family_distributions"),
            "current.family_distributions",
        ):
            family_id = _require_text(item.get("family_id"), "family_id")
            _accumulate_counts(
                current_family_counts,
                family_id,
                _integer_tuple(item.get("bucket_counts"), "bucket_counts"),
            )

    feature_scores: list[tuple[int, str]] = []
    for item in _mapping_sequence(
        reference.get("feature_distributions"),
        "reference.feature_distributions",
    ):
        feature_id = _require_text(item.get("feature_id"), "feature_id")
        if feature_id not in current_feature_counts:
            raise ValueError(f"current feature distribution missing: {feature_id}")
        feature_scores.append(
            (
                population_stability_index_bp(
                    _integer_tuple(item.get("bucket_counts"), "bucket_counts"),
                    current_feature_counts[feature_id],
                ),
                feature_id,
            )
        )
    family_scores: list[tuple[int, str]] = []
    for item in _mapping_sequence(
        reference.get("family_distributions"),
        "reference.family_distributions",
    ):
        family_id = _require_text(item.get("family_id"), "family_id")
        if family_id not in current_family_counts:
            raise ValueError(f"current family distribution missing: {family_id}")
        family_scores.append(
            (
                population_stability_index_bp(
                    _integer_tuple(item.get("bucket_counts"), "bucket_counts"),
                    current_family_counts[family_id],
                ),
                family_id,
            )
        )
    feature_max = max(feature_scores, key=lambda item: (item[0], item[1]))
    family_max = max(family_scores, key=lambda item: (item[0], item[1]))
    return {
        "feature_psi_bp": feature_max[0],
        "feature_psi_id": feature_max[1],
        "family_psi_bp": family_max[0],
        "family_psi_id": family_max[1],
        "psi_bp": max(feature_max[0], family_max[0]),
    }


def _validate_observation(
    value: Mapping[str, object],
    *,
    reference_hash: str,
    reference_file_hash: str,
) -> Mapping[str, Any]:
    observation = _mapping(value, "observation")
    if observation.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("promotion observation schema_version mismatch")
    if observation.get("reference_hash") != reference_hash:
        raise ValueError("promotion observation reference_hash mismatch")
    if observation.get("reference_file_hash") != reference_file_hash:
        raise ValueError("promotion observation reference_file_hash mismatch")
    observation_hash = _require_sha256(
        observation.get("observation_hash"),
        "observation_hash",
    )
    body = dict(observation)
    body.pop("observation_hash", None)
    if _payload_hash(body) != observation_hash:
        raise ValueError("promotion observation canonical hash mismatch")
    distribution = _mapping(
        observation.get("current_distribution"),
        "current_distribution",
    )
    if observation.get("current_distribution_hash") != _payload_hash(distribution):
        raise ValueError("promotion current distribution hash mismatch")
    if (
        observation.get("outcome_contract_version")
        != OUTCOME_CONTRACT_VERSION
        or observation.get("outcome_contract_hash") != OUTCOME_CONTRACT_HASH
    ):
        raise ValueError("promotion observation outcome contract mismatch")
    horizons = tuple(
        _require_positive_int(item, "prediction_horizon")
        for item in _sequence(
            observation.get("prediction_horizons_trading_sessions"),
            "prediction_horizons_trading_sessions",
        )
    )
    if horizons != PROMOTION_HORIZONS:
        raise ValueError("promotion observation horizons mismatch")
    prediction_rows = _mapping_sequence(
        observation.get("prediction_rows"),
        "prediction_rows",
    )
    prediction_keys: set[tuple[str, int]] = set()
    symbols: set[str] = set()
    for item in prediction_rows:
        symbol = _require_text(item.get("symbol"), "prediction.symbol")
        horizon = _require_positive_int(
            item.get("horizon_trading_sessions"),
            "prediction.horizon_trading_sessions",
        )
        if horizon not in PROMOTION_HORIZONS:
            raise ValueError("promotion observation prediction horizon mismatch")
        key = (symbol, horizon)
        if key in prediction_keys:
            raise ValueError(f"duplicate promotion observation prediction: {key}")
        prediction_keys.add(key)
        symbols.add(symbol)
        _require_bp(
            item.get("calibrated_downside_probability_bp"),
            "calibrated_downside_probability_bp",
        )
        _require_bp(
            item.get("uncalibrated_downside_probability_bp"),
            "uncalibrated_downside_probability_bp",
        )
    expected_keys = {
        (symbol, horizon)
        for symbol in symbols
        for horizon in PROMOTION_HORIZONS
    }
    if not symbols or prediction_keys != expected_keys:
        raise ValueError(
            "promotion observation must contain every symbol at horizons 5/10/20/60"
        )
    return observation


def _validate_reference_distributions(payload: Mapping[str, Any]) -> None:
    row_count = _require_int(payload.get("row_count"), "row_count")
    features = _mapping_sequence(
        payload.get("feature_distributions"),
        "feature_distributions",
    )
    families = _mapping_sequence(
        payload.get("family_distributions"),
        "family_distributions",
    )
    if len(features) != _require_int(payload.get("feature_count"), "feature_count"):
        raise ValueError("promotion reference feature_count mismatch")
    if len(families) != _require_int(payload.get("family_count"), "family_count"):
        raise ValueError("promotion reference family_count mismatch")
    feature_ids: set[str] = set()
    for item in features:
        feature_id = _require_text(item.get("feature_id"), "feature_id")
        if feature_id in feature_ids:
            raise ValueError(f"duplicate reference feature: {feature_id}")
        feature_ids.add(feature_id)
        counts = _integer_tuple(item.get("bucket_counts"), "bucket_counts")
        if sum(counts) != row_count:
            raise ValueError(f"reference feature count mismatch: {feature_id}")
    family_ids: set[str] = set()
    for item in families:
        family_id = _require_text(item.get("family_id"), "family_id")
        if family_id in family_ids:
            raise ValueError(f"duplicate reference family: {family_id}")
        family_ids.add(family_id)
        counts = _integer_tuple(item.get("bucket_counts"), "bucket_counts")
        if sum(counts) != row_count:
            raise ValueError(f"reference family count mismatch: {family_id}")
    outcome_contract = _mapping(
        payload.get("outcome_contract"),
        "outcome_contract",
    )
    if (
        outcome_contract.get("contract_version") != OUTCOME_CONTRACT_VERSION
        or outcome_contract.get("contract_hash") != OUTCOME_CONTRACT_HASH
        or outcome_contract.get("contract_body") != OUTCOME_CONTRACT_BODY
    ):
        raise ValueError("promotion reference outcome contract mismatch")
    probability_rows = _mapping_sequence(
        payload.get("frozen_probability_distributions_by_horizon"),
        "frozen_probability_distributions_by_horizon",
    )
    seen_horizons: list[int] = []
    for item in probability_rows:
        horizon = _require_positive_int(
            item.get("horizon_trading_sessions"),
            "horizon_trading_sessions",
        )
        if horizon in seen_horizons:
            raise ValueError(f"duplicate frozen probability horizon: {horizon}")
        seen_horizons.append(horizon)
        if _require_int(item.get("observation_count"), "observation_count") != (
            row_count
        ):
            raise ValueError(
                f"frozen probability observation count mismatch: h{horizon}"
            )
        for field_name in (
            "calibrated_bucket_counts",
            "uncalibrated_bucket_counts",
        ):
            counts = _integer_tuple(item.get(field_name), field_name)
            if sum(counts) != row_count:
                raise ValueError(
                    f"frozen probability count mismatch: h{horizon}:{field_name}"
                )
    if tuple(seen_horizons) != PROMOTION_HORIZONS:
        raise ValueError("frozen probability horizons must be 5/10/20/60")


def _validate_cross_artifact_custody(
    *,
    training: Mapping[str, Any],
    dataset: Mapping[str, Any],
) -> None:
    for field_name in (
        "dataset_id",
        "dataset_identity_hash",
        "feature_registry_hash",
        "training_as_of",
    ):
        if training.get(field_name) != dataset.get(field_name):
            raise ValueError(f"training/dataset {field_name} mismatch")
    if _canonical_hash_pairs(
        training.get("source_manifest_hashes"),
        "training.source_manifest_hashes",
    ) != _canonical_hash_pairs(
        dataset.get("source_manifest_hashes"),
        "dataset.source_manifest_hashes",
    ):
        raise ValueError("training/dataset source manifest custody mismatch")
    if _normalize_manifest_packs(training.get("feature_packs")) != (
        _normalize_manifest_packs(dataset.get("feature_packs"))
    ):
        raise ValueError("training/dataset feature packs mismatch")
    if training.get("training_row_count") != dataset.get("sample_count"):
        raise ValueError("training/dataset row count mismatch")


def _validate_model_custody(
    *,
    artifact: Mapping[str, Any],
    training: Mapping[str, Any],
    dataset: Mapping[str, Any],
) -> None:
    for field_name in (
        "dataset_id",
        "dataset_identity_hash",
        "dataset_manifest_file_hash",
        "feature_registry_hash",
        "training_as_of",
    ):
        if artifact.get(field_name) != training.get(field_name):
            raise ValueError(f"model/training {field_name} mismatch")
    if _canonical_hash_pairs(
        artifact.get("source_manifest_hashes"),
        "artifact.source_manifest_hashes",
    ) != _canonical_hash_pairs(
        training.get("source_manifest_hashes"),
        "training.source_manifest_hashes",
    ):
        raise ValueError("model/training source manifest custody mismatch")
    if _normalize_artifact_packs(artifact.get("feature_packs")) != (
        _normalize_manifest_packs(dataset.get("feature_packs"))
    ):
        raise ValueError("model/dataset feature packs mismatch")
    if artifact.get("formal_oos_allowed") is not False:
        raise ValueError("reference builder requires non-promoted frozen model")
    if artifact.get("production_alpha_bp") != 0:
        raise ValueError("reference builder requires frozen alpha=0 model")
    if artifact.get("broker_order_allowed") is not False:
        raise ValueError("reference builder rejects broker-enabled model")


def _validated_shard_specs(
    *,
    training: Mapping[str, Any],
    dataset: Mapping[str, Any],
    dataset_manifest_path: Path,
) -> tuple[tuple[Path, int], ...]:
    dataset_shards = {
        _require_text(item.get("path"), "shard.path"): item
        for item in _mapping_sequence(dataset.get("shards"), "dataset.shards")
    }
    training_shards = {
        _require_text(item.get("file_name"), "input_shard.file_name"): item
        for item in _mapping_sequence(
            training.get("input_shards"),
            "training.input_shards",
        )
    }
    if set(dataset_shards) != set(training_shards):
        raise ValueError("training/dataset shard sets mismatch")
    specs: list[tuple[Path, int]] = []
    for file_name in sorted(dataset_shards):
        dataset_item = dataset_shards[file_name]
        training_item = training_shards[file_name]
        compressed_hash = _require_sha256(
            dataset_item.get("compressed_sha256"),
            f"{file_name}.compressed_sha256",
        )
        if training_item.get("content_hash") != compressed_hash:
            raise ValueError(f"training shard hash mismatch: {file_name}")
        if training_item.get("row_count") != dataset_item.get("sample_count"):
            raise ValueError(f"training shard row count mismatch: {file_name}")
        shard_path = (dataset_manifest_path.parent / file_name).resolve()
        if shard_path.parent != dataset_manifest_path.parent.resolve():
            raise ValueError("dataset shard path escapes immutable publication")
        if _file_hash(shard_path) != compressed_hash:
            raise ValueError(f"dataset shard file hash mismatch: {file_name}")
        specs.append(
            (
                shard_path,
                _require_int(
                    dataset_item.get("sample_count"),
                    f"{file_name}.sample_count",
                ),
            )
        )
    return tuple(specs)


def _iter_training_rows(
    shard_path: Path,
    *,
    artifact: Mapping[str, Any],
    expected_feature_ids: frozenset[str],
) -> Iterable[_NumericRow]:
    header_seen = False
    with gzip.open(shard_path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid training JSONL: {shard_path}:{line_number}"
                ) from exc
            record = _mapping(payload, "training record")
            record_type = record.get("record_type")
            if record_type == "header":
                if header_seen or line_number != 1:
                    raise ValueError("training shard header must be first and unique")
                header_seen = True
                if record.get("dataset_id") != artifact.get("dataset_id"):
                    raise ValueError("training shard dataset_id mismatch")
                if record.get("dataset_identity_hash") != artifact.get(
                    "dataset_identity_hash"
                ):
                    raise ValueError("training shard dataset identity mismatch")
                continue
            if record_type != "sample" or not header_seen:
                raise ValueError("training shard sample precedes valid header")
            sample = _mapping(record.get("sample"), "sample")
            row = _mapping(sample.get("row"), "sample.row")
            decision_at = _require_text(row.get("decision_at"), "decision_at")
            if row.get("dataset_identity_hash") != artifact.get(
                "dataset_identity_hash"
            ):
                raise ValueError("frozen row dataset identity mismatch")
            if row.get("feature_registry_hash") != artifact.get(
                "feature_registry_hash"
            ):
                raise ValueError("frozen row feature registry mismatch")
            features = _mapping_sequence(row.get("features"), "row.features")
            values = _validated_serialized_features(
                features,
                decision_at=decision_at,
                expected_feature_ids=expected_feature_ids,
            )
            yield _NumericRow(
                row_id=_require_text(row.get("row_id"), "row_id"),
                decision_at=decision_at,
                symbol=_require_text(row.get("symbol"), "symbol"),
                values=values,
            )
    if not header_seen:
        raise ValueError("training shard header is missing")


def _validated_serialized_features(
    features: Sequence[Mapping[str, Any]],
    *,
    decision_at: str,
    expected_feature_ids: frozenset[str],
) -> Mapping[str, tuple[int | None, int, bool]]:
    decision = _parse_datetime(decision_at, "decision_at")
    values: dict[str, tuple[int | None, int, bool]] = {}
    for feature in features:
        feature_id = _require_text(feature.get("feature_id"), "feature_id")
        if feature_id in values:
            raise ValueError(f"duplicate feature: {feature_id}")
        available = _parse_datetime(
            _require_text(feature.get("available_at"), "available_at"),
            "available_at",
        )
        if available > decision:
            raise ValueError(f"future feature availability: {feature_id}")
        observed = _require_bool(feature.get("observed"), "observed")
        scale = _require_positive_int(feature.get("scale"), "scale")
        raw_value = feature.get("value_int")
        if observed:
            value_int = _require_int(raw_value, "value_int")
        else:
            if raw_value is not None:
                raise ValueError("unobserved feature must not carry value_int")
            value_int = None
        values[feature_id] = (value_int, scale, observed)
    if set(values) != expected_feature_ids:
        missing = sorted(expected_feature_ids - set(values))
        unknown = sorted(set(values) - expected_feature_ids)
        raise ValueError(
            f"frozen feature contract mismatch; missing={missing[:1]} "
            f"unknown={unknown[:1]}"
        )
    return values


def _validated_runtime_features(
    features: Sequence[PITFeatureValue],
    *,
    decision_at: str,
    expected_feature_ids: frozenset[str],
) -> Mapping[str, tuple[int | None, int, bool]]:
    payloads = [
        {
            "feature_id": feature.feature_id,
            "available_at": feature.available_at,
            "observed": feature.observed,
            "scale": feature.scale,
            "value_int": feature.value_int,
        }
        for feature in features
    ]
    return _validated_serialized_features(
        payloads,
        decision_at=decision_at,
        expected_feature_ids=expected_feature_ids,
    )


def _predict_downside_probabilities_bp(
    *,
    artifact: Mapping[str, Any],
    rows: tuple[_NumericRow, ...],
    feature_packs: tuple[tuple[str, tuple[str, ...]], ...],
    horizon_filter: int | None = None,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if horizon_filter is not None and horizon_filter not in PROMOTION_HORIZONS:
        raise ValueError("unsupported downside probability horizon")
    pack_by_id = dict(feature_packs)
    family_weights = {
        _require_text(item[0], "feature_family_weight.pack_id"): _require_bp(
            item[1],
            "feature_family_weight.weight_bp",
        )
        for item in _pair_sequence(
            artifact.get("feature_family_weights_bp"),
            "feature_family_weights_bp",
        )
    }
    if set(family_weights) != set(pack_by_id):
        raise ValueError("model feature family weights mismatch")
    calibrated_numerators = [0] * len(rows)
    uncalibrated_numerators = [0] * len(rows)
    denominators = [0] * len(rows)
    base_models = _mapping(artifact.get("base_models"), "base_models")
    expert_keys = tuple(
        _require_text(item, "expert_key")
        for item in _sequence(artifact.get("expert_keys"), "expert_keys")
    )
    for expert_key in expert_keys:
        parts = expert_key.split("|")
        if len(parts) != 3:
            raise ValueError(f"invalid expert key: {expert_key}")
        pack_id, raw_horizon, algorithm = parts
        if not raw_horizon.startswith("h"):
            raise ValueError(f"invalid expert horizon: {expert_key}")
        try:
            expert_horizon = int(raw_horizon[1:])
        except ValueError as exc:
            raise ValueError(f"invalid expert horizon: {expert_key}") from exc
        if horizon_filter is not None and expert_horizon != horizon_filter:
            continue
        feature_ids = pack_by_id.get(pack_id)
        if feature_ids is None:
            raise ValueError(f"expert references unknown pack: {pack_id}")
        model_payload = _mapping(base_models.get(expert_key), expert_key)
        missing_reasons = _mapping(
            model_payload.get("head_missing_reasons"),
            f"{expert_key}.head_missing_reasons",
        )
        if "downside_probability_bp" in missing_reasons:
            continue
        classification_models = _mapping(
            model_payload.get("classification_models"),
            f"{expert_key}.classification_models",
        )
        classifier = classification_models.get("downside_probability_bp")
        if classifier is None:
            continue
        active_indices = [
            index
            for index, row in enumerate(rows)
            if any(row.values[feature_id][2] for feature_id in feature_ids)
        ]
        if not active_indices:
            continue
        active_rows = tuple(rows[index] for index in active_indices)
        matrix = _pack_matrix(
            active_rows,
            feature_ids=feature_ids,
            algorithm=algorithm,
        )
        calibrated = _positive_probability_array(
            classifier,
            matrix,
            field_name=f"{expert_key}.calibrated",
        )
        uncalibrated = _uncalibrated_probability_array(
            classifier,
            matrix,
            field_name=f"{expert_key}.uncalibrated",
        )
        weight = family_weights[pack_id]
        for local_index, row_index in enumerate(active_indices):
            calibrated_bp = _quantize_probability_bp(calibrated[local_index])
            uncalibrated_bp = _quantize_probability_bp(
                uncalibrated[local_index]
            )
            calibrated_numerators[row_index] += weight * calibrated_bp
            uncalibrated_numerators[row_index] += weight * uncalibrated_bp
            denominators[row_index] += weight
    calibrated_result = tuple(
        (
            _round_ratio(calibrated_numerators[index], denominators[index])
            if denominators[index]
            else 5_000
        )
        for index in range(len(rows))
    )
    uncalibrated_result = tuple(
        (
            _round_ratio(uncalibrated_numerators[index], denominators[index])
            if denominators[index]
            else 5_000
        )
        for index in range(len(rows))
    )
    return calibrated_result, uncalibrated_result


def _predict_downside_probabilities_by_horizon_bp(
    *,
    artifact: Mapping[str, Any],
    rows: tuple[_NumericRow, ...],
    feature_packs: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[int, tuple[tuple[int, ...], tuple[int, ...]]]:
    horizons = _artifact_horizons(artifact)
    return {
        horizon: _predict_downside_probabilities_bp(
            artifact=artifact,
            rows=rows,
            feature_packs=feature_packs,
            horizon_filter=horizon,
        )
        for horizon in horizons
    }


def _pack_matrix(
    rows: Sequence[_NumericRow],
    *,
    feature_ids: Sequence[str],
    algorithm: str,
) -> NDArray[np.float64]:
    values: list[list[float]] = []
    masks: list[list[float]] = []
    for row in rows:
        value_row: list[float] = []
        mask_row: list[float] = []
        for feature_id in feature_ids:
            value_int, scale, observed = row.values[feature_id]
            if observed:
                assert value_int is not None
                value_row.append(
                    float(value_int) / float(scale)  # numeric-boundary: sklearn
                )
                mask_row.append(0.0)
            else:
                value_row.append(float("nan"))  # numeric-boundary: sklearn
                mask_row.append(1.0)
        values.append(value_row)
        masks.append(mask_row)
    matrix = np.asarray(values, dtype=float)  # numeric-boundary: sklearn
    if algorithm == "hist_gradient_boosting":
        return np.concatenate(
            (matrix, np.asarray(masks, dtype=float)),  # numeric-boundary
            axis=1,
        )
    if algorithm != "ridge_logistic":
        raise ValueError(f"unsupported expert algorithm: {algorithm}")
    return matrix


def _positive_probability_array(
    classifier: object,
    matrix: NDArray[np.float64],
    *,
    field_name: str,
) -> NDArray[np.float64]:
    predictor = getattr(classifier, "predict_proba", None)
    classes = getattr(classifier, "classes_", None)
    if not callable(predictor) or classes is None:
        raise ValueError(f"{field_name} predict_proba contract is unavailable")
    class_values = list(classes)
    if 1 not in class_values:
        raise ValueError(f"{field_name} positive class is unavailable")
    positive_index = class_values.index(1)
    probabilities = np.asarray(
        predictor(matrix),
        dtype=float,  # numeric-boundary: sklearn
    )
    if (
        probabilities.ndim != 2
        or probabilities.shape[0] != len(matrix)
        or probabilities.shape[1] != len(class_values)
        or not np.all(np.isfinite(probabilities))
        or np.any(probabilities < 0)
        or np.any(probabilities > 1)
    ):
        raise ValueError(f"{field_name} probability output is invalid")
    return np.asarray(
        probabilities[:, positive_index],
        dtype=float,  # numeric-boundary: sklearn
    )


def _uncalibrated_probability_array(
    classifier: object,
    matrix: NDArray[np.float64],
    *,
    field_name: str,
) -> NDArray[np.float64]:
    calibrated_folds = getattr(classifier, "calibrated_classifiers_", None)
    if not isinstance(calibrated_folds, list) or not calibrated_folds:
        raise ValueError(
            f"{field_name} uncalibrated fold estimators are unavailable"
        )
    fold_probabilities = []
    for fold_index, calibrated_fold in enumerate(calibrated_folds):
        estimator = getattr(calibrated_fold, "estimator", None)
        if estimator is None:
            raise ValueError(
                f"{field_name} fold {fold_index} estimator is unavailable"
            )
        fold_probabilities.append(
            _positive_probability_array(
                estimator,
                matrix,
                field_name=f"{field_name}.fold[{fold_index}]",
            )
        )
    return np.mean(
        np.vstack(fold_probabilities),
        axis=0,
        dtype=float,  # numeric-boundary: sklearn
    )


def _feature_packs(
    artifact: Mapping[str, Any],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    packs = _pair_sequence(artifact.get("feature_packs"), "feature_packs")
    result: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for pack_id_raw, feature_ids_raw in packs:
        pack_id = _require_text(pack_id_raw, "pack_id")
        feature_ids = tuple(
            _require_text(item, "feature_id")
            for item in _sequence(feature_ids_raw, f"{pack_id}.feature_ids")
        )
        if not feature_ids:
            raise ValueError(f"feature pack is empty: {pack_id}")
        if seen & set(feature_ids):
            raise ValueError("features must belong to exactly one pack")
        seen.update(feature_ids)
        result.append((pack_id, feature_ids))
    if tuple(pack_id for pack_id, _ in result) != tuple(
        sorted(pack_id for pack_id, _ in result)
    ):
        raise ValueError("feature packs must use canonical order")
    return tuple(result)


def _artifact_horizons(artifact: Mapping[str, Any]) -> tuple[int, ...]:
    horizons: set[int] = set()
    expert_keys = _sequence(artifact.get("expert_keys"), "expert_keys")
    if not expert_keys:
        raise ValueError("model artifact has no expert keys")
    for raw_key in expert_keys:
        expert_key = _require_text(raw_key, "expert_key")
        parts = expert_key.split("|")
        if len(parts) != 3:
            raise ValueError(f"invalid expert key: {expert_key}")
        raw_horizon = parts[1]
        if not raw_horizon.startswith("h"):
            raise ValueError(f"invalid expert horizon: {expert_key}")
        try:
            horizon = int(raw_horizon[1:])
        except ValueError as exc:
            raise ValueError(f"invalid expert horizon: {expert_key}") from exc
        if horizon <= 0:
            raise ValueError(f"invalid expert horizon: {expert_key}")
        horizons.add(horizon)
    return tuple(sorted(horizons))


def _feature_metadata(
    dataset: Mapping[str, Any],
    feature_packs: tuple[tuple[str, tuple[str, ...]], ...],
) -> Mapping[str, Mapping[str, object]]:
    registry = _mapping(dataset.get("feature_registry"), "feature_registry")
    features = _mapping_sequence(registry.get("features"), "registry.features")
    metadata = {
        _require_text(item.get("feature_id"), "feature_id"): {
            "family_id": _require_text(item.get("family_id"), "family_id"),
            "source_id": _require_text(item.get("source_id"), "source_id"),
            "scale": _require_positive_int(item.get("scale"), "scale"),
        }
        for item in features
    }
    expected = {
        feature_id: pack_id
        for pack_id, feature_ids in feature_packs
        for feature_id in feature_ids
    }
    if set(metadata) - set(expected):
        raise ValueError("feature registry exceeds frozen model feature set")
    missing_metadata = set(expected) - set(metadata)
    if any(expected[feature_id] != "data_quality" for feature_id in missing_metadata):
        raise ValueError("non-derived frozen feature metadata is missing")
    for feature_id in missing_metadata:
        metadata[feature_id] = {
            "family_id": "data_quality",
            "source_id": "derived:feature_quality",
            "scale": 1,
        }
    for feature_id, pack_id in expected.items():
        if metadata[feature_id]["family_id"] != pack_id:
            raise ValueError(f"feature family mismatch: {feature_id}")
    return metadata


def _normalize_manifest_packs(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            _require_text(item.get("pack_id"), "pack_id"),
            tuple(
                _require_text(feature_id, "feature_id")
                for feature_id in _sequence(
                    item.get("feature_ids"),
                    "feature_ids",
                )
            ),
        )
        for item in _mapping_sequence(value, "feature_packs")
    )


def _normalize_artifact_packs(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            _require_text(pack_id, "pack_id"),
            tuple(
                _require_text(feature_id, "feature_id")
                for feature_id in _sequence(feature_ids, "feature_ids")
            ),
        )
        for pack_id, feature_ids in _pair_sequence(value, "feature_packs")
    )


def _quantile_cut_points(
    values: Sequence[int],
    *,
    bin_count: int,
) -> tuple[int, ...]:
    if not values:
        return ()
    ordered = sorted(values)
    cuts = {
        ordered[min(len(ordered) - 1, (len(ordered) * index) // bin_count)]
        for index in range(1, bin_count)
    }
    return tuple(sorted(cuts))


def _histogram_counts(
    values: Sequence[int],
    *,
    upper_bounds: Sequence[int],
    missing_count: int,
    append_missing_bucket: bool = True,
) -> list[int]:
    counts = [0] * (len(upper_bounds) + 1)
    for value in values:
        counts[bisect_right(upper_bounds, value)] += 1
    if append_missing_bucket:
        counts.append(
            _require_nonnegative_int(missing_count, "missing_count")
        )
    elif missing_count != 0:
        raise ValueError("missing_count requires an explicit missing bucket")
    return counts


def _runtime_feature_snapshot_hash(row: PortfolioMLDatasetRow) -> str:
    return _payload_hash(
        {
            "row_id": row.row_id,
            "decision_at": row.decision_at,
            "symbol": row.symbol,
            "features": [
                {
                    "feature_id": feature.feature_id,
                    "family_id": feature.family_id,
                    "source_id": feature.source_id,
                    "value_int": feature.value_int,
                    "scale": feature.scale,
                    "event_at": feature.event_at,
                    "available_at": feature.available_at,
                    "revision_id": feature.revision_id,
                    "quality": feature.quality,
                    "content_hash": feature.content_hash,
                    "observed": feature.observed,
                    "event_time_semantics": feature.event_time_semantics,
                }
                for feature in sorted(
                    row.features,
                    key=lambda item: item.feature_id,
                )
            ],
            "portfolio_state_hash": row.portfolio_state.state_hash,
            "dataset_identity_hash": row.dataset_identity_hash,
            "feature_registry_hash": row.feature_registry_hash,
            "source_manifest_hashes": [
                [source_id, source_hash]
                for source_id, source_hash in row.source_manifest_hashes
            ],
        }
    )


def _load_model_artifact(
    path: Path,
    *,
    expected_hash: str,
) -> Mapping[str, Any]:
    _require_sha256(expected_hash, "expected_model_artifact_hash")
    if _file_hash(path) != expected_hash:
        raise ValueError("model artifact file hash mismatch")
    try:
        payload = joblib.load(path)
    except Exception as exc:
        raise ValueError("model artifact deserialization failed") from exc
    return _mapping(payload, "model artifact")


def _validate_dataset_manifest_hash(dataset: Mapping[str, Any]) -> None:
    expected = _require_sha256(dataset.get("manifest_hash"), "manifest_hash")
    body = dict(dataset)
    body.pop("manifest_hash", None)
    if _payload_hash(body) != expected:
        raise ValueError("dataset manifest canonical hash mismatch")


def _accumulate_counts(
    target: dict[str, list[int]],
    key: str,
    values: tuple[int, ...],
) -> None:
    if key not in target:
        target[key] = list(values)
        return
    if len(target[key]) != len(values):
        raise ValueError(f"current distribution bucket width mismatch: {key}")
    target[key] = [
        prior + current
        for prior, current in zip(target[key], values, strict=True)
    ]


def _canonical_hash_pairs(value: object, field_name: str) -> list[list[str]]:
    pairs = [
        [
            _require_text(item[0], f"{field_name}.source_id"),
            _require_sha256(item[1], f"{field_name}.source_hash"),
        ]
        for item in _pair_sequence(value, field_name)
    ]
    if pairs != sorted(pairs):
        raise ValueError(f"{field_name} must use canonical order")
    if len({item[0] for item in pairs}) != len(pairs):
        raise ValueError(f"{field_name} source ids must be unique")
    return pairs


def _quantize_probability_bp(value: object) -> int:
    numeric = float(cast(Any, value))  # numeric-boundary: sklearn
    if not np.isfinite(numeric):
        raise ValueError("model probability must be finite")
    bounded = max(0.0, min(1.0, numeric))
    return int(
        Decimal(str(bounded * 10_000.0)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _round_ratio(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("rounding denominator must be positive")
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _read_json_object(path: Path, field_name: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{field_name} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} must be UTF-8 JSON") from exc
    return _mapping(payload, field_name)


def _atomic_write_immutable_json(
    path: Path,
    payload: Mapping[str, object],
) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"immutable artifact already differs: {path}")
        return
    _atomic_write_bytes(path, encoded)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_write_bytes(path, encoded)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".staged",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with open(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed


def _parse_iso_date(value: object, field_name: str) -> date:
    text = _require_text(value, field_name)
    try:
        return datetime.fromisoformat(f"{text}T00:00:00").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return cast(Mapping[str, Any], value)


def _mapping_sequence(
    value: object,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        _mapping(item, f"{field_name}[]")
        for item in _sequence(value, field_name)
    )


def _pair_sequence(
    value: object,
    field_name: str,
) -> tuple[tuple[object, object], ...]:
    pairs: list[tuple[object, object]] = []
    for item in _sequence(value, field_name):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{field_name} entries must be two-item arrays")
        pairs.append((item[0], item[1]))
    return tuple(pairs)


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an array")
    return cast(Sequence[object], value)


def _integer_tuple(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[int, ...]:
    result = tuple(
        _require_nonnegative_int(item, field_name)
        for item in _sequence(value, field_name)
    )
    if not result and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _signed_integer_tuple(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[int, ...]:
    result = tuple(
        _require_int(item, field_name)
        for item in _sequence(value, field_name)
    )
    if not result and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_sha256(value: object, field_name: str) -> str:
    text = _require_text(value, field_name)
    if (
        not text.startswith(_SHA256_PREFIX)
        or len(text) != 71
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
    return text


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _require_nonnegative_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return integer


def _require_positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise ValueError(f"{field_name} must be positive")
    return integer


def _require_bp(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if not 0 <= integer <= TOTAL_BP:
        raise ValueError(f"{field_name} must be within 0..10000 bp")
    return integer


def _require_binary(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer not in {0, 1}:
        raise ValueError(f"{field_name} must be 0 or 1")
    return integer


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value
