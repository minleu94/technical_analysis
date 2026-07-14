"""Development-only Dataset V0 → Rule replay → ML challenger orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from decision_module.weight_contract import RecommendationWeightContract
from ml_module.historical_evaluation import evaluate_historical_predictions
from ml_module.probability_calibration import ShadowProbabilityCalibrator
from ml_module.purged_walk_forward import MLTimeWindowRow, PurgedWalkForwardSplitter


_APPLY_FLAGS = (
    ("apply_to_scoring", False),
    ("apply_to_recommendation", False),
    ("apply_to_portfolio", False),
    ("apply_to_exit", False),
)
_RULE_REPLAY_CONFIG = {
    "weights": dict(RecommendationWeightContract.DEFAULT_WEIGHTS),
    "technical_features": ("rsi_normalized_bp", "adx_normalized_bp", "macd_normalized_bp"),
    "adapter_version": "dataset-v0-development-replay-v1",
}
_FROZEN_COST_POLICY_ID = "dataset_v0_pre_cost_labels_no_incremental_model_cost"
_FROZEN_COST_POLICY_HASH = "sha256:" + hashlib.sha256(
    _FROZEN_COST_POLICY_ID.encode("utf-8")
).hexdigest()


@dataclass(frozen=True)
class FrozenDevelopmentResearchPolicy:
    """Fixed first-pass research policy; no parameter search is supported."""

    training_as_of: str = "2025-12-31"
    return_label_id: str = "relative_return_20d_bp"
    downside_label_id: str = "downside_20d_flag"
    cost_policy_id: str = _FROZEN_COST_POLICY_ID
    cost_policy_hash: str = _FROZEN_COST_POLICY_HASH
    minimum_train_dates: int = 60
    test_date_count: int = 20
    purge_trading_days: int = 20
    embargo_trading_days: int = 5
    hgb_max_iter: int = 80
    random_state: int = 42
    top_k: int = 5
    production_apply_flags: tuple[tuple[str, bool], ...] = _APPLY_FLAGS

    def __post_init__(self) -> None:
        if self.production_apply_flags != _APPLY_FLAGS:
            raise ValueError("production_apply_flags must remain all false")
        if self.cost_policy_id != _FROZEN_COST_POLICY_ID:
            raise ValueError("cost_policy_id must remain the Dataset V0 frozen policy")
        if self.cost_policy_hash != _FROZEN_COST_POLICY_HASH:
            raise ValueError("cost_policy_hash must remain the Dataset V0 frozen policy")
        if min(self.minimum_train_dates, self.test_date_count, self.hgb_max_iter, self.top_k) <= 0:
            raise ValueError("fixed research policy counts must be positive")
        if min(self.purge_trading_days, self.embargo_trading_days) < 0:
            raise ValueError("purge and embargo must not be negative")

    @classmethod
    def bounded_for_test(
        cls, **overrides: object
    ) -> "FrozenDevelopmentResearchPolicy":
        values: dict[str, object] = {
            "minimum_train_dates": 12,
            "test_date_count": 6,
            "purge_trading_days": 1,
            "embargo_trading_days": 1,
            "hgb_max_iter": 20,
            "top_k": 3,
        }
        values.update(overrides)
        return cls(**values)  # type: ignore[arg-type]

    @property
    def content_hash(self) -> str:
        return _sha256({
            "training_as_of": self.training_as_of,
            "return_label_id": self.return_label_id,
            "downside_label_id": self.downside_label_id,
            "cost_policy_id": self.cost_policy_id,
            "cost_policy_hash": self.cost_policy_hash,
            "minimum_train_dates": self.minimum_train_dates,
            "test_date_count": self.test_date_count,
            "purge_trading_days": self.purge_trading_days,
            "embargo_trading_days": self.embargo_trading_days,
            "hgb_max_iter": self.hgb_max_iter,
            "random_state": self.random_state,
            "top_k": self.top_k,
            "production_apply_flags": list(self.production_apply_flags),
        })


@dataclass(frozen=True)
class ResearchRuleBaseline:
    baseline_kind: str
    rule_version: str
    frozen_configuration_hash: str
    formal_rule_champion: bool
    blockers: tuple[str, ...]
    metrics: dict[str, int]


@dataclass(frozen=True)
class MLDevelopmentChallenger:
    model_families: tuple[str, ...]
    selected_model_family: str
    training_row_count: int
    fold_ids: tuple[str, ...]
    max_selection_label_available_date: str
    calibration_method: str
    calibration_id: str
    metrics_by_family: dict[str, dict[str, int]]


@dataclass(frozen=True)
class DevelopmentComparison:
    data_scope: str
    formal_oos: bool
    sample_count: int
    coverage_bp: int
    rule_metrics: dict[str, int]
    challenger_metrics: dict[str, int]
    downside_diagnostics: dict[str, int]
    conclusion: str
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class DevelopmentResearchResult:
    rule_baseline: ResearchRuleBaseline
    ml_challenger: MLDevelopmentChallenger
    comparison: DevelopmentComparison
    projection: dict[str, object]
    report: dict[str, object]
    lineage: dict[str, object]


@dataclass(frozen=True)
class _Sample:
    row_id: str
    decision_date: str
    label_end_date: str
    label_available_date: str
    feature_values: tuple[int | None, ...]
    return_target_bp: int
    downside_target: int
    rule_score_bp: int


@dataclass(frozen=True)
class _OOFPrediction:
    row: _Sample
    fold_id: str
    return_prediction_bp: int
    downside_probability_bp: int


class TerraDevelopmentResearchOrchestrator:
    """Runs fixed, historical-research-only Rule and ML diagnostics on Dataset V0."""

    def run(
        self,
        *,
        manifest_path: str | Path,
        dataset_path: str | Path,
        policy: FrozenDevelopmentResearchPolicy | None = None,
    ) -> DevelopmentResearchResult:
        frozen_policy = policy or FrozenDevelopmentResearchPolicy()
        manifest_file = Path(manifest_path).resolve()
        dataset_file = Path(dataset_path).resolve()
        manifest = _load_json_object(manifest_file)
        dataset = _load_json_object(dataset_file)
        _validate_dataset_v0_manifest(manifest)
        samples, feature_names, evaluation_count = _load_fit_samples(dataset, frozen_policy)
        if len(samples) < 20:
            raise ValueError("Dataset V0 requires at least twenty eligible 2025 fit rows")
        folds = PurgedWalkForwardSplitter(
            minimum_train_dates=frozen_policy.minimum_train_dates,
            test_date_count=frozen_policy.test_date_count,
            purge_trading_days=frozen_policy.purge_trading_days,
            embargo_trading_days=frozen_policy.embargo_trading_days,
        ).split(tuple(MLTimeWindowRow(row.row_id, row.decision_date, row.label_end_date) for row in samples))
        oof = _fixed_oof_predictions(samples, folds, frozen_policy)
        selected = min(
            oof,
            key=lambda family: (_mae(oof[family]), family),
        )
        selected_rows = tuple(oof[selected])
        calibrated, calibration_id = _oof_calibrate(selected, selected_rows)
        ml_metrics = {
            family: _metrics(predictions, frozen_policy.top_k)
            for family, predictions in oof.items()
        }
        challenger_metrics = _metrics(calibrated, frozen_policy.top_k)
        rule_predictions = tuple(
            _OOFPrediction(
                row=item.row,
                fold_id=item.fold_id,
                return_prediction_bp=item.row.rule_score_bp - 5_000,
                downside_probability_bp=10_000 - item.row.rule_score_bp,
            )
            for item in selected_rows
        )
        rule_metrics = _metrics(rule_predictions, frozen_policy.top_k)
        rule_config_hash, rule_version = _rule_replay_identity()
        blockers = (
            "formal_attested_persisted_rule_snapshot_missing",
            "dataset_v0_corporate_action_coverage_research_only_degraded",
            "historical_research_seen_development_data",
            "formal_oos_false",
            "promotion_not_eligible",
        )
        rule_baseline = ResearchRuleBaseline(
            baseline_kind="historical_research_rule_replay",
            rule_version=rule_version,
            frozen_configuration_hash=rule_config_hash,
            formal_rule_champion=False,
            blockers=blockers[:1],
            metrics=rule_metrics,
        )
        max_available = max(row.row.label_available_date for row in selected_rows)
        challenger = MLDevelopmentChallenger(
            model_families=("linear_logistic", "hist_gradient_boosting"),
            selected_model_family=selected,
            training_row_count=len(samples),
            fold_ids=tuple(sorted({item.fold_id for item in selected_rows})),
            max_selection_label_available_date=max_available,
            calibration_method="isotonic_oof",
            calibration_id=calibration_id,
            metrics_by_family=ml_metrics,
        )
        downside = {
            "rule_downside_brier_bp": rule_metrics["brier_bp"],
            "challenger_downside_brier_bp": challenger_metrics["brier_bp"],
            "downside_positive_count": sum(item.row.downside_target for item in calibrated),
            "downside_sample_count": len(calibrated),
        }
        comparison = DevelopmentComparison(
            data_scope="historical_research_seen_development_data",
            formal_oos=False,
            sample_count=len(calibrated),
            coverage_bp=challenger_metrics["coverage_bp"],
            rule_metrics=rule_metrics,
            challenger_metrics=challenger_metrics,
            downside_diagnostics=downside,
            conclusion="historical_research_only_no_formal_rule_vs_ml_conclusion",
            blockers=blockers,
        )
        lineage: dict[str, object] = {
            "dataset_id": _required_string(manifest, "dataset_id"),
            "generation_id": _required_string(manifest, "generation_id"),
            "dataset_manifest_hash": manifest.get("manifest_hash", ""),
            "dataset_content_hash": manifest.get("content_hash", ""),
            "manifest_file_sha256": _file_sha256(manifest_file),
            "dataset_file_sha256": _file_sha256(dataset_file),
            "feature_registry_hash": _required_string(manifest, "feature_registry_hash"),
            "label_registry_hash": _required_string(manifest, "label_registry_hash"),
            "rule_configuration_hash": rule_config_hash,
            "frozen_policy_hash": frozen_policy.content_hash,
            "cost_policy_id": frozen_policy.cost_policy_id,
            "cost_policy_hash": frozen_policy.cost_policy_hash,
            "input_fit_row_count": len(samples),
            "input_evaluation_row_count": evaluation_count,
            "feature_names": list(feature_names),
            "max_label_available_date": max_available,
        }
        projection: dict[str, object] = {
            "identity": {
                "dataset_id": lineage["dataset_id"],
                "generation_id": lineage["generation_id"],
                "research_run_id": _sha256({"lineage": lineage, "policy": frozen_policy.content_hash}),
            },
            "status": {
                "scope": "historical_research_seen_development_data",
                "formal_oos": False,
                "alpha_bp": 0,
                "apply_flags": dict(_APPLY_FLAGS),
                "promotion_eligible": False,
            },
            "frozen_metrics": {
                "sample_count": comparison.sample_count,
                "coverage_bp": comparison.coverage_bp,
                "rule": rule_metrics,
                "ml": challenger_metrics,
                "downside": downside,
            },
            "blockers": list(blockers),
            "lineage": lineage,
        }
        report: dict[str, object] = {
            "report_kind": "terra_development_research_comparison.v1",
            "data_scope": comparison.data_scope,
            "research_rule_baseline": _dataclass_dict(rule_baseline),
            "ml_development_challenger": _dataclass_dict(challenger),
            "comparison": _dataclass_dict(comparison),
            "lineage": lineage,
            "projection_schema": "ResearchConsoleProjection.v1-frozen-development-only",
        }
        return DevelopmentResearchResult(rule_baseline, challenger, comparison, projection, report, lineage)


def _load_fit_samples(
    dataset: dict[str, object], policy: FrozenDevelopmentResearchPolicy
) -> tuple[tuple[_Sample, ...], tuple[str, ...], int]:
    fit_rows = dataset.get("fit_rows")
    evaluation_rows = dataset.get("evaluation_rows")
    if not isinstance(fit_rows, list) or not isinstance(evaluation_rows, list):
        raise ValueError("Dataset V0 requires fit_rows and evaluation_rows arrays")
    samples: list[_Sample] = []
    feature_names: tuple[str, ...] | None = None
    for index, raw in enumerate(fit_rows):
        if not isinstance(raw, dict):
            raise ValueError("fit row must be an object")
        decision_date = _required_string(raw, "decision_date")
        if decision_date > policy.training_as_of:
            raise ValueError("fit rows after training_as_of are forbidden")
        feature_as_of = _required_string(raw, "feature_as_of_date")
        available = _required_string(raw, "available_date")
        if feature_as_of >= decision_date or available > decision_date:
            raise ValueError("Dataset V0 feature timing violates T-1 availability")
        features = raw.get("features")
        if not isinstance(features, list) or not features:
            raise ValueError("fit row features are required")
        values: list[int | None] = []
        names: list[str] = []
        for item in features:
            if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
                raise ValueError("feature entries must be [name, integer-or-null]")
            if isinstance(item[1], bool) or not isinstance(item[1], (int, type(None))):
                raise ValueError("persisted features must be integer-or-null")
            names.append(item[0])
            values.append(item[1])
        names_tuple = tuple(names)
        if feature_names is None:
            feature_names = names_tuple
        elif feature_names != names_tuple:
            raise ValueError("Dataset V0 feature schema must remain frozen")
        labels = raw.get("labels")
        if not isinstance(labels, list):
            raise ValueError("fit row labels are required")
        labels_by_id = {item.get("label_id"): item for item in labels if isinstance(item, dict)}
        return_label = labels_by_id.get(policy.return_label_id)
        downside_label = labels_by_id.get(policy.downside_label_id)
        if not isinstance(return_label, dict) or not isinstance(downside_label, dict):
            raise ValueError("Dataset V0 primary return and downside labels are required")
        return_target = _ready_label_value(return_label, policy.training_as_of)
        downside_target = _ready_label_value(downside_label, policy.training_as_of)
        if downside_target not in (0, 1):
            raise ValueError("downside label must be a boolean integer")
        label_available = _required_string(return_label, "available_date")
        if label_available != _required_string(downside_label, "available_date"):
            raise ValueError("primary labels must share availability")
        samples.append(_Sample(
            row_id=f"{_required_string(raw, 'symbol')}:{decision_date}:{index}",
            decision_date=decision_date,
            label_end_date=_required_string(return_label, "horizon_end_date"),
            label_available_date=label_available,
            feature_values=tuple(values),
            return_target_bp=return_target,
            downside_target=downside_target,
            rule_score_bp=_rule_score_bp(dict(zip(names_tuple, values))),
        ))
    return tuple(samples), feature_names or (), len(evaluation_rows)


def _fixed_oof_predictions(
    samples: tuple[_Sample, ...], folds: tuple[Any, ...], policy: FrozenDevelopmentResearchPolicy
) -> dict[str, tuple[_OOFPrediction, ...]]:
    by_id = {row.row_id: row for row in samples}
    results: dict[str, list[_OOFPrediction]] = {"linear_logistic": [], "hist_gradient_boosting": []}
    for fold in folds:
        train = tuple(by_id[row.row_id] for row in fold.train_rows if row.row_id in by_id)
        test = tuple(by_id[row.row_id] for row in fold.test_rows if row.row_id in by_id)
        if len(train) < 10 or not test or len({row.downside_target for row in train}) != 2:
            continue
        for family in results:
            return_model, downside_model = _fit_models(family, train, policy)
            matrix = _matrix(test)
            for row, prediction, probability in zip(
                test, return_model.predict(matrix), downside_model.predict_proba(matrix)[:, 1]
            ):
                results[family].append(_OOFPrediction(
                    row=row,
                    fold_id=fold.fold_id,
                    return_prediction_bp=int(np.rint(prediction)),
                    downside_probability_bp=int(np.rint(probability * 10_000)),
                ))
    if any(len({item.fold_id for item in rows}) < 2 for rows in results.values()):
        raise ValueError("Dataset V0 needs at least two usable purged walk-forward folds")
    return {family: tuple(rows) for family, rows in results.items()}


def _fit_models(
    family: str, rows: tuple[_Sample, ...], policy: FrozenDevelopmentResearchPolicy
) -> tuple[Pipeline, Pipeline]:
    matrix = _matrix(rows)
    returns = np.asarray([row.return_target_bp for row in rows], dtype=float)
    downside = np.asarray([row.downside_target for row in rows], dtype=int)
    preprocessing = (("imputer", SimpleImputer(strategy="median", keep_empty_features=True)), ("scaler", StandardScaler()))
    if family == "linear_logistic":
        return_model = Pipeline((*preprocessing, ("model", Ridge(alpha=1.0))))
        downside_model = Pipeline((*preprocessing, ("model", LogisticRegression(C=1.0, max_iter=500, random_state=policy.random_state))))
    elif family == "hist_gradient_boosting":
        return_model = Pipeline((*preprocessing, ("model", HistGradientBoostingRegressor(max_iter=policy.hgb_max_iter, learning_rate=0.05, max_depth=3, min_samples_leaf=2, random_state=policy.random_state))))
        downside_model = Pipeline((*preprocessing, ("model", HistGradientBoostingClassifier(max_iter=policy.hgb_max_iter, learning_rate=0.05, max_depth=3, min_samples_leaf=2, random_state=policy.random_state))))
    else:
        raise ValueError("only frozen linear_logistic and hist_gradient_boosting families are allowed")
    return return_model.fit(matrix, returns), downside_model.fit(matrix, downside)


def _oof_calibrate(
    family: str, rows: tuple[_OOFPrediction, ...]
) -> tuple[tuple[_OOFPrediction, ...], str]:
    raw = np.asarray([row.downside_probability_bp / 10_000 for row in rows], dtype=float)
    target = np.asarray([row.row.downside_target for row in rows], dtype=int)
    calibrator = ShadowProbabilityCalibrator(minimum_samples=20).fit(
        model_id=f"development-{family}", raw_probabilities=raw, labels=target,
        fold_ids=tuple(row.fold_id for row in rows),
    )
    calibrated = calibrator.predict(raw)
    return tuple(
        _OOFPrediction(item.row, item.fold_id, item.return_prediction_bp, int(np.rint(value * 10_000)))
        for item, value in zip(rows, calibrated)
    ), calibrator.calibration_id


def _metrics(rows: tuple[_OOFPrediction, ...], top_k: int) -> dict[str, int]:
    k = min(top_k, len(rows))
    return evaluate_historical_predictions(
        return_targets_bp=tuple(row.row.return_target_bp for row in rows),
        downside_targets=tuple(row.row.downside_target for row in rows),
        return_predictions_bp=tuple(row.return_prediction_bp for row in rows),
        ranking_scores=tuple(row.return_prediction_bp for row in rows),
        downside_probabilities_bp=tuple(row.downside_probability_bp for row in rows),
        top_k=k,
    )


def _mae(rows: tuple[_OOFPrediction, ...]) -> int:
    return sum(abs(row.row.return_target_bp - row.return_prediction_bp) for row in rows) // len(rows)


def _matrix(rows: tuple[_Sample, ...]) -> np.ndarray[Any, Any]:
    return np.asarray([[np.nan if value is None else value for value in row.feature_values] for row in rows], dtype=float)


def _rule_score_bp(features: dict[str, int | None]) -> int:
    """Frozen Dataset-V0 adapter for the current Rule configuration, never a formal snapshot."""
    technical = Decimal(5_000)
    rsi = features.get("rsi_normalized_bp")
    adx = features.get("adx_normalized_bp")
    macd = features.get("macd_normalized_bp")
    if rsi is not None:
        technical += Decimal(rsi) / Decimal(2)
    if adx is not None:
        technical += (Decimal(adx) - Decimal(2_500)) / Decimal(4)
    if macd is not None:
        technical += Decimal(macd) / Decimal(2)
    technical = min(Decimal(10_000), max(Decimal(0), technical))
    weights = RecommendationWeightContract.DEFAULT_WEIGHTS
    score = (
        Decimal(weights["pattern"]) * Decimal(5_000)
        + Decimal(weights["technical"]) * technical
        + Decimal(weights["volume"]) * Decimal(5_000)
    ) / Decimal(10_000)
    return int(score.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _rule_replay_identity() -> tuple[str, str]:
    engine_path = Path(__file__).resolve().parents[1] / "decision_module" / "scoring_engine.py"
    source_hash = _file_sha256(engine_path)
    config_hash = _sha256({"config": _RULE_REPLAY_CONFIG, "scoring_engine_source_hash": source_hash})
    return config_hash, f"current-rule-replay:{source_hash[7:19]}"


def _ready_label_value(label: dict[str, object], training_as_of: str) -> int:
    if label.get("maturity_status") != "ready":
        raise ValueError("fit labels must be ready")
    available = _required_string(label, "available_date")
    if available > training_as_of:
        raise ValueError("labels after training_as_of are forbidden")
    value = label.get("value")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("ready labels must be integers")
    return value


def _validate_dataset_v0_manifest(manifest: dict[str, object]) -> None:
    if manifest.get("schema_version") != "terra-development-dataset.v0":
        raise ValueError("Terra Development Dataset V0 manifest is required")
    if manifest.get("dataset_status") != "research_only_degraded":
        raise ValueError("dataset must remain research_only_degraded")
    if manifest.get("formal_oos_allowed") is not False or manifest.get("production_blend_alpha_bp") != 0:
        raise ValueError("Dataset V0 formal_oos and production alpha safety flags are required")
    if manifest.get("formal_rule_only_path_unchanged") is not True or manifest.get("zero_formal_write") is not True:
        raise ValueError("Dataset V0 formal-path safeguards are required")


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON artifact: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("JSON artifact must be an object")
    return value


def _required_string(value: dict[str, object], name: str) -> str:
    field = value.get(name)
    if not isinstance(field, str) or not field.strip():
        raise ValueError(f"{name} is required")
    return field


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _dataclass_dict(value: object) -> dict[str, object]:
    return dict(value.__dict__)  # type: ignore[attr-defined]
