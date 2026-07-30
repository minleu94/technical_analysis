"""配置型 ML 的唯讀、雜湊綁定正式推論邊界。

本服務只載入已由 :mod:`ml_module.allocation_training_service` 產生的 frozen
artifact，並把模型輸出量化為整數 bp 的 ``MLAllocationSignalRow`` 與
``MLAllocationProposal``。它不讀寫 Portfolio、Advice、Rule、promotion
registry 或 broker，也不能授權非零 alpha。

``joblib`` 只能在 artifact bytes 先通過呼叫端提供的 SHA-256 後反序列化；
因此 ``expected_artifact_hash`` 必須來自受控訓練 manifest，而不是與 artifact
放在同一個未受信任 payload 內。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Mapping, Sequence, cast
from zoneinfo import ZoneInfo

import joblib
import numpy as np
from numpy.typing import NDArray

from app_module.portfolio_allocation_dtos import (
    TOTAL_WEIGHT_BP,
    AllocationWeightContract,
    MLAllocationProposal,
    MLAllocationSignalRow,
)
from financial_module.portfolio_turnover import canonical_turnover_bp
from ml_module.allocation_contracts import PITFeatureValue, PortfolioMLDatasetRow
from ml_module.allocation_training_service import (
    ARTIFACT_SCHEMA_VERSION,
    CLASSIFICATION_EXPERT_HEADS,
    EXPERT_ALGORITHMS,
    EXPERT_HEAD_IDS,
    EXPERT_VECTOR_WIDTH,
    REGRESSION_EXPERT_HEADS,
)


_TAIPEI = ZoneInfo("Asia/Taipei")
_META_NUMERIC_FIELDS = (
    "target_weight_bp",
    "delta_weight_bp",
    "risk_contribution_bp",
    "risky_budget_bp",
    "cash_bp",
)
_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_schema_version",
        "dataset_id",
        "dataset_identity_hash",
        "dataset_manifest_file_hash",
        "feature_registry_hash",
        "source_manifest_hashes",
        "training_as_of",
        "feature_packs",
        "horizons",
        "expert_keys",
        "expert_head_ids",
        "expert_vector_width",
        "base_models",
        "meta_models",
        "feature_family_weights_bp",
        "production_alpha_bp",
        "production_action_allowed",
        "formal_oos_allowed",
        "broker_order_allowed",
    }
)


@dataclass(frozen=True)
class MLAllocationInferenceResult:
    """原子落盤所需的 proposal 與 deterministic audit。"""

    proposal: MLAllocationProposal
    proposal_hash: str
    replay_hash: str
    audit_json: str
    formal_oos_allowed: bool = False
    production_action_allowed: bool = False
    production_blend_alpha_bp: int = 0

    def __post_init__(self) -> None:
        _require_sha256(self.proposal_hash, field_name="proposal_hash")
        _require_sha256(self.replay_hash, field_name="replay_hash")
        try:
            payload = json.loads(self.audit_json)
        except json.JSONDecodeError as exc:
            raise ValueError("audit_json must be valid JSON") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("proposal_hash") != self.proposal_hash
            or payload.get("replay_hash") != self.replay_hash
        ):
            raise ValueError("audit_json does not match inference result hashes")
        if (
            self.formal_oos_allowed is not False
            or self.production_action_allowed is not False
            or self.production_blend_alpha_bp != 0
        ):
            raise ValueError("inference result cannot authorize production allocation")

    def audit_payload(self) -> Mapping[str, Any]:
        payload = json.loads(self.audit_json)
        if not isinstance(payload, dict):
            raise ValueError("audit_json must contain an object")
        return payload


@dataclass(frozen=True)
class _FeaturePack:
    pack_id: str
    feature_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ArtifactContract:
    dataset_id: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    feature_registry_hash: str
    source_manifest_hashes: tuple[tuple[str, str], ...]
    training_as_of: str
    feature_packs: tuple[_FeaturePack, ...]
    horizons: tuple[int, ...]
    expert_keys: tuple[str, ...]
    base_models: Mapping[str, Any]
    meta_models: Mapping[str, Any]
    feature_family_weights_bp: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class _ExpertOutput:
    expected_excess_return_bp: int
    expected_sector_excess_return_bp: int | None
    downside_probability_bp: int
    uncalibrated_downside_probability_bp: int
    predicted_mae_bp: int
    predicted_mfe_bp: int
    predicted_realized_volatility_bp: int
    predicted_max_drawdown_bp: int
    predicted_tail_loss_bp: int
    fill_feasibility_probability_bp: int
    rank_bp: int
    missing_head_ids: tuple[str, ...]
    neutral_fallback: bool


@dataclass(frozen=True)
class _MetaOutput:
    target_weight_bp: int
    delta_weight_bp: int
    risk_contribution_bp: int
    risky_budget_bp: int
    cash_bp: int
    rebalance_probability_bp: int
    rebalance_worthwhile: bool


class MLAllocationInferenceService:
    """對 frozen 配置模型執行單一 decision timestamp 的唯讀推論。"""

    def __init__(
        self,
        *,
        artifact_bytes: bytes,
        expected_artifact_hash: str,
        expected_dataset_id: str,
    ) -> None:
        if not isinstance(artifact_bytes, bytes) or not artifact_bytes:
            raise TypeError("artifact_bytes must be non-empty bytes")
        _require_sha256(
            expected_artifact_hash,
            field_name="expected_artifact_hash",
        )
        _require_text(
            expected_dataset_id=expected_dataset_id,
        )
        actual_hash = _sha256(artifact_bytes)
        if actual_hash != expected_artifact_hash:
            raise ValueError("artifact hash mismatch")

        try:
            raw_payload = joblib.load(BytesIO(artifact_bytes))
        except Exception as exc:
            raise ValueError("artifact deserialization failed") from exc
        artifact = _parse_artifact(raw_payload)
        if artifact.dataset_id != expected_dataset_id:
            raise ValueError("artifact dataset_id mismatch")

        self._artifact_hash = actual_hash
        self._artifact = artifact

    @classmethod
    def from_artifact_path(
        cls,
        artifact_path: str | Path,
        *,
        expected_artifact_hash: str,
        expected_dataset_id: str,
    ) -> "MLAllocationInferenceService":
        path = Path(artifact_path)
        if not path.is_file():
            raise FileNotFoundError(f"model artifact is missing: {path}")
        return cls(
            artifact_bytes=path.read_bytes(),
            expected_artifact_hash=expected_artifact_hash,
            expected_dataset_id=expected_dataset_id,
        )

    @property
    def artifact_hash(self) -> str:
        return self._artifact_hash

    @property
    def dataset_id(self) -> str:
        return self._artifact.dataset_id

    def infer(
        self,
        *,
        rows: Sequence[PortfolioMLDatasetRow],
        model_id: str,
        universe_id: str,
        policy_id: str,
        policy_hash: str,
        expected_universe_hash: str | None = None,
    ) -> MLAllocationInferenceResult:
        """產生不具 alpha、apply 或 broker 權限的配置提案。"""

        _require_text(
            model_id=model_id,
            universe_id=universe_id,
            policy_id=policy_id,
        )
        _require_sha256(policy_hash, field_name="policy_hash")
        if expected_universe_hash is not None:
            _require_sha256(
                expected_universe_hash,
                field_name="expected_universe_hash",
            )

        canonical_rows, decision_at = self._validate_rows(rows)
        feature_snapshot_hashes = {
            row.row_id: _feature_snapshot_hash(row) for row in canonical_rows
        }
        universe_hash = _sha256_json(
            [
                {
                    "row_id": row.row_id,
                    "symbol": row.symbol,
                    "feature_snapshot_hash": feature_snapshot_hashes[row.row_id],
                }
                for row in canonical_rows
            ]
        )
        if (
            expected_universe_hash is not None
            and universe_hash != expected_universe_hash
        ):
            raise ValueError("inference universe hash mismatch")

        pack_coverage = self._pack_coverage(canonical_rows)
        expert_outputs = self._predict_experts(
            rows=canonical_rows,
            pack_coverage=pack_coverage,
        )
        row_coverage_bp = {
            row.row_id: self._row_coverage_bp(
                pack_coverage=pack_coverage[row.row_id]
            )
            for row in canonical_rows
        }
        meta_outputs = self._predict_meta(
            rows=canonical_rows,
            expert_outputs=expert_outputs,
            row_coverage_bp=row_coverage_bp,
        )

        signals = tuple(
            self._signal_for_row(
                row=row,
                feature_snapshot_hash=feature_snapshot_hashes[row.row_id],
                pack_coverage=pack_coverage[row.row_id],
                expert_outputs=expert_outputs[row.row_id],
                coverage_bp=row_coverage_bp[row.row_id],
            )
            for row in canonical_rows
        )
        requested_weights, allocation_reason = self._requested_weights(
            rows=canonical_rows,
            meta_outputs=meta_outputs,
            row_coverage_bp=row_coverage_bp,
        )
        overall_coverage_bp = _round_ratio(
            sum(row_coverage_bp.values()),
            len(row_coverage_bp),
        )
        missing_family_ids = tuple(
            sorted(
                {
                    family_id
                    for row in canonical_rows
                    for family_id in row.missing_family_ids
                }
            )
        )
        fallback_reason: str | None
        if overall_coverage_bp == 0:
            fallback_reason = "all_feature_packs_missing_cash_only"
        elif missing_family_ids:
            fallback_reason = "feature_pack_missing_or_partial_missing_mask"
        else:
            fallback_reason = None

        reasons = {
            "ml_inference_only_no_alpha_authority",
            "transaction_cost_deferred_to_portfolio_projection",
        }
        if allocation_reason is not None:
            reasons.add(allocation_reason)
        for row in signals:
            reasons.update(row.reasons)

        current_state = canonical_rows[0].portfolio_state.weights
        estimated_turnover_bp = _turnover_bp(
            current_positions=dict(current_state.positions_bp),
            current_cash_bp=current_state.cash_bp,
            requested=requested_weights,
        )
        proposal = MLAllocationProposal(
            decision_date=decision_at.date().isoformat(),
            model_id=model_id,
            dataset_id=self._artifact.dataset_id,
            universe_id=universe_id,
            policy_id=policy_id,
            requested_weights=requested_weights,
            model_hash=self._artifact_hash,
            dataset_identity_hash=self._artifact.dataset_identity_hash,
            dataset_manifest_file_hash=(
                self._artifact.dataset_manifest_file_hash
            ),
            universe_hash=universe_hash,
            policy_hash=policy_hash,
            coverage_bp=overall_coverage_bp,
            feature_family_weights_bp=dict(
                self._artifact.feature_family_weights_bp
            ),
            estimated_turnover_bp=estimated_turnover_bp,
            estimated_transaction_cost=Decimal("0"),
            fallback_reason=fallback_reason,
            signals=signals,
            missing_family_ids=missing_family_ids,
            reasons=tuple(sorted(reasons)),
            formal_oos_allowed=False,
            production_action_allowed=False,
            production_blend_alpha_bp=0,
            broker_order_allowed=False,
        )
        proposal_payload = proposal.to_dict()
        proposal_hash = _sha256_json(proposal_payload)
        audit_without_replay_hash = {
            "schema_version": "ml-allocation-inference-audit-v3",
            "decision_at": decision_at.isoformat(),
            "model_id": model_id,
            "model_artifact_hash": self._artifact_hash,
            "dataset_id": self._artifact.dataset_id,
            "dataset_identity_hash": self._artifact.dataset_identity_hash,
            "dataset_manifest_file_hash": (
                self._artifact.dataset_manifest_file_hash
            ),
            "feature_registry_hash": self._artifact.feature_registry_hash,
            "source_manifest_hashes": [
                [source_id, source_hash]
                for source_id, source_hash in self._artifact.source_manifest_hashes
            ],
            "training_as_of": self._artifact.training_as_of,
            "universe_id": universe_id,
            "universe_hash": universe_hash,
            "policy_id": policy_id,
            "policy_hash": policy_hash,
            "feature_family_weights_bp": [
                [family_id, weight_bp]
                for family_id, weight_bp in self._artifact.feature_family_weights_bp
            ],
            "row_audits": [
                {
                    "row_id": row.row_id,
                    "symbol": row.symbol,
                    "feature_snapshot_hash": feature_snapshot_hashes[row.row_id],
                    "coverage_bp": row_coverage_bp[row.row_id],
                    "missing_family_ids": list(row.missing_family_ids),
                    "base_expert_outputs": {
                        expert_key: _expert_output_payload(
                            expert_outputs[row.row_id][expert_key]
                        )
                        for expert_key in self._artifact.expert_keys
                    },
                    "downside_probability_by_horizon_bp": (
                        self._downside_probability_by_horizon(
                            expert_outputs[row.row_id]
                        )
                    ),
                    "meta_output": {
                        "target_weight_bp": meta_outputs[
                            row.row_id
                        ].target_weight_bp,
                        "delta_weight_bp": meta_outputs[
                            row.row_id
                        ].delta_weight_bp,
                        "risk_contribution_bp": meta_outputs[
                            row.row_id
                        ].risk_contribution_bp,
                        "risky_budget_bp": meta_outputs[
                            row.row_id
                        ].risky_budget_bp,
                        "cash_bp": meta_outputs[row.row_id].cash_bp,
                        "rebalance_probability_bp": meta_outputs[
                            row.row_id
                        ].rebalance_probability_bp,
                        "rebalance_worthwhile": meta_outputs[
                            row.row_id
                        ].rebalance_worthwhile,
                    },
                }
                for row in canonical_rows
            ],
            "proposal_hash": proposal_hash,
            "fallback_reason": fallback_reason,
            "formal_oos_allowed": False,
            "production_action_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
            "not_performed": [
                "promotion_authorization",
                "rule_weight_blend",
                "portfolio_risk_projection",
                "advice_composition",
                "broker_order_routing",
            ],
        }
        replay_hash = _sha256_json(audit_without_replay_hash)
        audit_payload = {
            **audit_without_replay_hash,
            "replay_hash": replay_hash,
        }
        audit_json = _canonical_json(audit_payload)
        return MLAllocationInferenceResult(
            proposal=proposal,
            proposal_hash=proposal_hash,
            replay_hash=replay_hash,
            audit_json=audit_json,
        )

    def _validate_rows(
        self,
        rows: Sequence[PortfolioMLDatasetRow],
    ) -> tuple[tuple[PortfolioMLDatasetRow, ...], datetime]:
        if not rows:
            raise ValueError("inference rows are required")
        if any(not isinstance(row, PortfolioMLDatasetRow) for row in rows):
            raise TypeError("rows must contain PortfolioMLDatasetRow values")

        row_ids = tuple(row.row_id for row in rows)
        symbols = tuple(row.symbol for row in rows)
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("inference row ids must be unique")
        if len(symbols) != len(set(symbols)):
            raise ValueError("inference symbols must be unique")
        canonical = tuple(sorted(rows, key=lambda row: row.symbol))
        decision_at = _parse_decision_at(canonical[0].decision_at)
        if any(_parse_decision_at(row.decision_at) != decision_at for row in canonical):
            raise ValueError("all inference rows must share one decision_at")
        training_as_of = _parse_available_at(
            self._artifact.training_as_of,
            field_name="training_as_of",
        )
        if training_as_of > decision_at:
            raise ValueError("model training_as_of exceeds inference decision_at")

        expected_features = {
            feature_id: pack.pack_id
            for pack in self._artifact.feature_packs
            for feature_id in pack.feature_ids
        }
        expected_feature_ids = set(expected_features)
        expected_family_ids = {
            pack.pack_id for pack in self._artifact.feature_packs
        }
        expected_state = canonical[0].portfolio_state
        for row in canonical:
            if row.targets is not None:
                raise ValueError(
                    "inference rows must not contain supervised AllocationTargets"
                )
            if row.dataset_identity_hash != self._artifact.dataset_identity_hash:
                raise ValueError("dataset identity hash mismatch")
            if row.feature_registry_hash != self._artifact.feature_registry_hash:
                raise ValueError("feature registry hash mismatch")
            if row.source_manifest_hashes != self._artifact.source_manifest_hashes:
                raise ValueError("source manifest hashes mismatch")
            if row.portfolio_state != expected_state:
                raise ValueError("inference rows must share one causal portfolio state")
            feature_by_id = {
                feature.feature_id: feature for feature in row.features
            }
            if set(feature_by_id) != expected_feature_ids:
                raise ValueError(
                    "inference feature ids must exactly match the frozen artifact"
                )
            for feature_id, feature in feature_by_id.items():
                if feature.family_id != expected_features[feature_id]:
                    raise ValueError(
                        f"feature family mismatch for {feature_id}"
                    )
                if _parse_available_at(
                    feature.available_at,
                    field_name=f"{feature_id}.available_at",
                ) > decision_at:
                    raise ValueError(
                        f"future feature available_at exceeds decision_at: {feature_id}"
                    )
            unobserved_family_ids = {
                feature.family_id
                for feature in row.features
                if not feature.observed
            }
            if set(row.missing_family_ids) != unobserved_family_ids:
                raise ValueError(
                    "missing_family_ids must exactly match unobserved feature families"
                )
            if not set(row.missing_family_ids).issubset(expected_family_ids):
                raise ValueError("row contains an unknown missing feature family")

        current_symbols = {
            symbol for symbol, _ in expected_state.weights.positions_bp
        }
        if not current_symbols.issubset(set(symbols)):
            raise ValueError(
                "every current position requires an inference row; silent exit is forbidden"
            )
        return canonical, decision_at

    def _pack_coverage(
        self,
        rows: tuple[PortfolioMLDatasetRow, ...],
    ) -> dict[str, dict[str, tuple[int, int]]]:
        result: dict[str, dict[str, tuple[int, int]]] = {}
        for row in rows:
            feature_by_id = {
                feature.feature_id: feature for feature in row.features
            }
            result[row.row_id] = {
                pack.pack_id: (
                    sum(
                        feature_by_id[feature_id].observed
                        for feature_id in pack.feature_ids
                    ),
                    len(pack.feature_ids),
                )
                for pack in self._artifact.feature_packs
            }
        return result

    def _predict_experts(
        self,
        *,
        rows: tuple[PortfolioMLDatasetRow, ...],
        pack_coverage: Mapping[str, Mapping[str, tuple[int, int]]],
    ) -> dict[str, dict[str, _ExpertOutput]]:
        result: dict[str, dict[str, _ExpertOutput]] = {
            row.row_id: {} for row in rows
        }
        pack_by_id = {
            pack.pack_id: pack for pack in self._artifact.feature_packs
        }
        for expert_key in self._artifact.expert_keys:
            pack_id, _, algorithm = expert_key.split("|", 2)
            pack = pack_by_id[pack_id]
            active_rows = tuple(
                row
                for row in rows
                if pack_coverage[row.row_id][pack_id][0] > 0
            )
            for row in rows:
                if row not in active_rows:
                    result[row.row_id][expert_key] = _ExpertOutput(
                        expected_excess_return_bp=0,
                        expected_sector_excess_return_bp=None,
                        downside_probability_bp=5_000,
                        uncalibrated_downside_probability_bp=5_000,
                        predicted_mae_bp=10_000,
                        predicted_mfe_bp=0,
                        predicted_realized_volatility_bp=10_000,
                        predicted_max_drawdown_bp=10_000,
                        predicted_tail_loss_bp=10_000,
                        fill_feasibility_probability_bp=5_000,
                        rank_bp=5_000,
                        missing_head_ids=EXPERT_HEAD_IDS,
                        neutral_fallback=True,
                    )
            if not active_rows:
                continue

            model_payload = self._artifact.base_models[expert_key]
            matrix = _pack_matrix(
                active_rows,
                pack=pack,
                algorithm=algorithm,
            )
            head_values: dict[str, tuple[int | None, ...]] = {}
            regression_models = model_payload["regression_models"]
            for head_id in REGRESSION_EXPERT_HEADS:
                model = regression_models[head_id]
                if model is None:
                    fallback: int | None = (
                        None
                        if head_id == "expected_sector_excess_return_bp"
                        else 0
                    )
                    head_values[head_id] = tuple(
                        fallback for _ in active_rows
                    )
                    continue
                raw_prediction = _predict_array(
                    model,
                    matrix,
                    method_name="predict",
                    field_name=f"{expert_key}.{head_id}",
                )
                quantizer = (
                    _quantize_signed_bp
                    if head_id
                    in {
                        "expected_excess_return_bp",
                        "expected_sector_excess_return_bp",
                    }
                    else _quantize_bounded_bp
                )
                head_values[head_id] = tuple(
                    quantizer(value) for value in raw_prediction
                )

            classification_models = model_payload[
                "classification_models"
            ]
            uncalibrated_downside_values = tuple(5_000 for _ in active_rows)
            for head_id in CLASSIFICATION_EXPERT_HEADS:
                model = classification_models[head_id]
                if model is None:
                    head_values[head_id] = tuple(
                        5_000 for _ in active_rows
                    )
                    continue
                raw_probability = _predict_probability_array(
                    model,
                    matrix,
                    field_name=f"{expert_key}.{head_id}",
                )
                head_values[head_id] = tuple(
                    _quantize_probability_bp(value)
                    for value in raw_probability
                )
                if head_id == "downside_probability_bp":
                    uncalibrated_probability = (
                        _predict_uncalibrated_probability_array(
                            model,
                            matrix,
                            field_name=(
                                f"{expert_key}."
                                "uncalibrated_downside_probability_bp"
                            ),
                        )
                    )
                    uncalibrated_downside_values = tuple(
                        _quantize_probability_bp(value)
                        for value in uncalibrated_probability
                    )

            quantized_expected = tuple(
                _inference_int(
                    value,
                    field_name="expected_excess_return_bp",
                )
                for value in head_values["expected_excess_return_bp"]
            )
            rank_by_row_id = _rank_bp(
                rows=active_rows,
                predicted_values=quantized_expected,
            )
            missing_head_ids = tuple(
                sorted(model_payload["head_missing_reasons"])
            )
            for index, row in enumerate(active_rows):
                result[row.row_id][expert_key] = _ExpertOutput(
                    expected_excess_return_bp=quantized_expected[index],
                    expected_sector_excess_return_bp=_inference_optional_int(
                        head_values[
                            "expected_sector_excess_return_bp"
                        ][index],
                        field_name="expected_sector_excess_return_bp",
                    ),
                    downside_probability_bp=_inference_int(
                        head_values["downside_probability_bp"][index],
                        field_name="downside_probability_bp",
                    ),
                    uncalibrated_downside_probability_bp=_inference_int(
                        uncalibrated_downside_values[index],
                        field_name=(
                            "uncalibrated_downside_probability_bp"
                        ),
                    ),
                    predicted_mae_bp=_inference_int(
                        head_values["predicted_mae_bp"][index],
                        field_name="predicted_mae_bp",
                    ),
                    predicted_mfe_bp=_inference_int(
                        head_values["predicted_mfe_bp"][index],
                        field_name="predicted_mfe_bp",
                    ),
                    predicted_realized_volatility_bp=_inference_int(
                        head_values[
                            "predicted_realized_volatility_bp"
                        ][index],
                        field_name="predicted_realized_volatility_bp",
                    ),
                    predicted_max_drawdown_bp=_inference_int(
                        head_values["predicted_max_drawdown_bp"][index],
                        field_name="predicted_max_drawdown_bp",
                    ),
                    predicted_tail_loss_bp=_inference_int(
                        head_values["predicted_tail_loss_bp"][index],
                        field_name="predicted_tail_loss_bp",
                    ),
                    fill_feasibility_probability_bp=_inference_int(
                        head_values[
                            "fill_feasibility_probability_bp"
                        ][index],
                        field_name="fill_feasibility_probability_bp",
                    ),
                    rank_bp=rank_by_row_id[row.row_id],
                    missing_head_ids=missing_head_ids,
                    neutral_fallback=False,
                )
        return result

    def _predict_meta(
        self,
        *,
        rows: tuple[PortfolioMLDatasetRow, ...],
        expert_outputs: Mapping[str, Mapping[str, _ExpertOutput]],
        row_coverage_bp: Mapping[str, int],
    ) -> dict[str, _MetaOutput]:
        result: dict[str, _MetaOutput] = {}
        active_rows = tuple(row for row in rows if row_coverage_bp[row.row_id] > 0)
        for row in rows:
            if row not in active_rows:
                result[row.row_id] = _MetaOutput(
                    target_weight_bp=0,
                    delta_weight_bp=0,
                    risk_contribution_bp=0,
                    risky_budget_bp=0,
                    cash_bp=10_000,
                    rebalance_probability_bp=0,
                    rebalance_worthwhile=False,
                )
        if not active_rows:
            return result

        matrix = np.asarray(
            [
                [
                    value
                    for expert_key in self._artifact.expert_keys
                    for value in _expert_vector(
                        expert_outputs[row.row_id][expert_key]
                    )
                ]
                for row in active_rows
            ],
            dtype=float,  # numeric-boundary: analytics
        )
        numeric_models = self._artifact.meta_models["numeric"]
        numeric_predictions = {
            field_name: _predict_array(
                numeric_models[field_name],
                matrix,
                method_name="predict",
                field_name=f"meta.{field_name}",
            )
            for field_name in _META_NUMERIC_FIELDS
        }
        rebalance_probability = _predict_probability_array(
            self._artifact.meta_models["rebalance"],
            matrix,
            field_name="meta.rebalance_probability",
        )
        for index, row in enumerate(active_rows):
            rebalance_bp = _quantize_probability_bp(
                rebalance_probability[index]
            )
            result[row.row_id] = _MetaOutput(
                target_weight_bp=_quantize_bounded_bp(
                    numeric_predictions["target_weight_bp"][index]
                ),
                delta_weight_bp=_quantize_signed_bp(
                    numeric_predictions["delta_weight_bp"][index]
                ),
                risk_contribution_bp=_quantize_bounded_bp(
                    numeric_predictions["risk_contribution_bp"][index]
                ),
                risky_budget_bp=_quantize_bounded_bp(
                    numeric_predictions["risky_budget_bp"][index]
                ),
                cash_bp=_quantize_bounded_bp(
                    numeric_predictions["cash_bp"][index]
                ),
                rebalance_probability_bp=rebalance_bp,
                rebalance_worthwhile=rebalance_bp >= 5_000,
            )
        return result

    def _row_coverage_bp(
        self,
        *,
        pack_coverage: Mapping[str, tuple[int, int]],
    ) -> int:
        family_weights = dict(self._artifact.feature_family_weights_bp)
        exact = Decimal("0")
        for pack in self._artifact.feature_packs:
            observed, total = pack_coverage[pack.pack_id]
            exact += (
                Decimal(family_weights[pack.pack_id])
                * Decimal(observed)
                / Decimal(total)
            )
        return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))

    def _downside_probability_by_horizon(
        self,
        expert_outputs: Mapping[str, _ExpertOutput],
    ) -> dict[str, dict[str, int]]:
        """以 family weight 在每個 horizon 內聚合 calibrated/raw 機率。

        此輸出只進 deterministic inference audit，不改變既有
        ``MLAllocationSignalRow`` 的跨 horizon 配置訊號。Horizon 間不可先
        混合再拿同一個 outcome 評估，否則 calibration label 語意會錯位。
        """

        family_weights = dict(self._artifact.feature_family_weights_bp)
        result: dict[str, dict[str, int]] = {}
        for horizon in self._artifact.horizons:
            eligible: list[tuple[int, _ExpertOutput]] = []
            for expert_key in self._artifact.expert_keys:
                pack_id, raw_horizon, _algorithm = expert_key.split("|", 2)
                if raw_horizon != f"h{horizon}":
                    continue
                output = expert_outputs[expert_key]
                if output.neutral_fallback:
                    continue
                eligible.append((family_weights[pack_id], output))
            result[str(horizon)] = {
                "calibrated_downside_probability_bp": (
                    _weighted_expert_head(
                        eligible,
                        head_id="downside_probability_bp",
                        attribute="downside_probability_bp",
                        missing_default=5_000,
                    )
                    if eligible
                    else 5_000
                ),
                "uncalibrated_downside_probability_bp": (
                    _weighted_expert_head(
                        eligible,
                        head_id="downside_probability_bp",
                        attribute=(
                            "uncalibrated_downside_probability_bp"
                        ),
                        missing_default=5_000,
                    )
                    if eligible
                    else 5_000
                ),
            }
        return result

    def _signal_for_row(
        self,
        *,
        row: PortfolioMLDatasetRow,
        feature_snapshot_hash: str,
        pack_coverage: Mapping[str, tuple[int, int]],
        expert_outputs: Mapping[str, _ExpertOutput],
        coverage_bp: int,
    ) -> MLAllocationSignalRow:
        family_weights = dict(self._artifact.feature_family_weights_bp)
        active_values: list[tuple[int, _ExpertOutput]] = []
        reasons: set[str] = set()
        missing_head_ids: tuple[str, ...]
        for pack in self._artifact.feature_packs:
            observed, total = pack_coverage[pack.pack_id]
            if observed == 0:
                reasons.add(
                    f"feature_pack_missing_neutral_fallback:{pack.pack_id}"
                )
                continue
            if observed < total:
                reasons.add(
                    f"feature_pack_partial_missing_mask:{pack.pack_id}"
                )
            family_experts = tuple(
                expert_outputs[expert_key]
                for expert_key in self._artifact.expert_keys
                if expert_key.startswith(f"{pack.pack_id}|")
            )
            active_values.extend(
                (family_weights[pack.pack_id], output)
                for output in family_experts
                if not output.neutral_fallback
            )

        if not active_values:
            expected_return_bp = 0
            expected_sector_excess_return_bp: int | None = None
            downside_probability_bp = 5_000
            predicted_mae_bp = 10_000
            predicted_mfe_bp = 0
            predicted_realized_volatility_bp = 10_000
            predicted_max_drawdown_bp = 10_000
            predicted_tail_loss_bp = 10_000
            fill_feasibility_probability_bp = 5_000
            rank_bp = 5_000
            confidence_bp = 0
            missing_head_ids = EXPERT_HEAD_IDS
        else:
            expected_return_bp = _weighted_expert_head(
                active_values,
                head_id="expected_excess_return_bp",
                attribute="expected_excess_return_bp",
                missing_default=0,
            )
            sector_value = _weighted_optional_expert_head(
                active_values,
                head_id="expected_sector_excess_return_bp",
                attribute="expected_sector_excess_return_bp",
            )
            expected_sector_excess_return_bp = sector_value
            downside_probability_bp = _weighted_expert_head(
                active_values,
                head_id="downside_probability_bp",
                attribute="downside_probability_bp",
                missing_default=5_000,
            )
            predicted_mae_bp = _weighted_expert_head(
                active_values,
                head_id="predicted_mae_bp",
                attribute="predicted_mae_bp",
                missing_default=10_000,
            )
            predicted_mfe_bp = _weighted_expert_head(
                active_values,
                head_id="predicted_mfe_bp",
                attribute="predicted_mfe_bp",
                missing_default=0,
            )
            predicted_realized_volatility_bp = _weighted_expert_head(
                active_values,
                head_id="predicted_realized_volatility_bp",
                attribute="predicted_realized_volatility_bp",
                missing_default=10_000,
            )
            predicted_max_drawdown_bp = _weighted_expert_head(
                active_values,
                head_id="predicted_max_drawdown_bp",
                attribute="predicted_max_drawdown_bp",
                missing_default=10_000,
            )
            predicted_tail_loss_bp = _weighted_expert_head(
                active_values,
                head_id="predicted_tail_loss_bp",
                attribute="predicted_tail_loss_bp",
                missing_default=10_000,
            )
            fill_feasibility_probability_bp = _weighted_expert_head(
                active_values,
                head_id="fill_feasibility_probability_bp",
                attribute="fill_feasibility_probability_bp",
                missing_default=5_000,
            )
            denominator = sum(weight for weight, _ in active_values)
            rank_bp = _round_ratio(
                sum(
                    weight * output.rank_bp
                    for weight, output in active_values
                ),
                denominator,
            )
            missing_head_ids = tuple(
                head_id
                for head_id in EXPERT_HEAD_IDS
                if all(
                    head_id in output.missing_head_ids
                    for _, output in active_values
                )
            )
            for head_id in missing_head_ids:
                reasons.add(f"expert_head_missing:{head_id}")
            expert_returns = [
                output.expected_excess_return_bp for _, output in active_values
            ]
            spread_bp = min(
                10_000,
                max(expert_returns) - min(expert_returns),
            )
            agreement_bp = 10_000 - spread_bp
            confidence_bp = _round_ratio(
                coverage_bp * agreement_bp,
                10_000,
            )
        return MLAllocationSignalRow(
            stock_code=row.symbol,
            expected_excess_return_bp=expected_return_bp,
            downside_probability_bp=downside_probability_bp,
            predicted_mae_bp=predicted_mae_bp,
            rank_bp=rank_bp,
            confidence_bp=confidence_bp,
            coverage_bp=coverage_bp,
            feature_manifest_hash=feature_snapshot_hash,
            expected_sector_excess_return_bp=(
                expected_sector_excess_return_bp
            ),
            predicted_mfe_bp=predicted_mfe_bp,
            predicted_realized_volatility_bp=(
                predicted_realized_volatility_bp
            ),
            predicted_max_drawdown_bp=predicted_max_drawdown_bp,
            predicted_tail_loss_bp=predicted_tail_loss_bp,
            fill_feasibility_probability_bp=(
                fill_feasibility_probability_bp
            ),
            missing_head_ids=missing_head_ids,
            missing_family_ids=row.missing_family_ids,
            reasons=tuple(sorted(reasons)),
        )

    def _requested_weights(
        self,
        *,
        rows: tuple[PortfolioMLDatasetRow, ...],
        meta_outputs: Mapping[str, _MetaOutput],
        row_coverage_bp: Mapping[str, int],
    ) -> tuple[AllocationWeightContract, str | None]:
        active_outputs = tuple(
            meta_outputs[row.row_id]
            for row in rows
            if row_coverage_bp[row.row_id] > 0
        )
        if not active_outputs:
            return (
                AllocationWeightContract.cash_only(),
                "all_feature_packs_missing_cash_only",
            )
        cash_bp = _integer_median(
            tuple(output.cash_bp for output in active_outputs)
        )
        risky_budget_bp = _integer_median(
            tuple(output.risky_budget_bp for output in active_outputs)
        )
        maximum_invested_bp = min(
            TOTAL_WEIGHT_BP - cash_bp,
            risky_budget_bp,
        )
        raw_targets = {
            row.symbol: (
                meta_outputs[row.row_id].target_weight_bp
                if row_coverage_bp[row.row_id] > 0
                else 0
            )
            for row in rows
        }
        invested_bp = min(sum(raw_targets.values()), maximum_invested_bp)
        if invested_bp <= 0:
            return (
                AllocationWeightContract.cash_only(),
                "meta_zero_or_cash_only_target",
            )
        scaled = _scale_weights(raw_targets, target_total=invested_bp)
        return (
            AllocationWeightContract(
                symbol_weights_bp={
                    symbol: weight
                    for symbol, weight in scaled.items()
                    if weight > 0
                },
                cash_weight_bp=TOTAL_WEIGHT_BP - sum(scaled.values()),
            ),
            None,
        )


def _parse_artifact(value: object) -> _ArtifactContract:
    if not isinstance(value, dict):
        raise TypeError("artifact payload must be an object")
    unknown = set(value) - _ARTIFACT_FIELDS
    missing = _ARTIFACT_FIELDS - set(value)
    if unknown:
        raise ValueError(f"unsupported artifact field: {sorted(unknown)[0]}")
    if missing:
        raise ValueError(f"artifact field is missing: {sorted(missing)[0]}")
    if value["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("artifact schema version mismatch")

    dataset_id = _text(value["dataset_id"], field_name="dataset_id")
    dataset_identity_hash = _sha_text(
        value["dataset_identity_hash"],
        field_name="dataset_identity_hash",
    )
    dataset_manifest_file_hash = _sha_text(
        value["dataset_manifest_file_hash"],
        field_name="dataset_manifest_file_hash",
    )
    feature_registry_hash = _sha_text(
        value["feature_registry_hash"],
        field_name="feature_registry_hash",
    )
    source_manifest_hashes = _source_hash_pairs(
        value["source_manifest_hashes"]
    )
    training_as_of = _text(
        value["training_as_of"],
        field_name="training_as_of",
    )
    _parse_available_at(training_as_of, field_name="training_as_of")
    feature_packs = _feature_packs(value["feature_packs"])
    horizons = _positive_integer_tuple(value["horizons"], field_name="horizons")
    expert_keys = _string_tuple(value["expert_keys"], field_name="expert_keys")
    expected_expert_keys = tuple(
        f"{pack.pack_id}|h{horizon}|{algorithm}"
        for pack in feature_packs
        for horizon in horizons
        for algorithm in EXPERT_ALGORITHMS
    )
    if expert_keys != expected_expert_keys:
        raise ValueError("artifact expert keys do not match frozen packs/horizons")
    expert_head_ids = _string_tuple(
        value["expert_head_ids"],
        field_name="expert_head_ids",
    )
    if expert_head_ids != EXPERT_HEAD_IDS:
        raise ValueError("artifact expert head ids mismatch")
    expert_vector_width = _integer(
        value["expert_vector_width"],
        field_name="expert_vector_width",
    )
    if expert_vector_width != EXPERT_VECTOR_WIDTH:
        raise ValueError("artifact expert vector width mismatch")

    base_models = _mapping(value["base_models"], field_name="base_models")
    if set(base_models) != set(expert_keys):
        raise ValueError("artifact base model set does not match expert keys")
    for expert_key in expert_keys:
        model_payload = _mapping(
            base_models[expert_key],
            field_name=f"base_models[{expert_key}]",
        )
        if set(model_payload) != {
            "regression_models",
            "classification_models",
            "preprocessing_strategy",
            "head_fit_row_ids",
            "head_missing_reasons",
            "fit_row_ids",
        }:
            raise ValueError(f"base model contract mismatch: {expert_key}")
        fit_row_ids = _string_tuple(
            model_payload["fit_row_ids"],
            field_name=f"{expert_key}.fit_row_ids",
        )
        head_fit_row_ids = _mapping(
            model_payload["head_fit_row_ids"],
            field_name=f"{expert_key}.head_fit_row_ids",
        )
        if set(head_fit_row_ids) != set(EXPERT_HEAD_IDS):
            raise ValueError(f"head fit row set mismatch: {expert_key}")
        missing_reasons = _mapping(
            model_payload["head_missing_reasons"],
            field_name=f"{expert_key}.head_missing_reasons",
        )
        if not set(missing_reasons).issubset(EXPERT_HEAD_IDS):
            raise ValueError(f"unknown missing expert head: {expert_key}")
        for head_id, reason in missing_reasons.items():
            _text(
                reason,
                field_name=f"{expert_key}.{head_id}.missing_reason",
            )

        regression_models = _mapping(
            model_payload["regression_models"],
            field_name=f"{expert_key}.regression_models",
        )
        classification_models = _mapping(
            model_payload["classification_models"],
            field_name=f"{expert_key}.classification_models",
        )
        if set(regression_models) != set(REGRESSION_EXPERT_HEADS):
            raise ValueError(
                f"regression head model set mismatch: {expert_key}"
            )
        if set(classification_models) != set(
            CLASSIFICATION_EXPERT_HEADS
        ):
            raise ValueError(
                f"classification head model set mismatch: {expert_key}"
            )
        for head_id in EXPERT_HEAD_IDS:
            rows = _possibly_empty_string_tuple(
                head_fit_row_ids[head_id],
                field_name=f"{expert_key}.{head_id}.fit_row_ids",
            )
            if not set(rows).issubset(fit_row_ids):
                raise ValueError(
                    f"head fit rows exceed expert fit rows: {expert_key}"
                )
            model = (
                regression_models[head_id]
                if head_id in REGRESSION_EXPERT_HEADS
                else classification_models[head_id]
            )
            head_missing = head_id in missing_reasons
            if model is None:
                if not head_missing or rows:
                    raise ValueError(
                        f"missing head contract mismatch: {expert_key}.{head_id}"
                    )
                continue
            if head_missing or not rows:
                raise ValueError(
                    f"available head contract mismatch: {expert_key}.{head_id}"
                )
            _require_predictor(
                model,
                method_name=(
                    "predict"
                    if head_id in REGRESSION_EXPERT_HEADS
                    else "predict_proba"
                ),
                field_name=f"{expert_key}.{head_id}",
            )
        _text(
            model_payload["preprocessing_strategy"],
            field_name=f"{expert_key}.preprocessing_strategy",
        )

    meta_models = _mapping(value["meta_models"], field_name="meta_models")
    if set(meta_models) != {"numeric", "rebalance", "fit_row_ids"}:
        raise ValueError("meta model contract mismatch")
    numeric_models = _mapping(meta_models["numeric"], field_name="meta.numeric")
    if set(numeric_models) != set(_META_NUMERIC_FIELDS):
        raise ValueError("meta numeric model set mismatch")
    for field_name in _META_NUMERIC_FIELDS:
        _require_predictor(
            numeric_models[field_name],
            method_name="predict",
            field_name=f"meta.numeric.{field_name}",
        )
    _require_predictor(
        meta_models["rebalance"],
        method_name="predict_proba",
        field_name="meta.rebalance",
    )
    _string_tuple(meta_models["fit_row_ids"], field_name="meta.fit_row_ids")

    family_weights = _weight_pairs(
        value["feature_family_weights_bp"],
        field_name="feature_family_weights_bp",
    )
    if tuple(family_id for family_id, _ in family_weights) != tuple(
        pack.pack_id for pack in feature_packs
    ):
        raise ValueError("feature family weights do not match feature packs")
    if sum(weight for _, weight in family_weights) != 10_000:
        raise ValueError("feature family weights must equal 10000")

    alpha = _integer(value["production_alpha_bp"], field_name="production_alpha_bp")
    if alpha != 0:
        raise ValueError("artifact cannot authorize non-zero production alpha")
    for field_name in (
        "production_action_allowed",
        "formal_oos_allowed",
        "broker_order_allowed",
    ):
        if value[field_name] is not False:
            raise ValueError(f"artifact {field_name} must be false")
    return _ArtifactContract(
        dataset_id=dataset_id,
        dataset_identity_hash=dataset_identity_hash,
        dataset_manifest_file_hash=dataset_manifest_file_hash,
        feature_registry_hash=feature_registry_hash,
        source_manifest_hashes=source_manifest_hashes,
        training_as_of=training_as_of,
        feature_packs=feature_packs,
        horizons=horizons,
        expert_keys=expert_keys,
        base_models=base_models,
        meta_models=meta_models,
        feature_family_weights_bp=family_weights,
    )


def _feature_packs(value: object) -> tuple[_FeaturePack, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError("feature_packs must be a non-empty array")
    packs: list[_FeaturePack] = []
    feature_ids_seen: set[str] = set()
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError("feature_packs entries must be pack/feature arrays")
        pack_id = _text(item[0], field_name="feature_pack.pack_id")
        feature_ids = _string_tuple(
            item[1],
            field_name=f"feature_packs[{pack_id}]",
        )
        if any(
            character in feature_id
            for feature_id in feature_ids
            for character in ("*", "?", "[", "]")
        ):
            raise ValueError("artifact feature ids cannot contain wildcards")
        if feature_ids_seen & set(feature_ids):
            raise ValueError("artifact feature ids must belong to one pack")
        feature_ids_seen.update(feature_ids)
        packs.append(_FeaturePack(pack_id=pack_id, feature_ids=feature_ids))
    pack_ids = tuple(pack.pack_id for pack in packs)
    if len(pack_ids) != len(set(pack_ids)):
        raise ValueError("artifact feature pack ids must be unique")
    if pack_ids != tuple(sorted(pack_ids)):
        raise ValueError("artifact feature packs must use canonical order")
    return tuple(packs)


def _pack_matrix(
    rows: Sequence[PortfolioMLDatasetRow],
    *,
    pack: _FeaturePack,
    algorithm: str,
) -> NDArray[np.float64]:
    values: list[list[float]] = []
    masks: list[list[float]] = []
    for row in rows:
        feature_by_id = {
            feature.feature_id: feature for feature in row.features
        }
        value_row: list[float] = []
        mask_row: list[float] = []
        for feature_id in pack.feature_ids:
            feature = feature_by_id[feature_id]
            if feature.observed:
                assert feature.value_int is not None
                value_row.append(
                    float(  # numeric-boundary: analytics
                        feature.value_int
                    )
                    / float(feature.scale)  # numeric-boundary: analytics
                )
                mask_row.append(0.0)
            else:
                value_row.append(float("nan"))  # numeric-boundary: analytics
                mask_row.append(1.0)
        values.append(value_row)
        masks.append(mask_row)
    raw = np.asarray(
        values,
        dtype=float,  # numeric-boundary: analytics
    )
    if algorithm == "hist_gradient_boosting":
        return np.concatenate(
            (
                raw,
                np.asarray(
                    masks,
                    dtype=float,  # numeric-boundary: analytics
                ),
            ),
            axis=1,
        )
    if algorithm != "ridge_logistic":
        raise ValueError(f"unsupported expert algorithm: {algorithm}")
    return raw


def _predict_array(
    model: object,
    matrix: NDArray[np.float64],
    *,
    method_name: str,
    field_name: str,
) -> NDArray[np.float64]:
    predictor = getattr(model, method_name, None)
    if not callable(predictor):
        raise ValueError(f"{field_name} predictor is unavailable")
    try:
        result = np.asarray(
            predictor(matrix),
            dtype=float,  # numeric-boundary: analytics
        )
    except Exception as exc:
        raise ValueError(f"{field_name} prediction failed") from exc
    if result.ndim != 1 or len(result) != len(matrix) or not np.all(np.isfinite(result)):
        raise ValueError(f"{field_name} output shape/value is invalid")
    return result


def _predict_probability_array(
    model: object,
    matrix: NDArray[np.float64],
    *,
    field_name: str,
) -> NDArray[np.float64]:
    predictor = getattr(model, "predict_proba", None)
    if not callable(predictor):
        raise ValueError(f"{field_name} predictor is unavailable")
    try:
        result = np.asarray(
            predictor(matrix),
            dtype=float,  # numeric-boundary: analytics
        )
    except Exception as exc:
        raise ValueError(f"{field_name} prediction failed") from exc
    if (
        result.ndim != 2
        or result.shape != (len(matrix), 2)
        or not np.all(np.isfinite(result))
        or np.any(result < 0)
        or np.any(result > 1)
    ):
        raise ValueError(f"{field_name} output shape/value is invalid")
    return np.asarray(
        result[:, 1],
        dtype=float,  # numeric-boundary: analytics
    )


def _predict_uncalibrated_probability_array(
    model: object,
    matrix: NDArray[np.float64],
    *,
    field_name: str,
) -> NDArray[np.float64]:
    """重播 calibrated classifier 內各 fold 的原始 estimator 機率。"""

    calibrated_folds = getattr(model, "calibrated_classifiers_", None)
    if not isinstance(calibrated_folds, list) or not calibrated_folds:
        raise ValueError(
            f"{field_name} uncalibrated fold estimators are unavailable"
        )
    fold_probabilities: list[NDArray[np.float64]] = []
    for fold_index, calibrated_fold in enumerate(calibrated_folds):
        estimator = getattr(calibrated_fold, "estimator", None)
        if estimator is None:
            raise ValueError(
                f"{field_name} fold {fold_index} estimator is unavailable"
            )
        fold_probabilities.append(
            _predict_probability_array(
                estimator,
                matrix,
                field_name=f"{field_name}.fold[{fold_index}]",
            )
        )
    return np.mean(
        np.vstack(fold_probabilities),
        axis=0,
        dtype=float,  # numeric-boundary: analytics
    )


def _rank_bp(
    *,
    rows: tuple[PortfolioMLDatasetRow, ...],
    predicted_values: tuple[int, ...],
) -> dict[str, int]:
    ordered = sorted(
        zip(predicted_values, (row.symbol for row in rows), rows),
        key=lambda item: (item[0], item[1]),
    )
    if len(ordered) == 1:
        return {ordered[0][2].row_id: 5_000}
    denominator = len(ordered) - 1
    return {
        row.row_id: (rank * 10_000) // denominator
        for rank, (_, _, row) in enumerate(ordered)
    }


def _expert_vector(output: _ExpertOutput) -> tuple[int, ...]:
    values = (
        output.expected_excess_return_bp,
        (
            output.expected_sector_excess_return_bp
            if output.expected_sector_excess_return_bp is not None
            else 0
        ),
        output.predicted_mae_bp,
        output.predicted_mfe_bp,
        output.predicted_realized_volatility_bp,
        output.predicted_max_drawdown_bp,
        output.predicted_tail_loss_bp,
        output.downside_probability_bp,
        output.fill_feasibility_probability_bp,
        output.rank_bp,
    )
    missing = set(output.missing_head_ids)
    masks = tuple(int(head_id in missing) for head_id in EXPERT_HEAD_IDS)
    result = values + masks
    if len(result) != EXPERT_VECTOR_WIDTH:
        raise ValueError("expert inference vector width mismatch")
    return result


def _expert_output_payload(output: _ExpertOutput) -> dict[str, object]:
    return {
        "expected_excess_return_bp": output.expected_excess_return_bp,
        "expected_sector_excess_return_bp": (
            output.expected_sector_excess_return_bp
        ),
        "downside_probability_bp": output.downside_probability_bp,
        "uncalibrated_downside_probability_bp": (
            output.uncalibrated_downside_probability_bp
        ),
        "predicted_mae_bp": output.predicted_mae_bp,
        "predicted_mfe_bp": output.predicted_mfe_bp,
        "predicted_realized_volatility_bp": (
            output.predicted_realized_volatility_bp
        ),
        "predicted_max_drawdown_bp": output.predicted_max_drawdown_bp,
        "predicted_tail_loss_bp": output.predicted_tail_loss_bp,
        "fill_feasibility_probability_bp": (
            output.fill_feasibility_probability_bp
        ),
        "rank_bp": output.rank_bp,
        "missing_head_ids": list(output.missing_head_ids),
        "neutral_fallback": output.neutral_fallback,
    }


def _weighted_expert_head(
    active_values: Sequence[tuple[int, _ExpertOutput]],
    *,
    head_id: str,
    attribute: str,
    missing_default: int,
) -> int:
    eligible: list[tuple[int, int]] = []
    for weight, output in active_values:
        if head_id in output.missing_head_ids:
            continue
        value = getattr(output, attribute)
        if value is None:
            continue
        eligible.append(
            (weight, _inference_int(value, field_name=attribute))
        )
    if not eligible:
        return missing_default
    return _round_ratio(
        sum(weight * value for weight, value in eligible),
        sum(weight for weight, _ in eligible),
    )


def _weighted_optional_expert_head(
    active_values: Sequence[tuple[int, _ExpertOutput]],
    *,
    head_id: str,
    attribute: str,
) -> int | None:
    eligible: list[tuple[int, int]] = []
    for weight, output in active_values:
        if head_id in output.missing_head_ids:
            continue
        value = getattr(output, attribute)
        if value is None:
            continue
        eligible.append(
            (weight, _inference_int(value, field_name=attribute))
        )
    if not eligible:
        return None
    return _round_ratio(
        sum(weight * value for weight, value in eligible),
        sum(weight for weight, _ in eligible),
    )


def _feature_snapshot_hash(row: PortfolioMLDatasetRow) -> str:
    return _sha256_json(
        {
            "row_id": row.row_id,
            "decision_at": row.decision_at,
            "symbol": row.symbol,
            "features": [
                _feature_payload(feature)
                for feature in sorted(
                    row.features,
                    key=lambda item: item.feature_id,
                )
            ],
            "missing_family_ids": list(row.missing_family_ids),
            "portfolio_state_hash": row.portfolio_state.state_hash,
            "dataset_identity_hash": row.dataset_identity_hash,
            "feature_registry_hash": row.feature_registry_hash,
            "source_manifest_hashes": [
                [source_id, source_hash]
                for source_id, source_hash in row.source_manifest_hashes
            ],
        }
    )


def _feature_payload(feature: PITFeatureValue) -> dict[str, object]:
    return {
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


def _turnover_bp(
    *,
    current_positions: Mapping[str, int],
    current_cash_bp: int,
    requested: AllocationWeightContract,
) -> int:
    symbols = set(current_positions) | set(requested.symbol_weights_bp)
    ordered_symbols = sorted(symbols)
    return canonical_turnover_bp(
        current_position_weights_bp=tuple(
            current_positions.get(symbol, 0) for symbol in ordered_symbols
        ),
        current_cash_bp=current_cash_bp,
        target_position_weights_bp=tuple(
            requested.symbol_weights_bp.get(symbol, 0)
            for symbol in ordered_symbols
        ),
        target_cash_bp=requested.cash_weight_bp,
    )


def _scale_weights(
    weights: Mapping[str, int],
    *,
    target_total: int,
) -> dict[str, int]:
    if target_total < 0 or target_total > 10_000:
        raise ValueError("target_total must be within 0..10000")
    total = sum(weights.values())
    if total <= 0 or target_total == 0:
        return {symbol: 0 for symbol in weights}
    if total <= target_total:
        return dict(weights)
    floors: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    for symbol, weight in weights.items():
        floor, remainder = divmod(weight * target_total, total)
        floors[symbol] = floor
        remainders.append((remainder, symbol))
    remaining = target_total - sum(floors.values())
    for _, symbol in sorted(
        remainders,
        key=lambda item: (-item[0], item[1]),
    )[:remaining]:
        floors[symbol] += 1
    return floors


def _integer_median(values: tuple[int, ...]) -> int:
    if not values:
        raise ValueError("median values are required")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return _round_ratio(ordered[middle - 1] + ordered[middle], 2)


def _round_ratio(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("rounding denominator must be positive")
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _quantize_signed_bp(value: object) -> int:
    numeric = _quantize_model_integer(value)
    return max(-10_000, min(10_000, numeric))


def _quantize_bounded_bp(value: object) -> int:
    numeric = _quantize_model_integer(value)
    return max(0, min(10_000, numeric))


def _quantize_probability_bp(value: object) -> int:
    numeric = float(cast(Any, value))  # numeric-boundary: analytics
    if not np.isfinite(numeric):
        raise ValueError("model probability must be finite")
    bounded = max(0.0, min(1.0, numeric))
    return _quantize_model_integer(bounded * 10_000.0)


def _quantize_model_integer(value: object) -> int:
    numeric = float(cast(Any, value))  # numeric-boundary: analytics
    if not np.isfinite(numeric):
        raise ValueError("model output must be finite")
    return int(
        Decimal(str(numeric)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _source_hash_pairs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError("source_manifest_hashes must be a non-empty array")
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError("source manifest entries must be two-item arrays")
        source_id = _text(item[0], field_name="source_id")
        source_hash = _sha_text(item[1], field_name=f"source[{source_id}]")
        result.append((source_id, source_hash))
    source_ids = tuple(source_id for source_id, _ in result)
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source manifest ids must be unique")
    return tuple(result)


def _weight_pairs(
    value: object,
    *,
    field_name: str,
) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError(f"{field_name} must be a non-empty array")
    result: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{field_name} entries must be two-item arrays")
        key = _text(item[0], field_name=f"{field_name}.key")
        result.append((key, _bp(item[1], field_name=f"{field_name}[{key}]")))
    keys = tuple(key for key, _ in result)
    if len(keys) != len(set(keys)):
        raise ValueError(f"{field_name} keys must be unique")
    return tuple(result)


def _positive_integer_tuple(value: object, *, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError(f"{field_name} must be a non-empty integer array")
    result = tuple(_integer(item, field_name=field_name) for item in value)
    if any(item <= 0 for item in result) or len(result) != len(set(result)):
        raise ValueError(f"{field_name} must contain unique positive integers")
    if result != tuple(sorted(result)):
        raise ValueError(f"{field_name} must use canonical order")
    return result


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError(f"{field_name} must be a non-empty string array")
    result = tuple(_text(item, field_name=field_name) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must contain unique values")
    return result


def _possibly_empty_string_tuple(
    value: object,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a string array")
    result = tuple(_text(item, field_name=field_name) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must contain unique values")
    return result


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _require_predictor(
    value: object,
    *,
    method_name: str,
    field_name: str,
) -> None:
    if not callable(getattr(value, method_name, None)):
        raise ValueError(f"{field_name} must implement {method_name}")


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _require_text(**values: str) -> None:
    for field_name, value in values.items():
        _text(value, field_name=field_name)


def _integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer")
    return value


def _inference_int(value: object, *, field_name: str) -> int:
    return _integer(value, field_name=field_name)


def _inference_optional_int(
    value: object,
    *,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    return _integer(value, field_name=field_name)


def _bp(value: object, *, field_name: str) -> int:
    numeric = _integer(value, field_name=field_name)
    if not 0 <= numeric <= 10_000:
        raise ValueError(f"{field_name} must be within 0..10000")
    return numeric


def _sha_text(value: object, *, field_name: str) -> str:
    text = _text(value, field_name=field_name)
    _require_sha256(text, field_name=field_name)
    return text


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")


def _parse_available_at(value: str, *, field_name: str) -> datetime:
    if len(value) == 10:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO date") from exc
        return datetime.combine(parsed_date, time.max, tzinfo=_TAIPEI)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed.astimezone(_TAIPEI)


def _parse_decision_at(value: str) -> datetime:
    parsed = _parse_available_at(value, field_name="decision_at")
    if parsed.timetz().replace(tzinfo=None) != time(8, 30):
        raise ValueError("decision_at must be 08:30 Asia/Taipei")
    return parsed


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> str:
    return _sha256(_canonical_json(value).encode("utf-8"))


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
