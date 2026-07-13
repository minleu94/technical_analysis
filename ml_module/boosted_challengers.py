"""Structured gradient-boosted ranking/regression and downside challengers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor


@dataclass(frozen=True)
class BoostedShadowPrediction:
    return_prediction_bp: NDArray[np.float64]
    ranking_score: NDArray[np.float64]
    downside_probability: NDArray[np.float64]


@dataclass(frozen=True)
class BoostedShadowChallengerBundle:
    model_id: str
    dataset_id: str
    feature_names: tuple[str, ...]
    return_model: Any
    downside_model: Any
    model_family: str = "hist_gradient_boosting"
    shadow_only: bool = True
    production_eligible: bool = False

    def predict(self, x: NDArray[np.float64]) -> BoostedShadowPrediction:
        matrix = np.asarray(x, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.feature_names):
            raise ValueError("prediction feature shape mismatch")
        returns = np.asarray(self.return_model.predict(matrix), dtype=float)
        downside = np.asarray(self.downside_model.predict_proba(matrix)[:, 1], dtype=float)
        return BoostedShadowPrediction(returns, returns.copy(), downside)


class BoostedShadowChallengerTrainer:
    def __init__(self, *, random_state: int = 42, max_iter: int = 80) -> None:
        self.random_state = random_state
        self.max_iter = max_iter

    def fit(
        self,
        *,
        dataset_id: str,
        feature_names: tuple[str, ...],
        x: NDArray[np.float64],
        return_target_bp: NDArray[np.float64],
        downside_target: NDArray[np.int_],
    ) -> BoostedShadowChallengerBundle:
        matrix = np.asarray(x, dtype=float)
        returns = np.asarray(return_target_bp, dtype=float)
        downside = np.asarray(downside_target, dtype=int)
        if matrix.ndim != 2 or matrix.shape[1] != len(feature_names):
            raise ValueError("feature_names must match x columns")
        if len(matrix) != len(returns) or len(matrix) != len(downside):
            raise ValueError("training target length mismatch")
        if len(matrix) < 10:
            raise ValueError("at least ten training rows are required")
        if len(np.unique(downside)) != 2:
            raise ValueError("downside target requires two classes")
        if not np.isfinite(matrix).all() or not np.isfinite(returns).all():
            raise ValueError("training values must be finite")
        return_model = HistGradientBoostingRegressor(
            max_iter=self.max_iter,
            learning_rate=0.05,
            max_depth=3,
            random_state=self.random_state,
        ).fit(matrix, returns)
        downside_model = HistGradientBoostingClassifier(
            max_iter=self.max_iter,
            learning_rate=0.05,
            max_depth=3,
            random_state=self.random_state,
        ).fit(matrix, downside)
        identity = {
            "dataset_id": dataset_id,
            "feature_names": feature_names,
            "random_state": self.random_state,
            "max_iter": self.max_iter,
            "family": "hist_gradient_boosting",
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return BoostedShadowChallengerBundle(
            model_id=f"gate7-hgb-{digest}",
            dataset_id=dataset_id,
            feature_names=feature_names,
            return_model=return_model,
            downside_model=downside_model,
        )
