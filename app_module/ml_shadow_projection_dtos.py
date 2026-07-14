"""Neutral application projection for ML shadow metadata.

The module intentionally depends on the standard library only.  Composition
from ML-domain results remains a scripts-layer responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MLShadowPredictionProjectionDTO:
    prediction_id: str
    symbol: str
    return_prediction_bp: int
    ranking_score_bp: int
    downside_probability_bp: int
    uncertainty_bp: int

    def __post_init__(self) -> None:
        if not self.prediction_id or not self.symbol:
            raise ValueError("prediction identity is required")
        for name in (
            "return_prediction_bp",
            "ranking_score_bp",
            "downside_probability_bp",
            "uncertainty_bp",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be integer basis points")
        if not 0 <= self.downside_probability_bp <= 10000:
            raise ValueError("downside_probability_bp must be within 0..10000")


@dataclass(frozen=True)
class MLShadowProjectionDTO:
    decision_date: str
    model_id: str
    dataset_id: str
    status: str
    predictions: tuple[MLShadowPredictionProjectionDTO, ...]
    blockers: tuple[str, ...]
    production_blend_alpha_bp: int = 0
    formal_rule_unchanged: bool = True
    production_action_allowed: bool = False

    def __post_init__(self) -> None:
        if not all((self.decision_date, self.model_id, self.dataset_id, self.status)):
            raise ValueError("projection identity and status are required")
        if self.production_blend_alpha_bp != 0:
            raise ValueError("production_blend_alpha_bp must remain zero")
        if not self.formal_rule_unchanged or self.production_action_allowed:
            raise ValueError("formal rule path must remain unchanged")
        if self.status == "shadow_available" and (not self.predictions or self.blockers):
            raise ValueError("available projection requires predictions without blockers")
        if self.status == "shadow_unavailable" and (self.predictions or not self.blockers):
            raise ValueError("unavailable projection requires blockers without predictions")
