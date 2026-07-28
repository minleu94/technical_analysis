"""Development-only ML Experiment Contract and Runner.

本模組允許開發者建立並執行獨立、可重現的 ML 開發實驗（Feature Ablation, Model Family Comparison, Bounded Grid）。
所有運算純屬 Development Research；嚴禁 Formal OOS、Production Promotion、Production Blend 或寫入正式 DB。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_module.config import TWStockConfig
from decision_module.weight_contract import RecommendationWeightContract
from development_module.dataset_integrity import validate_persisted_dataset_v0
from development_module.output_guard import validate_development_output_root
from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.historical_evaluation import evaluate_historical_predictions
from ml_module.probability_calibration import ShadowProbabilityCalibrator
from ml_module.purged_walk_forward import MLTimeWindowRow, PurgedWalkForwardSplitter

EXPERIMENT_SCHEMA_VERSION = "terra-development-experiment.v1"

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
    hyperparameter_grid: dict[str, dict[str, Any]] = None  # type: ignore[assignment]
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
        if not self.feature_ids:
            raise ValueError("feature_ids must not be empty; automatic 'use everything' is forbidden")
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("feature_ids must be unique")
        if self.hyperparameter_grid is None:
            object.__setattr__(self, "hyperparameter_grid", {})
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
            "hyperparameter_grid": self.hyperparameter_grid,
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
        validate_persisted_dataset_v0(
            manifest_file=manifest_file,
            dataset_file=dataset_file,
            manifest=manifest,
            dataset=dataset,
        )

        if contract.parent_dataset_id != manifest.get("dataset_id"):
            raise ValueError("contract parent_dataset_id does not match manifest dataset_id")

        # Check candidate fields validation
        candidate_info: dict[str, Any] | None = None
        if candidate_artifact_path:
            cand_p = Path(candidate_artifact_path).resolve()
            if not cand_p.is_file():
                raise ValueError(f"candidate artifact not found: {cand_p}")
            cand_data = _load_json_object(cand_p)
            cand_hash = "sha256:" + hashlib.sha256(cand_p.read_bytes()).hexdigest()
            candidate_info = {"file_path": str(cand_p), "hash": cand_hash, "data": cand_data}
            if not contract.candidate_research_only:
                raise ValueError("contract candidate_research_only must be True when candidate artifact is provided")

        # Validate feature_ids against core registry and candidate features
        core_feature_ids = set(spec.feature_id for spec in CORE_LONG_HISTORY_FEATURE_REGISTRY.specs)
        for fid in contract.feature_ids:
            if fid not in core_feature_ids:
                if fid == "mops.ezsearch.statement_publication":
                    raise ValueError("MOPS statement_publication is an availability gate, NOT a numeric model feature")
                if candidate_info is None:
                    raise ValueError(f"unknown feature_id '{fid}' and no candidate artifact provided")

        samples, evaluation_count = _load_experiment_samples(dataset, contract)
        if len(samples) < 20:
            raise ValueError("experiment requires at least twenty eligible fit rows")

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

        lineage = {
            "experiment_id": contract.experiment_id,
            "contract_hash": contract.content_hash(),
            "dataset_id": manifest.get("dataset_id"),
            "generation_id": manifest.get("generation_id"),
            "manifest_file_sha256": _file_sha256(manifest_file),
            "dataset_file_sha256": _file_sha256(dataset_file),
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
            "lineage": lineage,
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
            "lineage": lineage,
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

        exp_dir = safe_root / "experiments"
        exp_dir.mkdir(parents=True, exist_ok=True)
        report_file = exp_dir / f"{contract.experiment_id}.json"
        report_bytes = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        report_sha256 = "sha256:" + hashlib.sha256(report_bytes).hexdigest()
        _safe_write_bytes(report_file, report_bytes)

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
    fit_rows = dataset.get("fit_rows", [])
    eval_rows = dataset.get("evaluation_rows", [])
    if not isinstance(fit_rows, list) or not isinstance(eval_rows, list):
        raise ValueError("fit_rows and evaluation_rows arrays are required")

    feature_id_indices: dict[str, int] = {}
    samples: list[_ExpSample] = []
    for idx, raw in enumerate(fit_rows):
        if not isinstance(raw, dict):
            continue
        decision_date = str(raw.get("decision_date", ""))
        if decision_date > contract.training_cutoff_date:
            continue
        features = raw.get("features", [])
        if not isinstance(features, list):
            continue
        feat_map = {item[0]: item[1] for item in features if isinstance(item, list) and len(item) == 2}
        values = tuple(feat_map.get(fid) for fid in contract.feature_ids)

        labels = raw.get("labels", [])
        if not isinstance(labels, list):
            continue
        labels_by_id = {lbl.get("label_id"): lbl for lbl in labels if isinstance(lbl, dict)}
        ret_lbl = labels_by_id.get(contract.return_label_id)
        down_lbl = labels_by_id.get(contract.downside_label_id)
        if not ret_lbl or not down_lbl:
            continue

        ret_val = ret_lbl.get("value")
        down_val = down_lbl.get("value")
        if not isinstance(ret_val, int) or not isinstance(down_val, int):
            continue

        samples.append(
            _ExpSample(
                row_id=f"{raw.get('symbol')}:{decision_date}:{idx}",
                decision_date=decision_date,
                label_end_date=str(ret_lbl.get("horizon_end_date")),
                label_available_date=str(ret_lbl.get("available_date")),
                feature_values=values,
                return_target_bp=ret_val,
                downside_target=down_val,
            )
        )

    return tuple(samples), len(eval_rows)


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

    grid = contract.hyperparameter_grid.get(family, {})
    if family == "linear_logistic":
        alpha = float(grid.get("ridge_alpha", 1.0))
        c_val = float(grid.get("logistic_c", 1.0))
        ret_model = Pipeline((*prep, ("model", Ridge(alpha=alpha))))
        down_model = Pipeline((*prep, ("model", LogisticRegression(C=c_val, max_iter=500, random_state=contract.random_state))))
    elif family == "hist_gradient_boosting":
        max_iter = int(grid.get("max_iter", 80))
        lr = float(grid.get("learning_rate", 0.05))
        ret_model = Pipeline((*prep, ("model", HistGradientBoostingRegressor(max_iter=max_iter, learning_rate=lr, max_depth=3, min_samples_leaf=2, random_state=contract.random_state))))
        down_model = Pipeline((*prep, ("model", HistGradientBoostingClassifier(max_iter=max_iter, learning_rate=lr, max_depth=3, min_samples_leaf=2, random_state=contract.random_state))))
    else:
        raise ValueError(f"unsupported model family: {family}")

    return ret_model.fit(matrix, returns), down_model.fit(matrix, downside)


def _calibrate_oof(
    family: str, preds: tuple[_ExpPrediction, ...]
) -> tuple[tuple[_ExpPrediction, ...], str]:
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


def _safe_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".tmp_{path.name}_{os.getpid()}"
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)


def _verify_no_symlink_escape(root: Path) -> None:
    resolved = root.resolve()
    for parent in (resolved, *resolved.parents):
        if parent.is_symlink():
            raise ValueError(f"symlink path detected: {parent}")
