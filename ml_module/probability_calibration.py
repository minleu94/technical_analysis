"""Out-of-fold isotonic calibration for shadow downside probabilities."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray
from sklearn.isotonic import IsotonicRegression


@dataclass(frozen=True)
class FittedShadowProbabilityCalibrator:
    calibration_id: str
    model_id: str
    estimator: Any
    sample_count: int
    fold_count: int
    method: str = "isotonic_oof"
    shadow_only: bool = True
    production_eligible: bool = False

    def predict(self, raw_probabilities: NDArray[np.float64]) -> NDArray[np.float64]:
        raw = np.asarray(raw_probabilities, dtype=float)
        if not np.isfinite(raw).all() or np.any((raw < 0) | (raw > 1)):
            raise ValueError("raw probabilities must be finite within 0..1")
        return np.asarray(self.estimator.predict(raw), dtype=float)


class ShadowProbabilityCalibrator:
    def __init__(self, *, minimum_samples: int = 20) -> None:
        if minimum_samples < 10:
            raise ValueError("minimum_samples must be at least 10")
        self.minimum_samples = minimum_samples

    def fit(
        self,
        *,
        model_id: str,
        raw_probabilities: NDArray[np.float64],
        labels: NDArray[np.int_],
        fold_ids: Sequence[str],
    ) -> FittedShadowProbabilityCalibrator:
        raw = np.asarray(raw_probabilities, dtype=float)
        target = np.asarray(labels, dtype=int)
        if len(raw) != len(target) or len(raw) != len(fold_ids):
            raise ValueError("calibration input lengths must match")
        if len(raw) < self.minimum_samples:
            raise ValueError("insufficient calibration samples")
        if len(set(fold_ids)) < 2:
            raise ValueError("calibration requires at least two out-of-fold blocks")
        if len(np.unique(target)) != 2:
            raise ValueError("calibration target requires two classes")
        if not np.isfinite(raw).all() or np.any((raw < 0) | (raw > 1)):
            raise ValueError("raw probabilities must be within 0..1")
        estimator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(
            raw, target
        )
        digest = hashlib.sha256(
            f"{model_id}|{len(raw)}|{'|'.join(sorted(set(fold_ids)))}".encode("utf-8")
        ).hexdigest()[:16]
        return FittedShadowProbabilityCalibrator(
            calibration_id=f"cal-{digest}",
            model_id=model_id,
            estimator=estimator,
            sample_count=len(raw),
            fold_count=len(set(fold_ids)),
        )
