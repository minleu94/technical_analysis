"""Frozen linear/HGB training with fold-only preprocessing and OOF blend selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from io import BytesIO
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml_module.probability_calibration import ShadowProbabilityCalibrator
from ml_module.purged_walk_forward import PurgedWalkForwardFold


@dataclass(frozen=True)
class HistoricalTrainingSample:
    row_id: str
    decision_date: str
    label_end_date: str
    label_available_date: str
    feature_values: tuple[int | None, ...]
    return_target_bp: int
    downside_target: int
    rule_score_bp: int


@dataclass(frozen=True)
class FoldTrainingAudit:
    fold_id: str
    model_family: str
    preprocessor_fit_row_ids: tuple[str, ...]
    test_row_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResearchBlendPolicy:
    research_alpha_bp: int
    production_alpha_bp: int
    selection_metric: str
    selection_label_cutoff: str
    max_selection_label_available_date: str


@dataclass(frozen=True)
class HistoricalTrainingResult:
    selected_model_family: str
    fold_audits: tuple[FoldTrainingAudit, ...]
    fold_ids: tuple[str, ...]
    research_blend_policy: ResearchBlendPolicy
    calibrator_id: str
    artifact_bytes: bytes
    artifact_hash: str
    training_row_count: int
    shadow_only: bool = True
    production_alpha_bp: int = 0
    production_action_allowed: bool = False


class HistoricalTrainingService:
    def __init__(self, *, random_state: int = 42, hgb_max_iter: int = 80) -> None:
        self.random_state = random_state
        self.hgb_max_iter = hgb_max_iter

    def fit(
        self,
        *,
        dataset_id: str,
        feature_names: tuple[str, ...],
        samples: tuple[HistoricalTrainingSample, ...],
        folds: tuple[PurgedWalkForwardFold, ...],
        training_as_of: str,
        blend_selection_label_cutoff: str,
    ) -> HistoricalTrainingResult:
        eligible = tuple(row for row in samples if (
            _date(row.decision_date) <= _date(training_as_of)
            and _date(row.label_available_date) <= _date(training_as_of)
        ))
        if len(eligible) < 20:
            raise ValueError("at least twenty cutoff-eligible training rows are required")
        by_id = {row.row_id: row for row in eligible}
        oof: dict[str, list[tuple[HistoricalTrainingSample, int, int]]] = {
            "linear": [], "hist_gradient_boosting": []
        }
        audits: list[FoldTrainingAudit] = []
        used_folds: list[str] = []
        probability_fold_ids: dict[str, list[str]] = {key: [] for key in oof}
        for fold in folds:
            train = tuple(by_id[row.row_id] for row in fold.train_rows if row.row_id in by_id)
            test = tuple(by_id[row.row_id] for row in fold.test_rows if row.row_id in by_id)
            if len(train) < 10 or not test or len({row.downside_target for row in train}) < 2:
                continue
            used_folds.append(fold.fold_id)
            for family in ("linear", "hist_gradient_boosting"):
                return_model, downside_model = self._fit_family(family, train)
                matrix = _matrix(test)
                predicted = return_model.predict(matrix)
                probabilities = downside_model.predict_proba(matrix)[:, 1]
                for row, prediction, probability in zip(test, predicted, probabilities):
                    oof[family].append((row, _round_float(prediction), _probability_bp(probability)))
                    probability_fold_ids[family].append(fold.fold_id)
                audits.append(FoldTrainingAudit(
                    fold.fold_id, family, tuple(row.row_id for row in train),
                    tuple(row.row_id for row in test),
                ))
        if len(set(used_folds)) < 2:
            raise ValueError("at least two usable OOF folds are required")
        mae = {
            family: _mean_absolute_error(values) for family, values in oof.items()
        }
        selected = min(mae, key=lambda family: (mae[family], family))
        selection_rows = tuple(
            item for item in oof[selected]
            if _date(item[0].decision_date) <= _date(blend_selection_label_cutoff)
            and _date(item[0].label_available_date) <= _date(blend_selection_label_cutoff)
        )
        if not selection_rows:
            raise ValueError("no OOF rows satisfy blend selection cutoff")
        alpha = _select_alpha(selection_rows)
        policy = ResearchBlendPolicy(
            research_alpha_bp=alpha,
            production_alpha_bp=0,
            selection_metric="return_mae_bp",
            selection_label_cutoff=blend_selection_label_cutoff,
            max_selection_label_available_date=max(row.label_available_date for row, _, _ in selection_rows),
        )
        probabilities = np.asarray([item[2] / 10_000 for item in oof[selected]], dtype=float)
        targets = np.asarray([item[0].downside_target for item in oof[selected]], dtype=int)
        calibrator = ShadowProbabilityCalibrator(minimum_samples=20).fit(
            model_id=f"{dataset_id}-{selected}", raw_probabilities=probabilities,
            labels=targets, fold_ids=probability_fold_ids[selected],
        )
        return_model, downside_model = self._fit_family(selected, eligible)
        payload: dict[str, Any] = {
            "dataset_id": dataset_id,
            "feature_names": feature_names,
            "selected_model_family": selected,
            "return_model": return_model,
            "downside_model": downside_model,
            "calibrator": calibrator,
            "research_blend_policy": policy,
            "production_alpha_bp": 0,
        }
        buffer = BytesIO()
        joblib.dump(payload, buffer, compress=0)
        artifact = buffer.getvalue()
        return HistoricalTrainingResult(
            selected_model_family=selected,
            fold_audits=tuple(audits),
            fold_ids=tuple(dict.fromkeys(used_folds)),
            research_blend_policy=policy,
            calibrator_id=calibrator.calibration_id,
            artifact_bytes=artifact,
            artifact_hash=f"sha256:{hashlib.sha256(artifact).hexdigest()}",
            training_row_count=len(eligible),
        )

    def _fit_family(
        self, family: str, rows: tuple[HistoricalTrainingSample, ...]
    ) -> tuple[Pipeline, Pipeline]:
        matrix = _matrix(rows)
        returns = np.asarray([row.return_target_bp for row in rows], dtype=float)
        downside = np.asarray([row.downside_target for row in rows], dtype=int)
        if family == "linear":
            return_model = Pipeline((
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scaler", StandardScaler()),
                ("model", Ridge(alpha=1.0)),
            ))
            downside_model = Pipeline((
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(C=1.0, max_iter=500, random_state=self.random_state)),
            ))
        else:
            return_model = Pipeline((
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("model", HistGradientBoostingRegressor(
                    max_iter=self.hgb_max_iter, learning_rate=0.05,
                    max_depth=3, random_state=self.random_state,
                )),
            ))
            downside_model = Pipeline((
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("model", HistGradientBoostingClassifier(
                    max_iter=self.hgb_max_iter, learning_rate=0.05,
                    max_depth=3, random_state=self.random_state,
                )),
            ))
        return return_model.fit(matrix, returns), downside_model.fit(matrix, downside)


def _matrix(rows: tuple[HistoricalTrainingSample, ...]) -> np.ndarray:
    return np.asarray([
        [np.nan if value is None else value for value in row.feature_values]
        for row in rows
    ], dtype=float)


def _mean_absolute_error(values: list[tuple[HistoricalTrainingSample, int, int]]) -> int:
    if not values:
        return 2**31 - 1
    return sum(abs(row.return_target_bp - prediction) for row, prediction, _ in values) // len(values)


def _select_alpha(values: tuple[tuple[HistoricalTrainingSample, int, int], ...]) -> int:
    candidates = (0, 2500, 5000, 7500, 10000)
    def error(alpha: int) -> tuple[int, int]:
        total = 0
        for row, prediction, _ in values:
            blended = (alpha * prediction + (10_000 - alpha) * row.rule_score_bp) // 10_000
            total += abs(row.return_target_bp - blended)
        return total, alpha
    return min(candidates, key=error)


def _round_float(value: float | np.floating[Any]) -> int:
    return int(round(float(value)))


def _probability_bp(value: float | np.floating[Any]) -> int:
    return int(round(float(value) * 10_000))


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])
