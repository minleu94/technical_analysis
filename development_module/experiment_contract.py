"""Development-only ML Experiment Contract and Runner.

本模組允許開發者建立並執行獨立、可重現的 ML 開發實驗（Feature Ablation, Model Family Comparison, Bounded Parameters）。
所有運算純屬 Development Research；嚴禁 Formal OOS、Production Promotion、Production Blend 或寫入正式 DB。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, date
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Literal, Mapping, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_module.config import TWStockConfig
from development_module.dataset_integrity import validate_persisted_dataset_v0
from development_module.output_guard import validate_development_output_root
from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY

EXPERIMENT_SCHEMA_VERSION = "terra-development-experiment.v1"

ALLOWED_MODEL_FAMILIES = frozenset({"linear_logistic", "hist_gradient_boosting"})

PREDEFINED_FEATURE_PACKS: dict[str, tuple[str, ...]] = {
    "core_20": tuple(spec.feature_id for spec in CORE_LONG_HISTORY_FEATURE_REGISTRY.specs),
    "technical_only": (
        "close_to_ma_5d_bp",
        "close_to_ma_20d_bp",
        "close_to_ma_60d_bp",
        "rsi_normalized_bp",
        "adx_normalized_bp",
        "macd_normalized_bp",
        "volume_ratio_5d_bp",
        "volume_ratio_20d_bp",
    ),
    "price_only": (
        "stock_return_1d_bp",
        "stock_return_5d_bp",
        "stock_return_20d_bp",
        "stock_return_60d_bp",
        "trailing_volatility_20d_bp",
        "high_low_range_20d_bp",
        "turnover_amount_minor",
    ),
    "price_technical": (
        "stock_return_1d_bp",
        "stock_return_5d_bp",
        "stock_return_20d_bp",
        "stock_return_60d_bp",
        "trailing_volatility_20d_bp",
        "high_low_range_20d_bp",
        "turnover_amount_minor",
        "close_to_ma_5d_bp",
        "close_to_ma_20d_bp",
        "close_to_ma_60d_bp",
        "rsi_normalized_bp",
        "adx_normalized_bp",
        "macd_normalized_bp",
        "volume_ratio_5d_bp",
        "volume_ratio_20d_bp",
    ),
}

_APPLY_FLAGS_DICT = {
    "apply_to_scoring": False,
    "apply_to_recommendation": False,
    "apply_to_portfolio": False,
    "apply_to_exit": False,
}


@dataclass(frozen=True)
class DevelopmentExperimentContract:
    experiment_id: str
    parent_dataset_id: str
    parent_dataset_manifest_hash: str
    feature_ids: tuple[str, ...]
    return_label_id: str = "relative_return_20d_bp"
    downside_label_id: str = "downside_20d_flag"
    training_cutoff_date: str = "2025-12-31"
    evaluation_boundary_date: str = "2026-01-01"
    model_families: tuple[str, ...] = ("linear_logistic", "hist_gradient_boosting")
    random_state: int = 42
    minimum_train_dates: int = 60
    test_date_count: int = 20
    purge_trading_days: int = 20
    embargo_trading_days: int = 5
    model_parameters: dict[str, dict[str, int | float]] = None  # type: ignore[assignment]
    candidate_research_only: bool = False
    development_training_allowed: Literal[True] = True
    formal_oos_allowed: Literal[False] = False
    formal_evidence_credit_authorized: Literal[False] = False
    production_allowed: Literal[False] = False
    production_blend_alpha_bp: Literal[0] = 0
    promotion_allowed: Literal[False] = False
    scheduler_allowed: Literal[False] = False
    broker_allowed: Literal[False] = False
    unblind_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.experiment_id or not self.experiment_id.strip():
            raise ValueError("experiment_id is required")
        if not self.parent_dataset_id or not self.parent_dataset_manifest_hash:
            raise ValueError("parent_dataset_id and parent_dataset_manifest_hash are required")
        if not self.parent_dataset_manifest_hash.startswith("sha256:"):
            raise ValueError("parent_dataset_manifest_hash must be sha256 formatted")
        if not self.feature_ids:
            raise ValueError("feature_ids must not be empty; automatic 'use everything' is forbidden")
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("feature_ids must be unique")
        if self.model_parameters is None:
            object.__setattr__(self, "model_parameters", {})

        # (Defect 3) Cutoff 與 Evaluation Boundary 驗證
        try:
            cutoff = date.fromisoformat(self.training_cutoff_date[:10])
            eval_b = date.fromisoformat(self.evaluation_boundary_date[:10])
            if cutoff >= eval_b:
                raise ValueError("training_cutoff_date must precede evaluation_boundary_date")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid training/evaluation dates: {exc}") from exc

        # (Defect 4) 模型家族 Allowlist 與 model_parameters Bounded Schema 檢查
        if not self.model_families:
            raise ValueError("model_families must not be empty")
        for fam in self.model_families:
            if fam not in ALLOWED_MODEL_FAMILIES:
                raise ValueError(f"unsupported model family '{fam}'; allowed: {sorted(ALLOWED_MODEL_FAMILIES)}")

        _validate_model_parameters(self.model_parameters, self.model_families)

        if self.formal_oos_allowed is not False or self.production_blend_alpha_bp != 0:
            raise ValueError("formal_oos_allowed and production_blend_alpha_bp safety flags are required")
        if self.production_allowed is not False or self.promotion_allowed is not False:
            raise ValueError("production_allowed and promotion_allowed must remain False")

    def content_hash(self) -> str:
        payload = {
            "experiment_id": self.experiment_id,
            "parent_dataset_id": self.parent_dataset_id,
            "parent_dataset_manifest_hash": self.parent_dataset_manifest_hash,
            "feature_ids": list(self.feature_ids),
            "return_label_id": self.return_label_id,
            "downside_label_id": self.downside_label_id,
            "training_cutoff_date": self.training_cutoff_date,
            "evaluation_boundary_date": self.evaluation_boundary_date,
            "model_families": list(self.model_families),
            "random_state": self.random_state,
            "minimum_train_dates": self.minimum_train_dates,
            "test_date_count": self.test_date_count,
            "purge_trading_days": self.purge_trading_days,
            "embargo_trading_days": self.embargo_trading_days,
            "model_parameters": self.model_parameters,
            "candidate_research_only": self.candidate_research_only,
        }
        return _canonical_hash(payload)


@dataclass(frozen=True)
class DevelopmentExperimentResult:
    contract: DevelopmentExperimentContract
    experiment_id: str
    selected_model_family: str
    metrics_by_family: dict[str, dict[str, int]]
    comparison_conclusion: str
    report_file_path: Path
    report_file_sha256: str
    sanitized_projection_path: Path
    sanitized_projection_sha256: str
    report: dict[str, Any]
    projection: dict[str, Any]


@dataclass(frozen=True)
class _ExpSample:
    row_id: str
    decision_date: str
    label_end_date: str
    label_available_date: str
    feature_values: tuple[int | None, ...]
    return_target_bp: int
    downside_target: int


@dataclass(frozen=True)
class _ExpPrediction:
    row: _ExpSample
    fold_id: str
    return_prediction_bp: int
    downside_probability_bp: int


class DevelopmentExperimentRunner:
    """Executes development ML experiments on Dataset V0."""

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

    def run(
        self,
        *,
        manifest_path: str | Path,
        dataset_path: str | Path,
        output_root: str | Path,
        contract: DevelopmentExperimentContract,
        candidate_artifact_path: str | Path | None = None,
        candidate_expected_sha256: str | None = None,
    ) -> DevelopmentExperimentResult:
        config = TWStockConfig()
        safe_root = validate_development_output_root(
            Path(output_root),
            data_root=Path(config.data_root),
            formal_db=Path(config.db_file),
        )
        _verify_no_symlink_escape(safe_root)

        manifest_file = Path(manifest_path).resolve()
        dataset_file = Path(dataset_path).resolve()
        manifest = _load_json_object(manifest_file)
        dataset = _load_json_object(dataset_file)

        # (Defect 2) 全面驗證 Dataset 完整性
        validate_persisted_dataset_v0(
            manifest_file=manifest_file,
            dataset_file=dataset_file,
            manifest=manifest,
            dataset=dataset,
        )

        # (Defect 2) 比對 parent_dataset_id 與 manifest_hash
        if contract.parent_dataset_id != manifest.get("dataset_id"):
            raise ValueError(f"contract parent_dataset_id '{contract.parent_dataset_id}' does not match manifest dataset_id '{manifest.get('dataset_id')}'")
        if contract.parent_dataset_manifest_hash != manifest.get("manifest_hash"):
            raise ValueError(f"parent_dataset_manifest_hash mismatch: contract '{contract.parent_dataset_manifest_hash}' != manifest '{manifest.get('manifest_hash')}'")

        # (Defect 7) Candidate Artifact 處理與 SHA-256 比對
        candidate_info: dict[str, Any] | None = None
        if candidate_artifact_path:
            cand_p = Path(candidate_artifact_path).resolve()
            if not cand_p.is_file():
                raise ValueError(f"candidate artifact not found: {cand_p}")
            cand_content = cand_p.read_bytes()
            computed_h = "sha256:" + hashlib.sha256(cand_content).hexdigest()

            if candidate_expected_sha256:
                norm_exp = candidate_expected_sha256 if candidate_expected_sha256.startswith("sha256:") else f"sha256:{candidate_expected_sha256}"
                if computed_h != norm_exp:
                    raise ValueError(f"candidate artifact SHA-256 mismatch: computed {computed_h} != expected {norm_exp}")

            cand_data = _load_json_object(cand_p)
            candidate_info = {"basename": cand_p.name, "hash": computed_h, "schema": cand_data.get("schema_version")}
            if not contract.candidate_research_only:
                raise ValueError("contract candidate_research_only must be True when candidate artifact is provided")

        # (Defect 1) 嚴格驗證 Feature IDs：未知或非數字特徵，顯式 fail closed 拒絕！
        core_feature_ids = set(spec.feature_id for spec in CORE_LONG_HISTORY_FEATURE_REGISTRY.specs)
        for fid in contract.feature_ids:
            if fid not in core_feature_ids:
                if fid == "mops.ezsearch.statement_publication":
                    raise ValueError("candidate_numeric_feature_materialization_not_implemented: MOPS statement_publication is an availability gate, NOT a numeric model feature")
                raise ValueError(f"candidate_numeric_feature_materialization_not_implemented: feature '{fid}' requires materialization engine")

        # (Defect 3) 嚴格載入 Samples，驗證 T-1 PIT、Label Maturity 與日期邊界
        samples, evaluation_count = _load_experiment_samples(dataset, contract)
        if len(samples) < 20:
            raise ValueError("experiment requires at least twenty eligible fit rows")

        # (Defect 6) 檢查 Output Collision，若報告檔已存在，先行 Fail Closed
        exp_dir = safe_root / "experiments"
        report_file = exp_dir / f"{contract.experiment_id}.json"
        if report_file.exists():
            raise ValueError(f"immutable report file already exists: {report_file}")

        from ml_module.purged_walk_forward import MLTimeWindowRow, PurgedWalkForwardSplitter
        folds = PurgedWalkForwardSplitter(
            minimum_train_dates=contract.minimum_train_dates,
            test_date_count=contract.test_date_count,
            purge_trading_days=contract.purge_trading_days,
            embargo_trading_days=contract.embargo_trading_days,
        ).split(tuple(MLTimeWindowRow(s.row_id, s.decision_date, s.label_end_date) for s in samples))

        oof_by_family = _fit_and_predict_families(samples, folds, contract)
        selected_family = min(
            oof_by_family,
            key=lambda family: (_mae_score(oof_by_family[family]), family),
        )
        selected_predictions = oof_by_family[selected_family]
        calibrated_predictions, calib_id = _calibrate_oof(selected_family, selected_predictions)

        metrics_by_family = {
            fam: _calc_metrics(preds, top_k=5)
            for fam, preds in oof_by_family.items()
        }

        conclusion = "research_observation" if len(samples) >= 40 else "insufficient_evidence"
        captured_time = self._now()

        manifest_hash = _file_sha256(manifest_file)
        dataset_hash = _file_sha256(dataset_file)

        # Internal report lineage (包含內部除錯資訊)
        report_lineage = {
            "experiment_id": contract.experiment_id,
            "contract_hash": contract.content_hash(),
            "dataset_id": manifest.get("dataset_id"),
            "generation_id": manifest.get("generation_id"),
            "manifest_file_path": str(manifest_file),
            "manifest_file_sha256": manifest_hash,
            "dataset_file_path": str(dataset_file),
            "dataset_file_sha256": dataset_hash,
            "selected_feature_ids": list(contract.feature_ids),
            "model_families": list(contract.model_families),
            "training_row_count": len(samples),
            "evaluation_row_count": evaluation_count,
            "candidate_artifact": candidate_info["hash"] if candidate_info else None,
            "generated_at": captured_time.isoformat(),
        }

        # (Defect 5) Sanitized Lineage strictly containing NO raw local file paths!
        sanitized_lineage = {
            "experiment_id": contract.experiment_id,
            "contract_hash": contract.content_hash(),
            "dataset_id": manifest.get("dataset_id"),
            "generation_id": manifest.get("generation_id"),
            "manifest_file_basename": manifest_file.name,
            "manifest_file_sha256": manifest_hash,
            "dataset_file_basename": dataset_file.name,
            "dataset_file_sha256": dataset_hash,
            "selected_feature_ids": list(contract.feature_ids),
            "model_families": list(contract.model_families),
            "training_row_count": len(samples),
            "evaluation_row_count": evaluation_count,
            "candidate_artifact": candidate_info["hash"] if candidate_info else None,
            "generated_at": captured_time.isoformat(),
        }

        report = {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "experiment_id": contract.experiment_id,
            "data_scope": "historical_research_seen_development_data",
            "contract": asdict(contract),
            "selected_model_family": selected_family,
            "metrics_by_family": metrics_by_family,
            "calibration_id": calib_id,
            "comparison_conclusion": conclusion,
            "lineage": report_lineage,
            "safety_flags": {
                "development_training_allowed": True,
                "formal_oos_allowed": False,
                "formal_evidence_credit_authorized": False,
                "production_allowed": False,
                "production_blend_alpha_bp": 0,
                "promotion_allowed": False,
                "scheduler_allowed": False,
                "broker_allowed": False,
                "unblind_allowed": False,
            },
        }

        sanitized_projection = {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "experiment_id": contract.experiment_id,
            "selected_model_family": selected_family,
            "comparison_conclusion": conclusion,
            "feature_ids": list(contract.feature_ids),
            "feature_count": len(contract.feature_ids),
            "identity": {
                "dataset_id": str(manifest.get("dataset_id")),
                "generation_id": str(manifest.get("generation_id")),
                "research_run_id": contract.experiment_id,
            },
            "status": {
                "scope": "historical_research_seen_development_data",
                "formal_oos": False,
                "alpha_bp": 0,
                "promotion_eligible": False,
                "apply_flags": _APPLY_FLAGS_DICT,
            },
            "lineage": sanitized_lineage,
            "frozen_metrics": {
                "selected_family_metrics": metrics_by_family[selected_family],
                "sample_count": len(samples),
            },
            "blockers": ["development_only_experiment_run"],
            "sources": [
                {
                    "source_id": "pit.quarterly_financials",
                    "label": "MOPS 季報發布 (F26-F29 官方秒級時間軸)",
                    "lane": "p0",
                    "status": "candidate",
                    "allowed_use": "research_pit_statement_availability, development_shadow_projection",
                    "observed_rows": 0,
                    "revision": "exp-v1",
                    "owner": "archi",
                    "degraded_reason": "experiment_run_shadow",
                }
            ],
        }

        report_bytes = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        report_sha256 = "sha256:" + hashlib.sha256(report_bytes).hexdigest()

        # (Defect 6) Exclusive Write 獨占寫入
        _exclusive_write_bytes(report_file, report_bytes)

        # (Defect 6) Atomic Replace 寫入最新 Projection
        latest_proj_file = safe_root / "latest_experiment_projection.json"
        proj_bytes = (json.dumps(sanitized_projection, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        proj_sha256 = "sha256:" + hashlib.sha256(proj_bytes).hexdigest()
        _atomic_write_bytes(latest_proj_file, proj_bytes)

        return DevelopmentExperimentResult(
            contract=contract,
            experiment_id=contract.experiment_id,
            selected_model_family=selected_family,
            metrics_by_family=metrics_by_family,
            comparison_conclusion=conclusion,
            report_file_path=report_file,
            report_file_sha256=report_sha256,
            sanitized_projection_path=latest_proj_file,
            sanitized_projection_sha256=proj_sha256,
            report=report,
            projection=sanitized_projection,
        )


def _load_experiment_samples(
    dataset: dict[str, Any], contract: DevelopmentExperimentContract
) -> tuple[tuple[_ExpSample, ...], int]:
    """(Defect 3) 嚴格實作 T-1 PIT 檢查、Label Maturity 與 Cutoff/Evaluation 邊界驗證。"""
    fit_rows = dataset.get("fit_rows", [])
    eval_rows = dataset.get("evaluation_rows", [])
    if not isinstance(fit_rows, list) or not isinstance(eval_rows, list):
        raise ValueError("fit_rows and evaluation_rows arrays are required")

    feature_id_indices = {fid: idx for idx, fid in enumerate(contract.feature_ids)}
    samples: list[_ExpSample] = []

    cutoff_date = contract.training_cutoff_date[:10]
    eval_boundary = contract.evaluation_boundary_date[:10]

    for idx, raw in enumerate(fit_rows):
        if not isinstance(raw, dict):
            continue
        decision_date = str(raw.get("decision_date", ""))[:10]
        if decision_date > cutoff_date:
            continue

        # (Defect 3) 特徵時間嚴格遵循 T-1 PIT
        feature_as_of = str(raw.get("feature_as_of_date", ""))[:10]
        feat_available = str(raw.get("available_date", ""))[:10]
        if feature_as_of >= decision_date or feat_available > decision_date:
            raise ValueError(f"feature timing timing defect: feature_as_of ({feature_as_of}) >= decision ({decision_date}) or available ({feat_available}) > decision")

        features = raw.get("features", [])
        if not isinstance(features, list):
            continue
        feat_map = {item[0]: item[1] for item in features if isinstance(item, list) and len(item) == 2}

        # 檢查所有選定特徵在列中均存在且不違反型態
        values: list[int | None] = []
        for fid in contract.feature_ids:
            if fid not in feat_map:
                raise ValueError(f"feature '{fid}' missing in dataset row for {decision_date}")
            val = feat_map[fid]
            if isinstance(val, bool) or not isinstance(val, (int, type(None))):
                raise TypeError(f"feature '{fid}' value must be integer or null")
            values.append(val)

        labels = raw.get("labels", [])
        if not isinstance(labels, list):
            continue
        labels_by_id = {lbl.get("label_id"): lbl for lbl in labels if isinstance(lbl, dict)}
        ret_lbl = labels_by_id.get(contract.return_label_id)
        down_lbl = labels_by_id.get(contract.downside_label_id)
        if not ret_lbl or not down_lbl:
            raise ValueError(f"required primary labels missing for row {decision_date}")

        # (Defect 3) 驗證 Label Maturity、Availability 與 Cutoff 邊界
        if ret_lbl.get("maturity_status") != "ready" or down_lbl.get("maturity_status") != "ready":
            raise ValueError(f"primary labels must have maturity_status 'ready' for training fit")

        ret_val = ret_lbl.get("value")
        down_val = down_lbl.get("value")
        if isinstance(ret_val, bool) or not isinstance(ret_val, int) or isinstance(down_val, bool) or not isinstance(down_val, int):
            raise TypeError("ready label values must be integer units")

        ret_avail = str(ret_lbl.get("available_date", ""))[:10]
        down_avail = str(down_lbl.get("available_date", ""))[:10]
        if ret_avail > cutoff_date or down_avail > cutoff_date:
            raise ValueError(f"label available_date ({ret_avail}) exceeds training_cutoff_date ({cutoff_date})")
        if ret_avail != down_avail:
            raise ValueError("primary labels must share the same available_date")

        ret_end = str(ret_lbl.get("horizon_end_date", ""))[:10]
        down_end = str(down_lbl.get("horizon_end_date", ""))[:10]
        if ret_end != down_end or ret_end <= decision_date:
            raise ValueError("label horizon_end_date is invalid or inconsistent")

        samples.append(
            _ExpSample(
                row_id=f"{raw.get('symbol')}:{decision_date}:{idx}",
                decision_date=decision_date,
                label_end_date=ret_end,
                label_available_date=ret_avail,
                feature_values=tuple(values),
                return_target_bp=ret_val,
                downside_target=down_val,
            )
        )

    # (Defect 3) 診斷 Evaluation 筆數 (位於 evaluation_boundary_date 之後)
    evaluation_count = sum(
        1 for r in eval_rows
        if isinstance(r, dict) and str(r.get("decision_date", ""))[:10] >= eval_boundary
    )

    return tuple(samples), evaluation_count


def _fit_and_predict_families(
    samples: tuple[_ExpSample, ...],
    folds: tuple[Any, ...],
    contract: DevelopmentExperimentContract,
) -> dict[str, tuple[_ExpPrediction, ...]]:
    by_id = {s.row_id: s for s in samples}
    results: dict[str, list[_ExpPrediction]] = {fam: [] for fam in contract.model_families}

    for fold in folds:
        train = tuple(by_id[r.row_id] for r in fold.train_rows if r.row_id in by_id)
        test = tuple(by_id[r.row_id] for r in fold.test_rows if r.row_id in by_id)
        if len(train) < 10 or not test or len({r.downside_target for r in train}) != 2:
            continue

        for family in contract.model_families:
            ret_model, down_model = _fit_single_family(family, train, contract)
            matrix = _to_matrix(test)
            pred_returns = ret_model.predict(matrix)
            pred_probs = down_model.predict_proba(matrix)[:, 1]

            for row, p_ret, p_prob in zip(test, pred_returns, pred_probs):
                results[family].append(
                    _ExpPrediction(
                        row=row,
                        fold_id=fold.fold_id,
                        return_prediction_bp=int(np.rint(p_ret)),
                        downside_probability_bp=int(np.rint(p_prob * 10_000)),
                    )
                )

    for fam, preds in results.items():
        if len({p.fold_id for p in preds}) < 2:
            raise ValueError(f"family '{fam}' requires at least 2 usable walk-forward folds")

    return {fam: tuple(preds) for fam, preds in results.items()}


def _fit_single_family(
    family: str,
    train: tuple[_ExpSample, ...],
    contract: DevelopmentExperimentContract,
) -> tuple[Pipeline, Pipeline]:
    matrix = _to_matrix(train)
    returns = np.asarray([r.return_target_bp for r in train], dtype=float)
    downside = np.asarray([r.downside_target for r in train], dtype=int)
    prep = (("imputer", SimpleImputer(strategy="median", keep_empty_features=True)), ("scaler", StandardScaler()))

    params = contract.model_parameters.get(family, {})
    if family == "linear_logistic":
        alpha = float(params.get("ridge_alpha", 1.0))
        c_val = float(params.get("logistic_c", 1.0))
        ret_model = Pipeline((*prep, ("model", Ridge(alpha=alpha))))
        down_model = Pipeline((*prep, ("model", LogisticRegression(C=c_val, max_iter=500, random_state=contract.random_state))))
    elif family == "hist_gradient_boosting":
        max_iter = int(params.get("max_iter", 80))
        lr = float(params.get("learning_rate", 0.05))
        depth = int(params.get("max_depth", 3))
        min_samples = int(params.get("min_samples_leaf", 2))
        ret_model = Pipeline((*prep, ("model", HistGradientBoostingRegressor(max_iter=max_iter, learning_rate=lr, max_depth=depth, min_samples_leaf=min_samples, random_state=contract.random_state))))
        down_model = Pipeline((*prep, ("model", HistGradientBoostingClassifier(max_iter=max_iter, learning_rate=lr, max_depth=depth, min_samples_leaf=min_samples, random_state=contract.random_state))))
    else:
        raise ValueError(f"unsupported model family: {family}")

    return ret_model.fit(matrix, returns), down_model.fit(matrix, downside)


def _validate_model_parameters(
    params: dict[str, dict[str, int | float]], model_families: Sequence[str]
) -> None:
    """(Defect 4) 嚴格驗證模型的超參數結構、Allowed Keys 與數值範圍。"""
    if not isinstance(params, dict):
        raise TypeError("model_parameters must be a dict")

    allowed_keys_map = {
        "linear_logistic": {"ridge_alpha", "logistic_c"},
        "hist_gradient_boosting": {"max_iter", "learning_rate", "max_depth", "min_samples_leaf"},
    }

    for fam, fam_params in params.items():
        if fam not in model_families:
            raise ValueError(f"model_parameters specifies unknown family '{fam}'")
        if not isinstance(fam_params, dict):
            raise TypeError(f"parameters for '{fam}' must be a dict")
        allowed = allowed_keys_map[fam]
        for key, val in fam_params.items():
            if key not in allowed:
                raise ValueError(f"unknown parameter '{key}' for model family '{fam}'; allowed: {sorted(allowed)}")
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise TypeError(f"parameter '{key}' value must be numeric")

            # Bounded range checks
            if key == "ridge_alpha" and val <= 0:
                raise ValueError("ridge_alpha must be positive")
            elif key == "logistic_c" and val <= 0:
                raise ValueError("logistic_c must be positive")
            elif key == "max_iter" and not (5 <= val <= 500):
                raise ValueError("max_iter must be between 5 and 500")
            elif key == "learning_rate" and not (0.001 <= val <= 1.0):
                raise ValueError("learning_rate must be between 0.001 and 1.0")
            elif key == "max_depth" and not (1 <= val <= 10):
                raise ValueError("max_depth must be between 1 and 10")
            elif key == "min_samples_leaf" and not (1 <= val <= 100):
                raise ValueError("min_samples_leaf must be between 1 and 100")


def _calibrate_oof(
    family: str, preds: tuple[_ExpPrediction, ...]
) -> tuple[tuple[_ExpPrediction, ...], str]:
    from ml_module.probability_calibration import ShadowProbabilityCalibrator
    raw = np.asarray([p.downside_probability_bp / 10_000 for p in preds], dtype=float)
    targets = np.asarray([p.row.downside_target for p in preds], dtype=int)
    calibrator = ShadowProbabilityCalibrator(minimum_samples=20).fit(
        model_id=f"exp-{family}",
        raw_probabilities=raw,
        labels=targets,
        fold_ids=tuple(p.fold_id for p in preds),
    )
    calibrated = calibrator.predict(raw)
    return tuple(
        _ExpPrediction(p.row, p.fold_id, p.return_prediction_bp, int(np.rint(val * 10_000)))
        for p, val in zip(preds, calibrated)
    ), calibrator.calibration_id


def _calc_metrics(preds: tuple[_ExpPrediction, ...], top_k: int) -> dict[str, int]:
    from ml_module.historical_evaluation import evaluate_historical_predictions
    k = min(top_k, len(preds))
    return evaluate_historical_predictions(
        return_targets_bp=tuple(p.row.return_target_bp for p in preds),
        downside_targets=tuple(p.row.downside_target for p in preds),
        return_predictions_bp=tuple(p.return_prediction_bp for p in preds),
        ranking_scores=tuple(p.return_prediction_bp for p in preds),
        downside_probabilities_bp=tuple(p.downside_probability_bp for p in preds),
        top_k=k,
    )


def _mae_score(preds: tuple[_ExpPrediction, ...]) -> int:
    return sum(abs(p.row.return_target_bp - p.return_prediction_bp) for p in preds) // len(preds)


def _to_matrix(rows: tuple[_ExpSample, ...]) -> np.ndarray[Any, Any]:
    return np.asarray([[np.nan if val is None else val for val in r.feature_values] for r in rows], dtype=float)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON artifact must be an object")
    return data


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _exclusive_write_bytes(path: Path, data: bytes) -> None:
    """(Defect 6) Exclusive creation with fsync; errors if file already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY  # Windows compatibility
    try:
        fd = os.open(path, flags)
    except FileExistsError:
        raise ValueError(f"immutable report file already exists: {path}") from None
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """(Defect 6) Atomic write using temporary file and fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path_str = tempfile.mkstemp(dir=path.parent, prefix=f".tmp_{path.name}_")
    temp_path = Path(temp_path_str)
    try:
        os.write(temp_fd, data)
        os.fsync(temp_fd)
        os.close(temp_fd)
        os.replace(temp_path, path)
    except Exception:
        os.close(temp_fd) if 'temp_fd' in locals() else None
        if temp_path.exists():
            temp_path.unlink()
        raise


def _verify_no_symlink_escape(root: Path) -> None:
    resolved = root.resolve()
    for parent in (resolved, *resolved.parents):
        if parent.is_symlink():
            raise ValueError(f"symlink path detected: {parent}")
