"""Fail-closed, non-applying ML promotion review contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ReviewStatus = Literal["defer", "eligible_for_human_review"]


@dataclass(frozen=True)
class MLPromotionReviewPackageV2:
    """Cites existing artifacts without applying an ML promotion."""

    experiment_id: str
    comparison_artifact_id: str
    formal_oos_decision_id: str
    forward_evidence_ids: tuple[str, ...]
    paper_evidence_ids: tuple[str, ...]
    source_decision_revision_ids: tuple[str, ...]
    shadow_observed_days: int
    shadow_pipeline_operational: bool
    drift_statuses: tuple[str, ...]
    calibration_status: str
    rollback_artifact_id: str
    blockers: tuple[str, ...]
    review_status: ReviewStatus
    formal_oos_allowed: Literal[False] = field(default=False, init=False)
    apply_promotion: Literal[False] = field(default=False, init=False)
    promotion_allowed: Literal[False] = field(default=False, init=False)
    auto_promotion_allowed: Literal[False] = field(default=False, init=False)
    retrain_allowed: Literal[False] = field(default=False, init=False)
    production_scheduler_allowed: Literal[False] = field(default=False, init=False)
    trading_allowed: Literal[False] = field(default=False, init=False)
    production_blend_alpha_bp: Literal[0] = field(default=0, init=False)

    @property
    def artifact_citations(self) -> tuple[str, ...]:
        """Return references only; this property never loads an artifact."""
        return (
            self.comparison_artifact_id,
            self.formal_oos_decision_id,
            *self.forward_evidence_ids,
            *self.paper_evidence_ids,
            *self.source_decision_revision_ids,
            self.rollback_artifact_id,
        )


class MLPromotionReviewPackageV2Service:
    """Projects supplied identities and statuses into a fail-closed review package."""

    def __init__(self, *, minimum_shadow_days: int = 20) -> None:
        if minimum_shadow_days <= 0:
            raise ValueError("minimum_shadow_days must be positive")
        self._minimum_shadow_days = minimum_shadow_days

    def build(
        self,
        *,
        experiment_id: str,
        comparison_artifact_id: str,
        comparison_review_status: str,
        formal_oos_decision_id: str,
        formal_oos_allowed: bool = False,
        forward_evidence_ids: tuple[str, ...],
        paper_evidence_ids: tuple[str, ...],
        source_decision_revision_ids: tuple[str, ...],
        shadow_observed_days: int,
        drift_statuses: tuple[str, ...],
        calibration_status: str,
        rollback_artifact_id: str,
    ) -> MLPromotionReviewPackageV2:
        """Build a review-only projection from previously computed artifacts."""
        if formal_oos_allowed is not False:
            raise ValueError("formal_oos_allowed must remain false")

        blockers = _blockers(
            experiment_id=experiment_id,
            comparison_artifact_id=comparison_artifact_id,
            comparison_review_status=comparison_review_status,
            formal_oos_decision_id=formal_oos_decision_id,
            forward_evidence_ids=forward_evidence_ids,
            paper_evidence_ids=paper_evidence_ids,
            source_decision_revision_ids=source_decision_revision_ids,
            shadow_observed_days=shadow_observed_days,
            drift_statuses=drift_statuses,
            calibration_status=calibration_status,
            rollback_artifact_id=rollback_artifact_id,
            minimum_shadow_days=self._minimum_shadow_days,
        )
        return MLPromotionReviewPackageV2(
            experiment_id=experiment_id,
            comparison_artifact_id=comparison_artifact_id,
            formal_oos_decision_id=formal_oos_decision_id,
            forward_evidence_ids=forward_evidence_ids,
            paper_evidence_ids=paper_evidence_ids,
            source_decision_revision_ids=source_decision_revision_ids,
            shadow_observed_days=shadow_observed_days,
            shadow_pipeline_operational=shadow_observed_days >= self._minimum_shadow_days,
            drift_statuses=drift_statuses,
            calibration_status=calibration_status,
            rollback_artifact_id=rollback_artifact_id,
            blockers=tuple(sorted(set(blockers))),
            review_status="defer",
        )


def _blockers(
    *,
    experiment_id: str,
    comparison_artifact_id: str,
    comparison_review_status: str,
    formal_oos_decision_id: str,
    forward_evidence_ids: tuple[str, ...],
    paper_evidence_ids: tuple[str, ...],
    source_decision_revision_ids: tuple[str, ...],
    shadow_observed_days: int,
    drift_statuses: tuple[str, ...],
    calibration_status: str,
    rollback_artifact_id: str,
    minimum_shadow_days: int,
) -> list[str]:
    blockers: list[str] = ["formal_oos_not_allowed"]
    if not experiment_id.strip():
        blockers.append("missing_experiment_id")
    if not comparison_artifact_id.strip():
        blockers.append("missing_comparison_artifact")
    if comparison_review_status != "eligible_for_promotion_review":
        blockers.append("comparison_not_eligible_for_review")
    if not formal_oos_decision_id.strip():
        blockers.append("missing_formal_oos_decision")
    if not forward_evidence_ids:
        blockers.append("missing_forward_evidence")
    if not paper_evidence_ids:
        blockers.append("missing_paper_evidence")
    if not source_decision_revision_ids:
        blockers.append("missing_source_decision_revisions")
    if shadow_observed_days < minimum_shadow_days:
        blockers.append("insufficient_shadow_days")
    if not drift_statuses:
        blockers.append("missing_drift_status")
    elif "major_drift" in drift_statuses:
        blockers.append("major_feature_drift")
    if calibration_status != "passed":
        blockers.append("calibration_not_passed")
    if not rollback_artifact_id.strip():
        blockers.append("missing_rollback_artifact")
    return blockers
