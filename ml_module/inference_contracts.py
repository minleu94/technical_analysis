"""Identity-only contracts for fail-closed ML shadow inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Mapping


@dataclass(frozen=True)
class ShadowInferenceRequest:
    model_id: str
    dataset_id: str
    decision_date: str
    feature_snapshot_hash: str
    feature_registry_hash: str
    source_versions: Mapping[str, str]
    feature_max_available_date: str

    def __post_init__(self) -> None:
        for field_name in (
            "model_id",
            "dataset_id",
            "decision_date",
            "feature_snapshot_hash",
            "feature_registry_hash",
            "feature_max_available_date",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        if not self.source_versions:
            raise ValueError("source_versions are required")
        if _date(self.feature_max_available_date) >= _date(self.decision_date):
            raise ValueError("feature snapshot must respect the T-1 cutoff")


@dataclass(frozen=True)
class ShadowPredictionIdentity:
    prediction_id: str
    symbol: str
    return_prediction_bp: int
    ranking_score_bp: int
    downside_probability_bp: int
    uncertainty_bp: int

    def __post_init__(self) -> None:
        if not self.prediction_id or not self.symbol:
            raise ValueError("prediction_id and symbol are required")
        for field_name in (
            "return_prediction_bp",
            "ranking_score_bp",
            "downside_probability_bp",
            "uncertainty_bp",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer basis points")
        if not 0 <= self.downside_probability_bp <= 10000:
            raise ValueError("downside_probability_bp must be within 0..10000")
        if self.uncertainty_bp < 0:
            raise ValueError("uncertainty_bp cannot be negative")


@dataclass(frozen=True)
class ShadowInferenceResult:
    request: ShadowInferenceRequest
    status: str
    predictions: tuple[ShadowPredictionIdentity, ...]
    excluded_symbols: tuple[str, ...]
    blockers: tuple[str, ...]
    drift_state: str
    model_status: str
    production_blend_alpha_bp: int = 0
    formal_rule_unchanged: bool = True
    production_action_allowed: bool = False

    def __post_init__(self) -> None:
        if self.production_blend_alpha_bp != 0:
            raise ValueError("production_blend_alpha_bp must remain zero")
        if not self.formal_rule_unchanged or self.production_action_allowed:
            raise ValueError("formal rule path must remain unchanged")

    @classmethod
    def available(
        cls,
        request: ShadowInferenceRequest,
        *,
        predictions: tuple[ShadowPredictionIdentity, ...],
    ) -> "ShadowInferenceResult":
        return cls(
            request=request,
            status="shadow_available",
            predictions=predictions,
            excluded_symbols=(),
            blockers=(),
            drift_state="not_evaluated",
            model_status="fixture_verified",
        )

    @classmethod
    def unavailable(cls, request: ShadowInferenceRequest, *, blocker: str) -> "ShadowInferenceResult":
        if not blocker:
            raise ValueError("blocker is required")
        return cls(
            request=request,
            status="shadow_unavailable",
            predictions=(),
            excluded_symbols=(),
            blockers=(blocker,),
            drift_state="not_evaluated",
            model_status="disabled_for_request",
        )


def prediction_id_for(request: ShadowInferenceRequest, symbol: str) -> str:
    if not symbol:
        raise ValueError("symbol is required")
    payload = {
        "model_id": request.model_id,
        "dataset_id": request.dataset_id,
        "decision_date": request.decision_date,
        "symbol": symbol,
        "feature_snapshot_hash": request.feature_snapshot_hash,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"prediction:{digest}"


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])
