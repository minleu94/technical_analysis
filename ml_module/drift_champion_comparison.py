"""Feature drift and same-sample challenger/champion comparison."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
import math
from typing import Iterable

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class MLFeatureDriftResult:
    feature_id: str
    psi: float
    status: str
    baseline_count: int
    current_count: int
    retrain_automatically: bool = False
    auto_promotion_allowed: bool = False

    @property
    def psi_bp(self) -> int:
        return int(
            (Decimal(str(self.psi)) * Decimal("10000")).quantize(
                Decimal("1"), rounding=ROUND_HALF_EVEN
            )
        )

    @property
    def recommended_human_action(self) -> str:
        if self.status == "major_drift":
            return "disable_shadow_and_review"
        if self.status == "moderate_drift":
            return "review_shadow_monitoring"
        return "continue_shadow_monitoring"


class MLFeatureDriftService:
    def compare(
        self,
        feature_id: str,
        baseline: NDArray[np.float64],
        current: NDArray[np.float64],
    ) -> MLFeatureDriftResult:
        reference = np.asarray(baseline, dtype=float)
        observed = np.asarray(current, dtype=float)
        if len(reference) < 20 or len(observed) < 20:
            raise ValueError("drift comparison requires at least twenty observations per sample")
        if not np.isfinite(reference).all() or not np.isfinite(observed).all():
            raise ValueError("drift values must be finite")
        edges = np.unique(np.quantile(reference, np.linspace(0, 1, 11)))
        if len(edges) < 3:
            raise ValueError("baseline feature lacks distribution variance")
        edges[0] = -np.inf
        edges[-1] = np.inf
        base_counts, _ = np.histogram(reference, bins=edges)
        current_counts, _ = np.histogram(observed, bins=edges)
        epsilon = 1e-6
        base_share = np.maximum(base_counts / len(reference), epsilon)
        current_share = np.maximum(current_counts / len(observed), epsilon)
        psi = float(np.sum((current_share - base_share) * np.log(current_share / base_share)))
        status = "stable" if psi < 0.1 else "moderate_drift" if psi < 0.25 else "major_drift"
        return MLFeatureDriftResult(feature_id, psi, status, len(reference), len(observed))


@dataclass(frozen=True)
class ChampionComparisonRow:
    sample_id: str
    actual_return_bp: int
    actual_downside: int
    champion_score: float
    challenger_score: float
    challenger_return_prediction_bp: float
    challenger_downside_probability: float

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id is required")
        if self.actual_downside not in {0, 1}:
            raise ValueError("actual_downside must be binary")
        values = (
            self.champion_score,
            self.challenger_score,
            self.challenger_return_prediction_bp,
            self.challenger_downside_probability,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("comparison values must be finite")
        if not 0 <= self.challenger_downside_probability <= 1:
            raise ValueError("challenger_downside_probability must be within 0..1")


@dataclass(frozen=True)
class MLChampionComparisonResult:
    sample_count: int
    k: int
    champion_precision_at_k_bp: int
    challenger_precision_at_k_bp: int
    challenger_return_mae_bp: int
    challenger_downside_brier_bp: int
    review_status: str
    auto_promotion_allowed: bool = False


class MLChampionComparisonService:
    def compare(
        self, *, rows: Iterable[ChampionComparisonRow], k: int
    ) -> MLChampionComparisonResult:
        samples = tuple(rows)
        if len({row.sample_id for row in samples}) != len(samples):
            raise ValueError("sample_id values must be unique")
        if k <= 0 or k > len(samples):
            raise ValueError("k must be within sample count")
        champion_top = sorted(samples, key=lambda row: row.champion_score, reverse=True)[:k]
        challenger_top = sorted(samples, key=lambda row: row.challenger_score, reverse=True)[:k]
        champion_precision = sum(row.actual_return_bp > 0 for row in champion_top) * 10000 // k
        challenger_precision = sum(row.actual_return_bp > 0 for row in challenger_top) * 10000 // k
        mae = int(round(
            sum(abs(row.challenger_return_prediction_bp - row.actual_return_bp) for row in samples)
            / len(samples)
        ))
        brier = int(round(
            sum((row.challenger_downside_probability - row.actual_downside) ** 2 for row in samples)
            * 10000
            / len(samples)
        ))
        status = "challenger_directionally_better" if challenger_precision > champion_precision else (
            "champion_directionally_better" if challenger_precision < champion_precision else "mixed_or_tied"
        )
        return MLChampionComparisonResult(
            len(samples), k, champion_precision, challenger_precision, mae, brier, status
        )
