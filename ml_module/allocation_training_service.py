"""全資料配置型 ML 的純訓練邊界。

本模組刻意不匯入 ``app_module``、``decision_module`` 或 ``portfolio_module``。
所有公開契約皆使用整數 bp；NumPy／scikit-learn 的浮點數只存在於本檔案的
模型訓練與推論邊界，離開邊界前一律量化回整數。

訓練流程採兩層 stacking：

1. 每個 feature pack、horizon 與 algorithm 都只對 outer-fold test rows
   產生 base OOF prediction。
2. Meta Allocator 只使用上述 base OOF prediction。其時間序列 OOF 預測
   僅以較早 outer folds 的 OOF rows fit，最後模型才使用完整 OOF 集合 fit。

本服務只產生可供 Production Co-pilot 稽核的模型 artifact；不決定 production
alpha，也不允許直接套用投組。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
from io import BytesIO
import json
from typing import Any, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml_module.allocation_contracts import AllocationTargets, PortfolioMLDatasetRow
from ml_module.allocation_rank_contract import (
    DEFAULT_RANK_CONTRACT,
    rank_values_bp,
    validate_rank_contract,
)
from ml_module.purged_walk_forward import PurgedWalkForwardFold


SUPPORTED_HORIZONS = (5, 10, 20, 60)
EXPERT_ALGORITHMS = ("ridge_logistic", "hist_gradient_boosting")
ARTIFACT_SCHEMA_VERSION = "allocation-model-artifact-v3"
REGRESSION_EXPERT_HEADS = (
    "expected_excess_return_bp",
    "expected_sector_excess_return_bp",
    "predicted_mae_bp",
    "predicted_mfe_bp",
    "predicted_realized_volatility_bp",
    "predicted_max_drawdown_bp",
    "predicted_tail_loss_bp",
)
CLASSIFICATION_EXPERT_HEADS = (
    "downside_probability_bp",
    "fill_feasibility_probability_bp",
)
EXPERT_HEAD_IDS = REGRESSION_EXPERT_HEADS + CLASSIFICATION_EXPERT_HEADS
# 每個 expert 向 Meta Allocator 提供全部 head、benchmark rank，
# 以及逐 head missing mask。
EXPERT_VECTOR_WIDTH = len(EXPERT_HEAD_IDS) + 1 + len(EXPERT_HEAD_IDS)
_REGRESSION_LABEL_FIELDS = {
    "expected_excess_return_bp": "benchmark_excess_return_bp",
    "expected_sector_excess_return_bp": "sector_excess_return_bp",
    "predicted_mae_bp": "mae_bp",
    "predicted_mfe_bp": "mfe_bp",
    "predicted_realized_volatility_bp": "realized_volatility_bp",
    "predicted_max_drawdown_bp": "max_drawdown_bp",
    "predicted_tail_loss_bp": "tail_loss_bp",
}
_CLASSIFICATION_LABEL_FIELDS = {
    "downside_probability_bp": "downside_observed",
    "fill_feasibility_probability_bp": "fill_feasible_observed",
}
_SIGNED_REGRESSION_HEADS = frozenset(
    {
        "expected_excess_return_bp",
        "expected_sector_excess_return_bp",
    }
)
ExpertAlgorithm = Literal["ridge_logistic", "hist_gradient_boosting"]
_TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True)
class FeaturePackDefinition:
    """一組需共同訓練的 PIT 特徵。

    ``feature_ids`` 的順序屬於 frozen schema，會進入 artifact/replay hash。
    """

    pack_id: str
    feature_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(pack_id=self.pack_id)
        if (
            not self.feature_ids
            or any(not feature_id.strip() for feature_id in self.feature_ids)
            or len(self.feature_ids) != len(set(self.feature_ids))
        ):
            raise ValueError("feature_ids must be non-empty and unique")


@dataclass(frozen=True)
class AllocationHorizonLabel:
    """成熟後才可 fit 的單一 horizon 結果標籤。"""

    horizon_trading_days: int
    horizon_end_date: str
    available_at: str
    benchmark_excess_return_bp: int
    sector_excess_return_bp: int | None
    sector_excess_observed: bool
    sector_excess_missing_reason: str | None
    downside_observed: bool
    mae_bp: int
    mfe_bp: int
    realized_volatility_bp: int
    max_drawdown_bp: int
    tail_loss_bp: int
    fill_feasible_observed: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.horizon_trading_days, bool)
            or not isinstance(self.horizon_trading_days, int)
            or self.horizon_trading_days <= 0
        ):
            raise TypeError("horizon_trading_days must be a positive integer")
        _parse_date(self.horizon_end_date, field_name="horizon_end_date")
        available = _parse_available_at(self.available_at, field_name="available_at")
        if available.date() < _parse_date(
            self.horizon_end_date, field_name="horizon_end_date"
        ):
            raise ValueError("label available_at must not precede horizon_end_date")
        _require_integer(
            "benchmark_excess_return_bp", self.benchmark_excess_return_bp
        )
        if self.sector_excess_return_bp is not None:
            _require_integer(
                "sector_excess_return_bp", self.sector_excess_return_bp
            )
        if not isinstance(self.sector_excess_observed, bool):
            raise TypeError("sector_excess_observed must be bool")
        if self.sector_excess_observed:
            if self.sector_excess_return_bp is None:
                raise ValueError(
                    "observed sector excess requires sector_excess_return_bp"
                )
            if self.sector_excess_missing_reason is not None:
                raise ValueError(
                    "observed sector excess cannot have a missing reason"
                )
        else:
            if self.sector_excess_return_bp is not None:
                raise ValueError(
                    "missing sector excess cannot carry a numeric value"
                )
            _require_text(
                sector_excess_missing_reason=(
                    self.sector_excess_missing_reason or ""
                )
            )
        if not isinstance(self.downside_observed, bool):
            raise TypeError("downside_observed must be bool")
        for field_name in (
            "mae_bp",
            "mfe_bp",
            "realized_volatility_bp",
            "max_drawdown_bp",
            "tail_loss_bp",
        ):
            _require_bp(field_name, getattr(self, field_name))
        if not isinstance(self.fill_feasible_observed, bool):
            raise TypeError("fill_feasible_observed must be bool")


@dataclass(frozen=True)
class AllocationTrainingSample:
    """PIT dataset row 與多 horizon supervised outcomes。"""

    row: PortfolioMLDatasetRow
    horizon_labels: tuple[AllocationHorizonLabel, ...]

    def __post_init__(self) -> None:
        if self.row.targets is None:
            raise ValueError("allocation training sample requires AllocationTargets")
        if not self.horizon_labels:
            raise ValueError("horizon_labels are required")
        horizons = tuple(label.horizon_trading_days for label in self.horizon_labels)
        if len(horizons) != len(set(horizons)):
            raise ValueError("horizon labels must be unique")
        decision_date = _parse_decision_at(self.row.decision_at).date()
        for label in self.horizon_labels:
            if _parse_date(
                label.horizon_end_date, field_name="horizon_end_date"
            ) <= decision_date:
                raise ValueError("horizon_end_date must be after decision date")


@dataclass(frozen=True)
class BaseExpertOOFPrediction:
    """單一 base expert 對 outer-fold test row 的量化預測。"""

    row_id: str
    decision_date: str
    fold_id: str
    pack_id: str
    horizon_trading_days: int
    algorithm: ExpertAlgorithm
    expected_excess_return_bp: int
    expected_sector_excess_return_bp: int | None
    downside_probability_bp: int
    predicted_mae_bp: int
    predicted_mfe_bp: int
    predicted_realized_volatility_bp: int
    predicted_max_drawdown_bp: int
    predicted_tail_loss_bp: int
    fill_feasibility_probability_bp: int
    rank_bp: int
    missing_head_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(
            row_id=self.row_id,
            decision_date=self.decision_date,
            fold_id=self.fold_id,
            pack_id=self.pack_id,
            algorithm=self.algorithm,
        )
        _parse_date(self.decision_date, field_name="decision_date")
        if self.algorithm not in EXPERT_ALGORITHMS:
            raise ValueError("unsupported expert algorithm")
        if (
            isinstance(self.horizon_trading_days, bool)
            or not isinstance(self.horizon_trading_days, int)
            or self.horizon_trading_days <= 0
        ):
            raise TypeError("horizon_trading_days must be a positive integer")
        _require_integer(
            "expected_excess_return_bp", self.expected_excess_return_bp
        )
        if self.expected_sector_excess_return_bp is not None:
            _require_integer(
                "expected_sector_excess_return_bp",
                self.expected_sector_excess_return_bp,
            )
        for field_name in (
            "downside_probability_bp",
            "predicted_mae_bp",
            "predicted_mfe_bp",
            "predicted_realized_volatility_bp",
            "predicted_max_drawdown_bp",
            "predicted_tail_loss_bp",
            "fill_feasibility_probability_bp",
            "rank_bp",
        ):
            _require_bp(field_name, getattr(self, field_name))
        if (
            len(self.missing_head_ids) != len(set(self.missing_head_ids))
            or not set(self.missing_head_ids).issubset(EXPERT_HEAD_IDS)
        ):
            raise ValueError("missing_head_ids must be unique known expert heads")
        sector_missing = (
            "expected_sector_excess_return_bp" in self.missing_head_ids
        )
        if sector_missing != (self.expected_sector_excess_return_bp is None):
            raise ValueError(
                "sector excess value and missing-head mask are inconsistent"
            )

    @property
    def expert_id(self) -> str:
        return (
            f"{self.pack_id}|h{self.horizon_trading_days}|{self.algorithm}"
        )


@dataclass(frozen=True)
class ExpertFoldAudit:
    """可證明所有 fold-local state 僅 fit outer train rows 的稽核紀錄。"""

    fold_id: str
    pack_id: str
    horizon_trading_days: int
    algorithm: ExpertAlgorithm
    model_fit_row_ids: tuple[str, ...]
    preprocessor_fit_row_ids: tuple[str, ...]
    calibrator_fit_row_ids: tuple[str, ...]
    test_row_ids: tuple[str, ...]
    preprocessing_strategy: str
    head_fit_row_ids: tuple[tuple[str, tuple[str, ...]], ...] = ()
    missing_head_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(
            fold_id=self.fold_id,
            pack_id=self.pack_id,
            algorithm=self.algorithm,
            preprocessing_strategy=self.preprocessing_strategy,
        )
        for field_name in (
            "model_fit_row_ids",
            "preprocessor_fit_row_ids",
            "test_row_ids",
        ):
            values = getattr(self, field_name)
            if (
                not values
                or len(values) != len(set(values))
                or any(not value.strip() for value in values)
            ):
                raise ValueError(f"{field_name} must be non-empty and unique")
        if len(self.calibrator_fit_row_ids) != len(
            set(self.calibrator_fit_row_ids)
        ):
            raise ValueError("calibrator_fit_row_ids must be unique")
        expected = set(self.model_fit_row_ids)
        if (
            self.preprocessor_fit_row_ids is not self.model_fit_row_ids
            and set(self.preprocessor_fit_row_ids) != expected
        ):
            raise ValueError("preprocessor rows must equal model fit rows")
        if (
            self.calibrator_fit_row_ids is not self.model_fit_row_ids
            and not set(self.calibrator_fit_row_ids).issubset(expected)
        ):
            raise ValueError("calibrator rows must belong to model fit rows")
        if expected & set(self.test_row_ids):
            raise ValueError("fit rows and test rows must be disjoint")
        head_ids = tuple(head_id for head_id, _ in self.head_fit_row_ids)
        if head_ids != EXPERT_HEAD_IDS:
            raise ValueError(
                "head_fit_row_ids must follow the complete expert head order"
            )
        if (
            len(self.missing_head_ids) != len(set(self.missing_head_ids))
            or not set(self.missing_head_ids).issubset(EXPERT_HEAD_IDS)
        ):
            raise ValueError("missing_head_ids must be unique known expert heads")
        for head_id, row_ids in self.head_fit_row_ids:
            if row_ids is not self.model_fit_row_ids:
                if len(row_ids) != len(set(row_ids)):
                    raise ValueError(f"{head_id} fit row ids must be unique")
                if not set(row_ids).issubset(expected):
                    raise ValueError(
                        f"{head_id} fit rows must belong to outer train"
                    )
            if (not row_ids) != (head_id in self.missing_head_ids):
                raise ValueError(
                    f"{head_id} fit rows and missing-head mask are inconsistent"
                )


@dataclass(frozen=True)
class MetaAllocatorOOFPrediction:
    """Meta Allocator 的時間序列 OOF 整數預測。"""

    row_id: str
    decision_date: str
    fold_id: str
    fit_fold_ids: tuple[str, ...]
    fit_row_ids: tuple[str, ...]
    target_weight_bp: int
    delta_weight_bp: int
    risk_contribution_bp: int
    risky_budget_bp: int
    cash_bp: int
    rebalance_worthwhile: bool

    def __post_init__(self) -> None:
        _require_text(
            row_id=self.row_id,
            decision_date=self.decision_date,
            fold_id=self.fold_id,
        )
        _parse_date(self.decision_date, field_name="decision_date")
        if (
            not self.fit_fold_ids
            or len(self.fit_fold_ids) != len(set(self.fit_fold_ids))
            or any(not fold_id.strip() for fold_id in self.fit_fold_ids)
        ):
            raise ValueError("fit_fold_ids must be non-empty and unique")
        if (
            not self.fit_row_ids
            or len(self.fit_row_ids) != len(set(self.fit_row_ids))
            or any(not row_id.strip() for row_id in self.fit_row_ids)
        ):
            raise ValueError("fit_row_ids must be non-empty and unique")
        for field_name in (
            "target_weight_bp",
            "risk_contribution_bp",
            "risky_budget_bp",
            "cash_bp",
        ):
            _require_bp(field_name, getattr(self, field_name))
        delta = _require_integer("delta_weight_bp", self.delta_weight_bp)
        if not -10_000 <= delta <= 10_000:
            raise ValueError("delta_weight_bp must be within -10000..10000")
        if not isinstance(self.rebalance_worthwhile, bool):
            raise TypeError("rebalance_worthwhile must be bool")


@dataclass(frozen=True)
class MetaFoldAudit:
    fold_id: str
    fit_fold_ids: tuple[str, ...]
    fit_row_ids: tuple[str, ...]
    test_row_ids: tuple[str, ...]


@dataclass(frozen=True)
class AllocationTrainingResult:
    """可重播的配置訓練結果；production alpha 永遠保持 0。"""

    dataset_id: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    feature_registry_hash: str
    source_manifest_hashes: tuple[tuple[str, str], ...]
    training_as_of: str
    horizons: tuple[int, ...]
    feature_pack_ids: tuple[str, ...]
    outer_fold_ids: tuple[str, ...]
    base_oof_predictions: tuple[BaseExpertOOFPrediction, ...]
    expert_fold_audits: tuple[ExpertFoldAudit, ...]
    meta_oof_predictions: tuple[MetaAllocatorOOFPrediction, ...]
    meta_fold_audits: tuple[MetaFoldAudit, ...]
    feature_family_weights_bp: tuple[tuple[str, int], ...]
    artifact_bytes: bytes
    artifact_hash: str
    replay_hash: str
    audit_json: str
    rank_contract: str = DEFAULT_RANK_CONTRACT
    production_alpha_bp: int = 0
    production_action_allowed: bool = False

    def __post_init__(self) -> None:
        _require_text(dataset_id=self.dataset_id, training_as_of=self.training_as_of)
        _require_sha256(
            self.dataset_identity_hash,
            field_name="dataset_identity_hash",
        )
        _require_sha256(
            self.dataset_manifest_file_hash,
            field_name="dataset_manifest_file_hash",
        )
        _require_sha256(
            self.feature_registry_hash, field_name="feature_registry_hash"
        )
        if not self.source_manifest_hashes:
            raise ValueError("source_manifest_hashes are required")
        for source_id, source_hash in self.source_manifest_hashes:
            _require_text(source_id=source_id)
            _require_sha256(
                source_hash, field_name=f"source_manifest_hashes[{source_id}]"
            )
        if not self.horizons or not self.outer_fold_ids:
            raise ValueError("horizons and outer_fold_ids are required")
        if len(self.outer_fold_ids) < 4:
            raise ValueError("at least four outer folds are required")
        if not self.artifact_bytes:
            raise ValueError("artifact_bytes are required")
        _require_sha256(self.artifact_hash, field_name="artifact_hash")
        _require_sha256(self.replay_hash, field_name="replay_hash")
        validate_rank_contract(self.rank_contract)
        if sum(value for _, value in self.feature_family_weights_bp) != 10_000:
            raise ValueError("feature family weights must equal 10000")
        if self.production_alpha_bp != 0 or self.production_action_allowed:
            raise ValueError("training result cannot authorize production allocation")

    def audit_payload(self) -> Mapping[str, Any]:
        """回傳可直接寫入 JSON evidence 的乾淨 mapping。"""

        payload = json.loads(self.audit_json)
        if not isinstance(payload, dict):
            raise ValueError("audit_json must contain an object")
        return payload


class AllocationTrainingService:
    """以 outer-fold OOF 專家訓練配置 Meta Allocator。"""

    def __init__(
        self,
        *,
        random_state: int = 42,
        hgb_max_iter: int = 60,
        ridge_alpha: int = 1,
        rank_contract: str = DEFAULT_RANK_CONTRACT,
    ) -> None:
        if isinstance(random_state, bool) or not isinstance(random_state, int):
            raise TypeError("random_state must be integer")
        if (
            isinstance(hgb_max_iter, bool)
            or not isinstance(hgb_max_iter, int)
            or hgb_max_iter <= 0
        ):
            raise TypeError("hgb_max_iter must be a positive integer")
        if (
            isinstance(ridge_alpha, bool)
            or not isinstance(ridge_alpha, int)
            or ridge_alpha <= 0
        ):
            raise TypeError("ridge_alpha must be a positive integer")
        self._random_state = random_state
        self._hgb_max_iter = hgb_max_iter
        self._ridge_alpha = ridge_alpha
        self._rank_contract = validate_rank_contract(rank_contract)

    def fit(
        self,
        *,
        dataset_id: str,
        samples: Sequence[AllocationTrainingSample],
        feature_packs: Sequence[FeaturePackDefinition],
        folds: Sequence[PurgedWalkForwardFold],
        training_as_of: str,
        dataset_manifest_file_hash: str,
        horizons: Sequence[int] = SUPPORTED_HORIZONS,
    ) -> AllocationTrainingResult:
        """訓練 base experts 與 Meta Allocator。

        任何 cutoff、fold ownership、purge 或 OOF 重疊違規都會 fail closed；
        不會靜默丟棄列後繼續訓練。
        """

        _require_text(dataset_id=dataset_id, training_as_of=training_as_of)
        _require_sha256(
            dataset_manifest_file_hash,
            field_name="dataset_manifest_file_hash",
        )
        cutoff = _parse_available_at(training_as_of, field_name="training_as_of")
        canonical_horizons = _validate_horizons(horizons)
        canonical_packs = _validate_feature_packs(feature_packs)
        sample_by_id = self._validate_samples(
            samples=samples,
            feature_packs=canonical_packs,
            horizons=canonical_horizons,
            cutoff=cutoff,
        )
        canonical_folds = self._validate_folds(
            folds=folds,
            sample_by_id=sample_by_id,
            cutoff=cutoff,
            horizons=canonical_horizons,
        )
        manifest_row = next(iter(sample_by_id.values())).row

        base_predictions: list[BaseExpertOOFPrediction] = []
        expert_audits: list[ExpertFoldAudit] = []
        for fold in canonical_folds:
            train = tuple(sample_by_id[row.row_id] for row in fold.train_rows)
            test = tuple(sample_by_id[row.row_id] for row in fold.test_rows)
            train_ids = tuple(sample.row.row_id for sample in train)
            test_ids = tuple(sample.row.row_id for sample in test)
            for pack in canonical_packs:
                for horizon in canonical_horizons:
                    for algorithm in EXPERT_ALGORITHMS:
                        predictions, audit = self._fit_expert_fold(
                            fold=fold,
                            pack=pack,
                            horizon=horizon,
                            algorithm=algorithm,
                            train=train,
                            test=test,
                            train_ids=train_ids,
                            test_ids=test_ids,
                            rank_contract=self._rank_contract,
                        )
                        base_predictions.extend(predictions)
                        expert_audits.append(audit)

        canonical_base = tuple(
            sorted(
                base_predictions,
                key=lambda row: (
                    row.decision_date,
                    row.row_id,
                    row.pack_id,
                    row.horizon_trading_days,
                    row.algorithm,
                ),
            )
        )
        expert_keys = tuple(
            f"{pack.pack_id}|h{horizon}|{algorithm}"
            for pack in canonical_packs
            for horizon in canonical_horizons
            for algorithm in EXPERT_ALGORITHMS
        )
        meta_matrix_by_row = _build_meta_oof_matrix(
            predictions=canonical_base,
            folds=canonical_folds,
            expert_keys=expert_keys,
        )
        meta_predictions, meta_audits = self._fit_time_causal_meta_oof(
            folds=canonical_folds,
            sample_by_id=sample_by_id,
            meta_matrix_by_row=meta_matrix_by_row,
            expert_keys=expert_keys,
        )
        final_meta_models = self._fit_meta_models(
            row_ids=tuple(sorted(meta_matrix_by_row)),
            sample_by_id=sample_by_id,
            meta_matrix_by_row=meta_matrix_by_row,
        )
        family_weights = _feature_family_weights(
            packs=canonical_packs,
            expert_keys=expert_keys,
            meta_models=final_meta_models,
            observed_family_ids=_observed_family_ids(
                samples=tuple(sample_by_id.values()),
                packs=canonical_packs,
            ),
        )
        final_base_models = self._fit_final_base_models(
            samples=tuple(sample_by_id[row_id] for row_id in sorted(sample_by_id)),
            packs=canonical_packs,
            horizons=canonical_horizons,
        )

        artifact_payload: dict[str, Any] = {
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "dataset_identity_hash": manifest_row.dataset_identity_hash,
            "dataset_manifest_file_hash": dataset_manifest_file_hash,
            "feature_registry_hash": manifest_row.feature_registry_hash,
            "source_manifest_hashes": manifest_row.source_manifest_hashes,
            "training_as_of": cutoff.isoformat(),
            "feature_packs": tuple(
                (pack.pack_id, pack.feature_ids) for pack in canonical_packs
            ),
            "horizons": canonical_horizons,
            "expert_keys": expert_keys,
            "expert_head_ids": EXPERT_HEAD_IDS,
            "expert_vector_width": EXPERT_VECTOR_WIDTH,
            "rank_contract": self._rank_contract,
            "base_models": final_base_models,
            "meta_models": final_meta_models,
            "feature_family_weights_bp": family_weights,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
        }
        artifact_buffer = BytesIO()
        joblib.dump(artifact_payload, artifact_buffer, compress=0)
        artifact_bytes = artifact_buffer.getvalue()
        artifact_hash = _sha256(artifact_bytes)

        audit_payload = {
            "schema_version": "allocation-training-audit-v3",
            "model_artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "dataset_identity_hash": manifest_row.dataset_identity_hash,
            "dataset_manifest_file_hash": dataset_manifest_file_hash,
            "feature_registry_hash": manifest_row.feature_registry_hash,
            "source_manifest_hashes": [
                [source_id, source_hash]
                for source_id, source_hash in manifest_row.source_manifest_hashes
            ],
            "training_as_of": cutoff.isoformat(),
            "horizons": list(canonical_horizons),
            "expert_head_ids": list(EXPERT_HEAD_IDS),
            "expert_vector_width": EXPERT_VECTOR_WIDTH,
            "rank_contract": self._rank_contract,
            "feature_packs": [
                {
                    "pack_id": pack.pack_id,
                    "feature_ids": list(pack.feature_ids),
                }
                for pack in canonical_packs
            ],
            "outer_fold_ids": [fold.fold_id for fold in canonical_folds],
            "base_oof_predictions": [
                asdict(prediction) for prediction in canonical_base
            ],
            "expert_fold_audits": [
                _expert_fold_audit_payload(audit)
                for audit in sorted(
                    expert_audits,
                    key=lambda row: (
                        row.fold_id,
                        row.pack_id,
                        row.horizon_trading_days,
                        row.algorithm,
                    ),
                )
            ],
            "meta_oof_predictions": [
                _meta_oof_prediction_payload(prediction)
                for prediction in sorted(
                    meta_predictions,
                    key=lambda row: (row.decision_date, row.row_id),
                )
            ],
            "meta_fold_audits": [
                _meta_fold_audit_payload(audit) for audit in meta_audits
            ],
            "feature_family_weights_bp": [
                [family_id, weight_bp]
                for family_id, weight_bp in family_weights
            ],
            "artifact_hash": artifact_hash,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
        }
        audit_json_without_replay_hash = json.dumps(
            audit_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        replay_hash = _sha256(audit_json_without_replay_hash.encode("utf-8"))
        audit_payload["replay_hash"] = replay_hash
        audit_json = json.dumps(
            audit_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        return AllocationTrainingResult(
            dataset_id=dataset_id,
            dataset_identity_hash=manifest_row.dataset_identity_hash,
            dataset_manifest_file_hash=dataset_manifest_file_hash,
            feature_registry_hash=manifest_row.feature_registry_hash,
            source_manifest_hashes=manifest_row.source_manifest_hashes,
            training_as_of=cutoff.isoformat(),
            horizons=canonical_horizons,
            feature_pack_ids=tuple(pack.pack_id for pack in canonical_packs),
            outer_fold_ids=tuple(fold.fold_id for fold in canonical_folds),
            base_oof_predictions=canonical_base,
            expert_fold_audits=tuple(
                sorted(
                    expert_audits,
                    key=lambda row: (
                        row.fold_id,
                        row.pack_id,
                        row.horizon_trading_days,
                        row.algorithm,
                    ),
                )
            ),
            meta_oof_predictions=tuple(
                sorted(
                    meta_predictions,
                    key=lambda row: (row.decision_date, row.row_id),
                )
            ),
            meta_fold_audits=tuple(meta_audits),
            feature_family_weights_bp=family_weights,
            artifact_bytes=artifact_bytes,
            artifact_hash=artifact_hash,
            replay_hash=replay_hash,
            audit_json=audit_json,
            rank_contract=self._rank_contract,
        )

    def _validate_samples(
        self,
        *,
        samples: Sequence[AllocationTrainingSample],
        feature_packs: tuple[FeaturePackDefinition, ...],
        horizons: tuple[int, ...],
        cutoff: datetime,
    ) -> dict[str, AllocationTrainingSample]:
        if not samples:
            raise ValueError("allocation training samples are required")
        sample_by_id: dict[str, AllocationTrainingSample] = {}
        required_feature_ids = {
            feature_id
            for pack in feature_packs
            for feature_id in pack.feature_ids
        }
        for sample in samples:
            row = sample.row
            if row.row_id in sample_by_id:
                raise ValueError("allocation training row ids must be unique")
            decision_at = _parse_decision_at(row.decision_at)
            if decision_at > cutoff:
                raise ValueError("decision_at exceeds training_as_of")
            targets = _require_targets(sample)
            if not targets.is_fit_eligible(training_as_of=cutoff.isoformat()):
                raise ValueError("AllocationTargets availability exceeds training_as_of")
            labels = {
                label.horizon_trading_days: label
                for label in sample.horizon_labels
            }
            if set(labels) != set(horizons):
                raise ValueError("every sample must contain every configured horizon")
            if any(
                _parse_available_at(
                    label.available_at, field_name="label.available_at"
                )
                > cutoff
                for label in labels.values()
            ):
                raise ValueError("horizon label availability exceeds training_as_of")
            feature_by_id = {
                feature.feature_id: feature for feature in row.features
            }
            if not required_feature_ids.issubset(feature_by_id):
                missing = sorted(required_feature_ids - set(feature_by_id))
                raise ValueError(
                    f"training row is missing registered feature: {missing[0]}"
                )
            unexpected = set(feature_by_id) - required_feature_ids
            if unexpected:
                raise ValueError(
                    "every training feature must be assigned to an explicit "
                    f"feature pack: {sorted(unexpected)[0]}"
                )
            for pack in feature_packs:
                for feature_id in pack.feature_ids:
                    feature = feature_by_id[feature_id]
                    if feature.family_id != pack.pack_id:
                        raise ValueError(
                            f"feature {feature_id} does not belong to pack {pack.pack_id}"
                        )
            sample_by_id[row.row_id] = sample
        if len(
            {sample.row.dataset_identity_hash for sample in sample_by_id.values()}
        ) != 1:
            raise ValueError("training rows must share one dataset identity hash")
        if len(
            {sample.row.feature_registry_hash for sample in sample_by_id.values()}
        ) != 1:
            raise ValueError("training rows must share one feature registry hash")
        if len(
            {
                sample.row.source_manifest_hashes
                for sample in sample_by_id.values()
            }
        ) != 1:
            raise ValueError("training rows must share one source manifest set")
        return sample_by_id

    def _validate_folds(
        self,
        *,
        folds: Sequence[PurgedWalkForwardFold],
        sample_by_id: Mapping[str, AllocationTrainingSample],
        cutoff: datetime,
        horizons: tuple[int, ...],
    ) -> tuple[PurgedWalkForwardFold, ...]:
        if len(folds) < 4:
            raise ValueError("allocation training requires at least four outer folds")
        fold_ids = tuple(fold.fold_id for fold in folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("outer fold ids must be unique")
        ordered = tuple(
            sorted(folds, key=lambda fold: (fold.test_start, fold.fold_id))
        )
        observed_decision_dates = tuple(
            sorted(
                {
                    _parse_decision_at(sample.row.decision_at).date()
                    for sample in sample_by_id.values()
                }
            )
        )
        decision_date_index = {
            decision_date: index
            for index, decision_date in enumerate(observed_decision_dates)
        }
        seen_test_rows: set[str] = set()
        previous_test_end: date | None = None
        previous_train_ids: set[str] | None = None
        for fold in ordered:
            if fold.purge_trading_days < 60 or fold.embargo_trading_days < 5:
                raise ValueError(
                    "outer folds must enforce at least purge=60 and embargo=5"
                )
            train_ids = tuple(row.row_id for row in fold.train_rows)
            test_ids = tuple(row.row_id for row in fold.test_rows)
            if not train_ids or not test_ids:
                raise ValueError("every outer fold requires train and test rows")
            if len(train_ids) != len(set(train_ids)):
                raise ValueError("outer fold train row ids must be unique")
            if len(test_ids) != len(set(test_ids)):
                raise ValueError("outer fold test row ids must be unique")
            if set(train_ids) & set(test_ids):
                raise ValueError("outer fold train and test rows must be disjoint")
            overlap = seen_test_rows & set(test_ids)
            if overlap:
                raise ValueError("a row may appear in only one outer test fold")
            seen_test_rows.update(test_ids)
            unknown = (set(train_ids) | set(test_ids)) - set(sample_by_id)
            if unknown:
                raise ValueError(f"fold references unknown row: {sorted(unknown)[0]}")
            test_start = _parse_date(fold.test_start, field_name="test_start")
            test_end = _parse_date(fold.test_end, field_name="test_end")
            if test_end < test_start:
                raise ValueError("outer fold test_end must not precede test_start")
            if previous_test_end is not None and test_start <= previous_test_end:
                raise ValueError("outer fold test periods must be strictly ordered")
            if (
                test_start not in decision_date_index
                or test_end not in decision_date_index
            ):
                raise ValueError(
                    "outer fold boundaries require observed decision dates"
                )
            if previous_test_end is not None:
                actual_embargo_days = (
                    decision_date_index[test_start]
                    - decision_date_index[previous_test_end]
                    - 1
                )
                if actual_embargo_days < fold.embargo_trading_days:
                    raise ValueError(
                        "outer fold actual embargo is shorter than declared "
                        "embargo_trading_days"
                    )
            previous_test_end = test_end
            train_id_set = set(train_ids)
            if (
                previous_train_ids is not None
                and not previous_train_ids.issubset(train_id_set)
            ):
                raise ValueError(
                    "outer fold train rows must form an expanding window"
                )
            previous_train_ids = train_id_set

            fold_decision_at = datetime.combine(
                test_start, time(8, 30), tzinfo=_TAIPEI
            )
            latest_train_date = max(
                _parse_decision_at(
                    sample_by_id[row.row_id].row.decision_at
                ).date()
                for row in fold.train_rows
            )
            if latest_train_date not in decision_date_index:
                raise ValueError(
                    "outer fold train boundary requires observed decision dates"
                )
            actual_purge_days = (
                decision_date_index[test_start]
                - decision_date_index[latest_train_date]
                - 1
            )
            if actual_purge_days < fold.purge_trading_days:
                raise ValueError(
                    "outer fold actual purge is shorter than declared "
                    "purge_trading_days"
                )
            for window_row in fold.train_rows:
                sample = sample_by_id[window_row.row_id]
                if _parse_decision_at(sample.row.decision_at) >= fold_decision_at:
                    raise ValueError("outer train decision crosses test start")
                max_horizon_end = max(
                    _parse_date(label.horizon_end_date, field_name="horizon_end_date")
                    for label in sample.horizon_labels
                    if label.horizon_trading_days in horizons
                )
                if max_horizon_end >= test_start:
                    raise ValueError("outer train label horizon crosses test start")
                if any(
                    _parse_available_at(
                        label.available_at, field_name="label.available_at"
                    )
                    > fold_decision_at
                    for label in sample.horizon_labels
                    if label.horizon_trading_days in horizons
                ):
                    raise ValueError(
                        "outer train horizon label was unavailable at test start"
                    )
                targets = _require_targets(sample)
                if _parse_available_at(
                    targets.available_at, field_name="targets.available_at"
                ) > fold_decision_at:
                    raise ValueError(
                        "outer train AllocationTargets were unavailable at test start"
                    )
            for window_row in fold.test_rows:
                sample = sample_by_id[window_row.row_id]
                decision = _parse_decision_at(sample.row.decision_at)
                if not test_start <= decision.date() <= test_end:
                    raise ValueError(
                        "outer test row decision must lie inside its test period"
                    )
                if decision > cutoff:
                    raise ValueError("outer test decision exceeds training_as_of")
        return ordered

    def _fit_expert_fold(
        self,
        *,
        fold: PurgedWalkForwardFold,
        pack: FeaturePackDefinition,
        horizon: int,
        algorithm: str,
        train: tuple[AllocationTrainingSample, ...],
        test: tuple[AllocationTrainingSample, ...],
        train_ids: tuple[str, ...],
        test_ids: tuple[str, ...],
        rank_contract: str = DEFAULT_RANK_CONTRACT,
    ) -> tuple[tuple[BaseExpertOOFPrediction, ...], ExpertFoldAudit]:
        if len(train) < 10:
            raise ValueError("every expert fold requires at least ten train rows")
        x_train = _pack_matrix(train, pack=pack, algorithm=algorithm)
        x_test = _pack_matrix(test, pack=pack, algorithm=algorithm)
        model_payload = self._fit_expert_head_models(
            algorithm=algorithm,
            x=x_train,
            samples=train,
            horizon=horizon,
            shared_fit_row_ids=train_ids,
        )
        head_values: dict[str, tuple[int | None, ...]] = {}
        missing_heads = tuple(
            sorted(model_payload["head_missing_reasons"])
        )
        regression_models = model_payload["regression_models"]
        for head_id in REGRESSION_EXPERT_HEADS:
            model = regression_models[head_id]
            if model is None:
                fallback: int | None = (
                    None
                    if head_id == "expected_sector_excess_return_bp"
                    else 0
                )
                head_values[head_id] = tuple(fallback for _ in test)
                continue
            raw_prediction = np.asarray(
                model.predict(x_test),
                dtype=float,  # numeric-boundary: analytics
            )
            quantizer = (
                _quantize_signed_bp
                if head_id in _SIGNED_REGRESSION_HEADS
                else _quantize_non_negative_bp
            )
            head_values[head_id] = tuple(
                quantizer(value) for value in raw_prediction
            )

        classification_models = model_payload["classification_models"]
        for head_id in CLASSIFICATION_EXPERT_HEADS:
            model = classification_models[head_id]
            if model is None:
                head_values[head_id] = tuple(5_000 for _ in test)
                continue
            raw_probability = np.asarray(
                model.predict_proba(x_test)[:, 1],
                dtype=float,  # numeric-boundary: analytics
            )
            head_values[head_id] = tuple(
                _quantize_probability_bp(value)
                for value in raw_probability
            )

        quantized_returns = tuple(
            _required_prediction_int(
                value,
                field_name="expected_excess_return_bp",
            )
            for value in head_values["expected_excess_return_bp"]
        )
        rank_by_index = _rank_bp_by_decision(
            test=test,
            predicted_returns=quantized_returns,
            rank_contract=rank_contract,
        )
        predictions = tuple(
            BaseExpertOOFPrediction(
                row_id=sample.row.row_id,
                decision_date=_parse_decision_at(
                    sample.row.decision_at
                ).date().isoformat(),
                fold_id=fold.fold_id,
                pack_id=pack.pack_id,
                horizon_trading_days=horizon,
                algorithm=algorithm,  # type: ignore[arg-type]
                expected_excess_return_bp=quantized_returns[index],
                expected_sector_excess_return_bp=_optional_prediction_int(
                    head_values["expected_sector_excess_return_bp"][index],
                    field_name="expected_sector_excess_return_bp",
                ),
                downside_probability_bp=_required_prediction_int(
                    head_values["downside_probability_bp"][index],
                    field_name="downside_probability_bp",
                ),
                predicted_mae_bp=_required_prediction_int(
                    head_values["predicted_mae_bp"][index],
                    field_name="predicted_mae_bp",
                ),
                predicted_mfe_bp=_required_prediction_int(
                    head_values["predicted_mfe_bp"][index],
                    field_name="predicted_mfe_bp",
                ),
                predicted_realized_volatility_bp=_required_prediction_int(
                    head_values["predicted_realized_volatility_bp"][index],
                    field_name="predicted_realized_volatility_bp",
                ),
                predicted_max_drawdown_bp=_required_prediction_int(
                    head_values["predicted_max_drawdown_bp"][index],
                    field_name="predicted_max_drawdown_bp",
                ),
                predicted_tail_loss_bp=_required_prediction_int(
                    head_values["predicted_tail_loss_bp"][index],
                    field_name="predicted_tail_loss_bp",
                ),
                fill_feasibility_probability_bp=_required_prediction_int(
                    head_values["fill_feasibility_probability_bp"][index],
                    field_name="fill_feasibility_probability_bp",
                ),
                rank_bp=rank_by_index[index],
                missing_head_ids=missing_heads,
            )
            for index, sample in enumerate(test)
        )
        head_fit_mapping = model_payload["head_fit_row_ids"]
        classifier_fit_ids = (
            train_ids
            if any(
                head_fit_mapping[head_id]
                for head_id in CLASSIFICATION_EXPERT_HEADS
            )
            else ()
        )
        audit = ExpertFoldAudit(
            fold_id=fold.fold_id,
            pack_id=pack.pack_id,
            horizon_trading_days=horizon,
            algorithm=algorithm,  # type: ignore[arg-type]
            model_fit_row_ids=train_ids,
            preprocessor_fit_row_ids=train_ids,
            calibrator_fit_row_ids=classifier_fit_ids,
            test_row_ids=test_ids,
            preprocessing_strategy=model_payload["preprocessing_strategy"],
            head_fit_row_ids=tuple(
                (head_id, head_fit_mapping[head_id])
                for head_id in EXPERT_HEAD_IDS
            ),
            missing_head_ids=missing_heads,
        )
        return predictions, audit

    def _fit_expert_head_models(
        self,
        *,
        algorithm: str,
        x: NDArray[np.float64],
        samples: tuple[AllocationTrainingSample, ...],
        horizon: int,
        shared_fit_row_ids: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        labels = tuple(_horizon_label(sample, horizon) for sample in samples)
        all_fit_row_ids = (
            shared_fit_row_ids
            if shared_fit_row_ids is not None
            else tuple(sample.row.row_id for sample in samples)
        )
        if len(all_fit_row_ids) != len(samples):
            raise ValueError("shared fit row ids must match expert samples")
        regression_models: dict[str, Any | None] = {}
        classification_models: dict[str, Any | None] = {}
        head_fit_row_ids: dict[str, tuple[str, ...]] = {}
        head_missing_reasons: dict[str, str] = {}

        for head_id in REGRESSION_EXPERT_HEADS:
            label_field = _REGRESSION_LABEL_FIELDS[head_id]
            eligible_indices = tuple(
                index
                for index, label in enumerate(labels)
                if getattr(label, label_field) is not None
            )
            if len(eligible_indices) < 2:
                if head_id != "expected_sector_excess_return_bp":
                    raise ValueError(
                        f"required regression head has insufficient labels: {head_id}"
                    )
                regression_models[head_id] = None
                head_fit_row_ids[head_id] = ()
                head_missing_reasons[head_id] = (
                    "pit_sector_benchmark_labels_unavailable"
                )
                continue
            matrix = x[np.asarray(eligible_indices, dtype=int)]
            target = np.asarray(
                [
                    _required_label_integer(
                        getattr(labels[index], label_field),
                        field_name=label_field,
                    )
                    for index in eligible_indices
                ],
                dtype=float,  # numeric-boundary: analytics
            )
            regression_models[head_id] = self._fit_regression_model(
                algorithm=algorithm,
                x=matrix,
                target=target,
            )
            head_fit_row_ids[head_id] = (
                all_fit_row_ids
                if len(eligible_indices) == len(samples)
                else tuple(
                    samples[index].row.row_id
                    for index in eligible_indices
                )
            )

        for head_id in CLASSIFICATION_EXPERT_HEADS:
            label_field = _CLASSIFICATION_LABEL_FIELDS[head_id]
            target = np.asarray(
                [
                    int(
                        _required_label_bool(
                            getattr(label, label_field),
                            field_name=label_field,
                        )
                    )
                    for label in labels
                ],
                dtype=int,
            )
            class_counts = tuple(
                int(np.sum(target == class_value))
                for class_value in (0, 1)
            )
            if min(class_counts) < 2:
                classification_models[head_id] = None
                head_fit_row_ids[head_id] = ()
                head_missing_reasons[head_id] = (
                    "classifier_requires_two_rows_per_class"
                )
                continue
            classification_models[head_id] = self._fit_classifier_model(
                algorithm=algorithm,
                x=x,
                target=target,
            )
            head_fit_row_ids[head_id] = all_fit_row_ids

        return {
            "regression_models": regression_models,
            "classification_models": classification_models,
            "preprocessing_strategy": _preprocessing_strategy(algorithm),
            "head_fit_row_ids": head_fit_row_ids,
            "head_missing_reasons": head_missing_reasons,
            "fit_row_ids": all_fit_row_ids,
        }

    def _fit_regression_model(
        self,
        *,
        algorithm: str,
        x: NDArray[np.float64],
        target: NDArray[np.float64],
    ) -> Any:
        if algorithm == "ridge_logistic":
            model: Any = Pipeline(
                (
                    (
                        "imputer",
                        SimpleImputer(
                            strategy="median",
                            add_indicator=True,
                            keep_empty_features=True,
                        ),
                    ),
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        Ridge(
                            alpha=float(  # numeric-boundary: analytics
                                self._ridge_alpha
                            )
                        ),
                    ),
                )
            )
        elif algorithm == "hist_gradient_boosting":
            model = HistGradientBoostingRegressor(
                max_iter=self._hgb_max_iter,
                learning_rate=0.05,
                max_depth=3,
                early_stopping=False,
                random_state=self._random_state,
            )
        else:
            raise ValueError("unsupported expert algorithm")
        return model.fit(x, target)

    def _fit_classifier_model(
        self,
        *,
        algorithm: str,
        x: NDArray[np.float64],
        target: NDArray[np.int_],
    ) -> Any:
        if algorithm == "ridge_logistic":
            classifier: Any = Pipeline(
                (
                    (
                        "imputer",
                        SimpleImputer(
                            strategy="median",
                            add_indicator=True,
                            keep_empty_features=True,
                        ),
                    ),
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        LogisticRegression(
                            C=1.0,
                            max_iter=500,
                            random_state=self._random_state,
                        ),
                    ),
                )
            )
        elif algorithm == "hist_gradient_boosting":
            classifier = HistGradientBoostingClassifier(
                max_iter=self._hgb_max_iter,
                learning_rate=0.05,
                max_depth=3,
                early_stopping=False,
                random_state=self._random_state,
            )
        else:
            raise ValueError("unsupported expert algorithm")

        minimum_class_count = int(
            min(np.sum(target == 0), np.sum(target == 1))
        )
        calibration_folds = min(3, minimum_class_count)
        if calibration_folds < 2:
            raise ValueError("calibration requires at least two rows in each class")
        calibrated_classifier = CalibratedClassifierCV(
            estimator=classifier,
            method="sigmoid",
            cv=calibration_folds,
            n_jobs=None,
        )
        return calibrated_classifier.fit(x, target)

    def _fit_time_causal_meta_oof(
        self,
        *,
        folds: tuple[PurgedWalkForwardFold, ...],
        sample_by_id: Mapping[str, AllocationTrainingSample],
        meta_matrix_by_row: Mapping[str, tuple[int, ...]],
        expert_keys: tuple[str, ...],
    ) -> tuple[
        tuple[MetaAllocatorOOFPrediction, ...],
        tuple[MetaFoldAudit, ...],
    ]:
        del expert_keys
        predictions: list[MetaAllocatorOOFPrediction] = []
        audits: list[MetaFoldAudit] = []
        prior_row_ids: list[str] = []
        owner_fold_by_row: dict[str, str] = {}
        for fold_index, fold in enumerate(folds):
            current_test_ids = tuple(row.row_id for row in fold.test_rows)
            if fold_index > 0:
                fold_decision_at = datetime.combine(
                    _parse_date(fold.test_start, field_name="test_start"),
                    time(8, 30),
                    tzinfo=_TAIPEI,
                )
                matured_prior_row_ids = tuple(
                    row_id
                    for row_id in prior_row_ids
                    if _parse_available_at(
                        _require_targets(sample_by_id[row_id]).available_at,
                        field_name="targets.available_at",
                    )
                    <= fold_decision_at
                )
                if not matured_prior_row_ids:
                    raise ValueError(
                        "meta allocator has no matured prior OOF AllocationTargets"
                    )
                matured_fit_fold_ids = tuple(
                    dict.fromkeys(
                        owner_fold_by_row[row_id]
                        for row_id in matured_prior_row_ids
                    )
                )
                models = self._fit_meta_models(
                    row_ids=matured_prior_row_ids,
                    sample_by_id=sample_by_id,
                    meta_matrix_by_row=meta_matrix_by_row,
                )
                x_test = np.asarray(
                    [meta_matrix_by_row[row_id] for row_id in current_test_ids],
                    dtype=float,  # numeric-boundary: analytics
                )
                numeric_predictions = {
                    field_name: np.asarray(
                        model.predict(x_test),
                        dtype=float,  # numeric-boundary: analytics
                    )
                    for field_name, model in models["numeric"].items()
                }
                rebalance_probability = np.asarray(
                    models["rebalance"].predict_proba(x_test)[:, 1],
                    dtype=float,  # numeric-boundary: analytics
                )
                for row_index, row_id in enumerate(current_test_ids):
                    sample = sample_by_id[row_id]
                    predictions.append(
                        MetaAllocatorOOFPrediction(
                            row_id=row_id,
                            decision_date=_parse_decision_at(
                                sample.row.decision_at
                            ).date().isoformat(),
                            fold_id=fold.fold_id,
                            fit_fold_ids=matured_fit_fold_ids,
                            fit_row_ids=matured_prior_row_ids,
                            target_weight_bp=_quantize_bounded_bp(
                                numeric_predictions["target_weight_bp"][row_index]
                            ),
                            delta_weight_bp=_quantize_signed_bp(
                                numeric_predictions["delta_weight_bp"][row_index]
                            ),
                            risk_contribution_bp=_quantize_bounded_bp(
                                numeric_predictions["risk_contribution_bp"][
                                    row_index
                                ]
                            ),
                            risky_budget_bp=_quantize_bounded_bp(
                                numeric_predictions["risky_budget_bp"][row_index]
                            ),
                            cash_bp=_quantize_bounded_bp(
                                numeric_predictions["cash_bp"][row_index]
                            ),
                            rebalance_worthwhile=bool(
                                rebalance_probability[row_index] >= 0.5
                            ),
                        )
                    )
                audits.append(
                    MetaFoldAudit(
                        fold_id=fold.fold_id,
                        fit_fold_ids=matured_fit_fold_ids,
                        fit_row_ids=matured_prior_row_ids,
                        test_row_ids=current_test_ids,
                    )
                )
            prior_row_ids.extend(current_test_ids)
            owner_fold_by_row.update(
                {row_id: fold.fold_id for row_id in current_test_ids}
            )
        if len({row.fold_id for row in predictions}) < 3:
            raise ValueError(
                "time-causal meta OOF requires at least three predicted outer folds"
            )
        return tuple(predictions), tuple(audits)

    def _fit_meta_models(
        self,
        *,
        row_ids: tuple[str, ...],
        sample_by_id: Mapping[str, AllocationTrainingSample],
        meta_matrix_by_row: Mapping[str, tuple[int, ...]],
    ) -> dict[str, Any]:
        if not row_ids:
            raise ValueError("meta allocator requires OOF rows")
        matrix = np.asarray(
            [meta_matrix_by_row[row_id] for row_id in row_ids],
            dtype=float,  # numeric-boundary: analytics
        )
        target_fields = {
            "target_weight_bp": np.asarray(
                [
                    _symbol_target(sample_by_id[row_id])
                    for row_id in row_ids
                ],
                dtype=float,  # numeric-boundary: analytics
            ),
            "delta_weight_bp": np.asarray(
                [
                    _symbol_delta(sample_by_id[row_id])
                    for row_id in row_ids
                ],
                dtype=float,  # numeric-boundary: analytics
            ),
            "risk_contribution_bp": np.asarray(
                [
                    _symbol_risk_contribution(sample_by_id[row_id])
                    for row_id in row_ids
                ],
                dtype=float,  # numeric-boundary: analytics
            ),
            "risky_budget_bp": np.asarray(
                [
                    _require_targets(sample_by_id[row_id]).risky_budget_bp
                    for row_id in row_ids
                ],
                dtype=float,  # numeric-boundary: analytics
            ),
            "cash_bp": np.asarray(
                [
                    _require_targets(sample_by_id[row_id]).cash_bp
                    for row_id in row_ids
                ],
                dtype=float,  # numeric-boundary: analytics
            ),
        }
        numeric_models: dict[str, Pipeline] = {}
        for field_name, target in target_fields.items():
            numeric_models[field_name] = Pipeline(
                (
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        Ridge(
                            alpha=float(  # numeric-boundary: analytics
                                self._ridge_alpha
                            )
                        ),
                    ),
                )
            ).fit(matrix, target)

        rebalance_target = np.asarray(
            [
                int(_require_targets(sample_by_id[row_id]).rebalance_worthwhile)
                for row_id in row_ids
            ],
            dtype=int,
        )
        if len(np.unique(rebalance_target)) == 2:
            rebalance_model: Any = Pipeline(
                (
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        LogisticRegression(
                            C=1.0,
                            max_iter=500,
                            random_state=self._random_state,
                        ),
                    ),
                )
            ).fit(matrix, rebalance_target)
        else:
            rebalance_model = _ConstantProbabilityClassifier(
                positive_probability=int(rebalance_target[0])
            )
        return {
            "numeric": numeric_models,
            "rebalance": rebalance_model,
            "fit_row_ids": row_ids,
        }

    def _fit_final_base_models(
        self,
        *,
        samples: tuple[AllocationTrainingSample, ...],
        packs: tuple[FeaturePackDefinition, ...],
        horizons: tuple[int, ...],
    ) -> dict[str, Any]:
        models: dict[str, Any] = {}
        shared_fit_row_ids = tuple(
            sample.row.row_id for sample in samples
        )
        for pack in packs:
            for horizon in horizons:
                for algorithm in EXPERT_ALGORITHMS:
                    matrix = _pack_matrix(
                        samples,
                        pack=pack,
                        algorithm=algorithm,
                    )
                    model_payload = self._fit_expert_head_models(
                        algorithm=algorithm,
                        x=matrix,
                        samples=samples,
                        horizon=horizon,
                        shared_fit_row_ids=shared_fit_row_ids,
                    )
                    key = f"{pack.pack_id}|h{horizon}|{algorithm}"
                    models[key] = model_payload
        return models


@dataclass(frozen=True)
class _ConstantProbabilityClassifier:
    """Meta label 單一類別時的確定性、可序列化 fallback。"""

    positive_probability: int

    def predict_proba(
        self, x: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        probability = float(  # numeric-boundary: analytics
            self.positive_probability
        )
        return np.asarray(
            [
                [1.0 - probability, probability]
                for _ in range(len(x))
            ],
            dtype=float,  # numeric-boundary: analytics
        )


def _validate_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    if not horizons:
        raise ValueError("at least one horizon is required")
    values: list[int] = []
    for horizon in horizons:
        if (
            isinstance(horizon, bool)
            or not isinstance(horizon, int)
            or horizon <= 0
        ):
            raise TypeError("horizons must contain positive integers")
        values.append(horizon)
    if len(values) != len(set(values)):
        raise ValueError("horizons must be unique")
    return tuple(sorted(values))


def _validate_feature_packs(
    feature_packs: Sequence[FeaturePackDefinition],
) -> tuple[FeaturePackDefinition, ...]:
    if not feature_packs:
        raise ValueError("feature packs are required")
    canonical = tuple(sorted(feature_packs, key=lambda pack: pack.pack_id))
    pack_ids = tuple(pack.pack_id for pack in canonical)
    if len(pack_ids) != len(set(pack_ids)):
        raise ValueError("feature pack ids must be unique")
    feature_ids = [
        feature_id
        for pack in canonical
        for feature_id in pack.feature_ids
    ]
    if len(feature_ids) != len(set(feature_ids)):
        raise ValueError("a feature may belong to only one feature pack")
    return canonical


def _pack_matrix(
    samples: Sequence[AllocationTrainingSample],
    *,
    pack: FeaturePackDefinition,
    algorithm: str,
) -> NDArray[np.float64]:
    value_width = len(pack.feature_ids)
    include_masks = algorithm == "hist_gradient_boosting"
    matrix_width = value_width * (2 if include_masks else 1)
    matrix = np.empty(
        (len(samples), matrix_width),
        dtype=float,  # numeric-boundary: analytics
    )
    matrix[:, :value_width] = np.nan
    if include_masks:
        matrix[:, value_width:] = 1.0
    for row_index, sample in enumerate(samples):
        feature_by_id = {
            feature.feature_id: feature for feature in sample.row.features
        }
        for feature_index, feature_id in enumerate(pack.feature_ids):
            feature = feature_by_id[feature_id]
            if feature.observed:
                assert feature.value_int is not None
                matrix[row_index, feature_index] = (
                    float(  # numeric-boundary: analytics
                        feature.value_int
                    )
                    / float(feature.scale)  # numeric-boundary: analytics
                )
                if include_masks:
                    matrix[row_index, value_width + feature_index] = 0.0
    return matrix


def _build_meta_oof_matrix(
    *,
    predictions: tuple[BaseExpertOOFPrediction, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
    expert_keys: tuple[str, ...],
) -> dict[str, tuple[int, ...]]:
    test_ownership: dict[str, str] = {}
    for fold in folds:
        for row in fold.test_rows:
            if row.row_id in test_ownership:
                raise ValueError("a row may appear in only one outer test fold")
            test_ownership[row.row_id] = fold.fold_id
    values: dict[str, dict[str, tuple[int, ...]]] = {}
    for prediction in predictions:
        if test_ownership.get(prediction.row_id) != prediction.fold_id:
            raise ValueError("base prediction is not owned by its outer test fold")
        by_expert = values.setdefault(prediction.row_id, {})
        if prediction.expert_id in by_expert:
            raise ValueError("duplicate base OOF prediction")
        by_expert[prediction.expert_id] = _base_prediction_vector(
            prediction
        )
    matrix: dict[str, tuple[int, ...]] = {}
    for row_id, by_expert in values.items():
        if set(by_expert) != set(expert_keys):
            raise ValueError(
                f"meta row {row_id} lacks a complete base OOF expert set"
            )
        matrix[row_id] = tuple(
            value
            for expert_key in expert_keys
            for value in by_expert[expert_key]
        )
    if set(matrix) != set(test_ownership):
        raise ValueError("every outer test row requires base OOF predictions")
    return matrix


def _feature_family_weights(
    *,
    packs: tuple[FeaturePackDefinition, ...],
    expert_keys: tuple[str, ...],
    meta_models: Mapping[str, Any],
    observed_family_ids: frozenset[str],
) -> tuple[tuple[str, int], ...]:
    pack_ids = frozenset(pack.pack_id for pack in packs)
    if not observed_family_ids or not observed_family_ids.issubset(pack_ids):
        raise ValueError(
            "feature family weights require at least one observed registered family"
        )
    scores = {pack.pack_id: Decimal("0") for pack in packs}
    numeric_models = meta_models["numeric"]
    for model in numeric_models.values():
        ridge = model.named_steps["model"]
        coefficients = np.asarray(
            ridge.coef_,
            dtype=float,  # numeric-boundary: analytics
        )
        _accumulate_family_coefficients(
            scores=scores,
            coefficients=coefficients,
            expert_keys=expert_keys,
        )
    rebalance = meta_models["rebalance"]
    if isinstance(rebalance, Pipeline):
        logistic = rebalance.named_steps["model"]
        coefficients = np.asarray(
            logistic.coef_[0],
            dtype=float,  # numeric-boundary: analytics
        )
        _accumulate_family_coefficients(
            scores=scores,
            coefficients=coefficients,
            expert_keys=expert_keys,
        )
    for family_id in scores:
        if family_id not in observed_family_ids:
            scores[family_id] = Decimal("0")
    return _largest_remainder_weights(
        scores,
        eligible_family_ids=observed_family_ids,
    )


def _observed_family_ids(
    *,
    samples: tuple[AllocationTrainingSample, ...],
    packs: tuple[FeaturePackDefinition, ...],
) -> frozenset[str]:
    registered = frozenset(pack.pack_id for pack in packs)
    observed = frozenset(
        feature.family_id
        for sample in samples
        for feature in sample.row.features
        if feature.observed and feature.family_id in registered
    )
    return observed


def _accumulate_family_coefficients(
    *,
    scores: dict[str, Decimal],
    coefficients: NDArray[np.float64],
    expert_keys: tuple[str, ...],
) -> None:
    if len(coefficients) != len(expert_keys) * EXPERT_VECTOR_WIDTH:
        raise ValueError("meta coefficient shape does not match expert inputs")
    for expert_index, expert_key in enumerate(expert_keys):
        pack_id = expert_key.split("|", 1)[0]
        start = expert_index * EXPERT_VECTOR_WIDTH
        score = sum(
            Decimal(
                str(
                    abs(
                        float(value)  # numeric-boundary: analytics
                    )
                )
            )
            for value in coefficients[
                start : start + EXPERT_VECTOR_WIDTH
            ]
        )
        scores[pack_id] += score


def _largest_remainder_weights(
    scores: Mapping[str, Decimal],
    *,
    eligible_family_ids: frozenset[str] | None = None,
) -> tuple[tuple[str, int], ...]:
    if not scores:
        raise ValueError("feature family scores are required")
    canonical_ids = tuple(sorted(scores))
    eligible_ids = (
        frozenset(canonical_ids)
        if eligible_family_ids is None
        else eligible_family_ids
    )
    if not eligible_ids or not eligible_ids.issubset(canonical_ids):
        raise ValueError(
            "eligible feature families must be a non-empty score subset"
        )
    total = sum(scores.values(), Decimal("0"))
    if total == 0:
        numerator = {
            family_id: (
                Decimal(1)
                if family_id in eligible_ids
                else Decimal(0)
            )
            for family_id in canonical_ids
        }
        total = Decimal(len(eligible_ids))
    else:
        numerator = dict(scores)
    floors: dict[str, int] = {}
    remainders: list[tuple[Decimal, str]] = []
    for family_id in canonical_ids:
        exact = Decimal(10_000) * numerator[family_id] / total
        floor = int(exact)
        floors[family_id] = floor
        remainders.append((exact - Decimal(floor), family_id))
    remaining = 10_000 - sum(floors.values())
    for _, family_id in sorted(
        remainders, key=lambda item: (-item[0], item[1])
    )[:remaining]:
        floors[family_id] += 1
    return tuple((family_id, floors[family_id]) for family_id in canonical_ids)


def _rank_bp_by_decision(
    *,
    test: tuple[AllocationTrainingSample, ...],
    predicted_returns: tuple[int, ...],
    rank_contract: str = DEFAULT_RANK_CONTRACT,
) -> dict[int, int]:
    grouped: dict[str, list[tuple[int, str, int]]] = {}
    for index, (sample, prediction) in enumerate(zip(test, predicted_returns)):
        decision_date = _parse_decision_at(sample.row.decision_at).date().isoformat()
        grouped.setdefault(decision_date, []).append(
            (prediction, sample.row.symbol, index)
        )
    ranks: dict[int, int] = {}
    for rows in grouped.values():
        values = tuple(item[0] for item in rows)
        tie_keys = tuple(item[1] for item in rows)
        rank_values = rank_values_bp(
            values,
            tie_keys,
            rank_contract=rank_contract,
        )
        for item, rank in zip(rows, rank_values):
            ranks[item[2]] = rank
    return ranks


def _base_prediction_vector(
    prediction: BaseExpertOOFPrediction,
) -> tuple[int, ...]:
    values = (
        prediction.expected_excess_return_bp,
        (
            prediction.expected_sector_excess_return_bp
            if prediction.expected_sector_excess_return_bp is not None
            else 0
        ),
        prediction.predicted_mae_bp,
        prediction.predicted_mfe_bp,
        prediction.predicted_realized_volatility_bp,
        prediction.predicted_max_drawdown_bp,
        prediction.predicted_tail_loss_bp,
        prediction.downside_probability_bp,
        prediction.fill_feasibility_probability_bp,
    )
    missing = set(prediction.missing_head_ids)
    masks = tuple(int(head_id in missing) for head_id in EXPERT_HEAD_IDS)
    result = values + (prediction.rank_bp,) + masks
    if len(result) != EXPERT_VECTOR_WIDTH:
        raise ValueError("base expert vector width mismatch")
    return result


def _preprocessing_strategy(algorithm: str) -> str:
    if algorithm == "ridge_logistic":
        return "head_local_median_indicator_then_standard_scale"
    if algorithm == "hist_gradient_boosting":
        return "native_nan_plus_explicit_missing_mask"
    raise ValueError("unsupported expert algorithm")


def _required_label_integer(value: object, *, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} label is missing")
    return _require_integer(field_name, value)


def _required_label_bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be bool")
    return value


def _required_prediction_int(value: object, *, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} prediction is missing")
    return _require_integer(field_name, value)


def _optional_prediction_int(
    value: object,
    *,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    return _require_integer(field_name, value)


def _symbol_target(sample: AllocationTrainingSample) -> int:
    targets = _require_targets(sample)
    return int(targets.target_weight_bp.get(sample.row.symbol, 0))


def _symbol_delta(sample: AllocationTrainingSample) -> int:
    targets = _require_targets(sample)
    return int(targets.delta_weight_bp.get(sample.row.symbol, 0))


def _symbol_risk_contribution(sample: AllocationTrainingSample) -> int:
    targets = _require_targets(sample)
    return int(targets.risk_contribution_bp.get(sample.row.symbol, 0))


def _require_targets(sample: AllocationTrainingSample) -> AllocationTargets:
    if sample.row.targets is None:
        raise ValueError("allocation sample targets are required")
    return sample.row.targets


def _horizon_label(
    sample: AllocationTrainingSample, horizon: int
) -> AllocationHorizonLabel:
    for label in sample.horizon_labels:
        if label.horizon_trading_days == horizon:
            return label
    raise ValueError(f"sample lacks horizon {horizon}")


def _quantize_signed_bp(value: float | np.floating[Any]) -> int:
    quantized = _round_float_to_integer(value)
    return max(-10_000, min(10_000, quantized))


def _quantize_non_negative_bp(value: float | np.floating[Any]) -> int:
    quantized = _round_float_to_integer(value)
    return max(0, min(10_000, quantized))


def _quantize_bounded_bp(value: float | np.floating[Any]) -> int:
    return _quantize_non_negative_bp(value)


def _quantize_probability_bp(value: float | np.floating[Any]) -> int:
    if not np.isfinite(value):
        raise ValueError("model probability must be finite")
    bounded = max(
        0.0,
        min(
            1.0,
            float(value),  # numeric-boundary: analytics
        ),
    )
    return _round_float_to_integer(bounded * 10_000.0)


def _round_float_to_integer(value: float | np.floating[Any]) -> int:
    numeric = float(value)  # numeric-boundary: analytics
    if not np.isfinite(numeric):
        raise ValueError("model output must be finite")
    return int(
        Decimal(str(numeric)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )


def _require_integer(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer units")
    return value


def _require_bp(field_name: str, value: object) -> int:
    numeric = _require_integer(field_name, value)
    if not 0 <= numeric <= 10_000:
        raise ValueError(f"{field_name} must be within 0..10000 bp")
    return numeric


def _require_text(**values: str) -> None:
    for field_name, value in values.items():
        if not value or not value.strip():
            raise ValueError(f"{field_name} is required")


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _parse_available_at(value: str, *, field_name: str) -> datetime:
    if len(value) == 10:
        parsed_date = _parse_date(value, field_name=field_name)
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


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _row_id_custody(row_ids: Sequence[str]) -> dict[str, object]:
    """以有序 row ids 的 count/hash 保存 fold ownership，避免重複展開 GB 級清單。"""

    encoded = json.dumps(
        list(row_ids),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "count": len(row_ids),
        "ordered_sha256": _sha256(encoded),
    }


def _expert_fold_audit_payload(audit: ExpertFoldAudit) -> dict[str, object]:
    return {
        "fold_id": audit.fold_id,
        "pack_id": audit.pack_id,
        "horizon_trading_days": audit.horizon_trading_days,
        "algorithm": audit.algorithm,
        "preprocessing_strategy": audit.preprocessing_strategy,
        "model_fit_rows": _row_id_custody(audit.model_fit_row_ids),
        "preprocessor_fit_rows": _row_id_custody(
            audit.preprocessor_fit_row_ids
        ),
        "calibrator_fit_rows": _row_id_custody(
            audit.calibrator_fit_row_ids
        ),
        "test_rows": _row_id_custody(audit.test_row_ids),
        "head_fit_rows": [
            {
                "head_id": head_id,
                **_row_id_custody(row_ids),
            }
            for head_id, row_ids in audit.head_fit_row_ids
        ],
        "missing_head_ids": list(audit.missing_head_ids),
    }


def _meta_fold_audit_payload(audit: MetaFoldAudit) -> dict[str, object]:
    return {
        "fold_id": audit.fold_id,
        "fit_fold_ids": list(audit.fit_fold_ids),
        "fit_rows": _row_id_custody(audit.fit_row_ids),
        "test_rows": _row_id_custody(audit.test_row_ids),
    }


def _meta_oof_prediction_payload(
    prediction: MetaAllocatorOOFPrediction,
) -> dict[str, object]:
    """Persist one Meta OOF prediction without repeating its whole fit set.

    ``MetaAllocatorOOFPrediction`` keeps the full fit-row tuple in memory so
    the trainer and tests can prove temporal isolation.  Persisting that same
    tuple on every OOF row grows quadratically with the number of folds and
    rows.  Count plus ordered SHA-256 preserves deterministic custody while
    the fold-level audit retains the authoritative fit/test set membership.
    """

    payload = asdict(prediction)
    fit_row_ids = prediction.fit_row_ids
    payload.pop("fit_row_ids")
    payload["fit_rows"] = _row_id_custody(fit_row_ids)
    return payload
