"""Neutral, read-only projection of external-evidence review artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping


@dataclass(frozen=True)
class ExternalEvidenceObservabilityDTO:
    """Status-only application DTO; it cannot apply or recompute a decision."""

    review_status: str
    blockers: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    degraded: bool
    artifact_citations: tuple[str, ...]
    model_id: str
    dataset_id: str
    prediction_ids: tuple[str, ...]
    frozen_domain_metrics: Mapping[str, int]
    apply_promotion: Literal[False] = field(default=False, init=False)
    promotion_allowed: Literal[False] = field(default=False, init=False)
    retrain_allowed: Literal[False] = field(default=False, init=False)
    scheduler_allowed: Literal[False] = field(default=False, init=False)
    trading_allowed: Literal[False] = field(default=False, init=False)
    formal_oos_allowed: Literal[False] = field(default=False, init=False)
    production_blend_alpha_bp: Literal[0] = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not self.review_status or not self.model_id or not self.dataset_id:
            raise ValueError("review status, model_id, and dataset_id are required")
        if not all(self.artifact_citations):
            raise ValueError("artifact citations must be non-empty")
        if not all(self.prediction_ids):
            raise ValueError("prediction identities must be non-empty")
        copied_metrics = dict(self.frozen_domain_metrics)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in copied_metrics.values()):
            raise TypeError("frozen_domain_metrics values must be integer basis points")
        object.__setattr__(self, "frozen_domain_metrics", MappingProxyType(copied_metrics))


class ExternalEvidenceObservabilityService:
    """Copies supplied identities, statuses, and frozen metrics into a DTO."""

    def project(
        self,
        *,
        review_status: str,
        blockers: tuple[str, ...],
        missing_requirements: tuple[str, ...],
        degraded: bool,
        artifact_citations: tuple[str, ...],
        model_id: str,
        dataset_id: str,
        prediction_ids: tuple[str, ...],
        frozen_domain_metrics: Mapping[str, int],
    ) -> ExternalEvidenceObservabilityDTO:
        return ExternalEvidenceObservabilityDTO(
            review_status=review_status,
            blockers=blockers,
            missing_requirements=missing_requirements,
            degraded=degraded,
            artifact_citations=artifact_citations,
            model_id=model_id,
            dataset_id=dataset_id,
            prediction_ids=prediction_ids,
            frozen_domain_metrics=frozen_domain_metrics,
        )
