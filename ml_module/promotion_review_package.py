"""Non-applying ML rollback and promotion-review package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MLPromotionReviewPackage:
    model_id: str
    dataset_id: str
    champion_model_id: str
    review_status: str
    blockers: tuple[str, ...]
    shadow_observed_days: int
    comparison_status: str
    drift_statuses: tuple[str, ...]
    calibration_status: str
    rollback_artifact: str
    verification_artifacts: tuple[str, ...]
    rollback_required: bool = True
    apply_promotion: bool = False
    auto_promotion_allowed: bool = False
    production_scheduler_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "dataset_id": self.dataset_id,
            "champion_model_id": self.champion_model_id,
            "review_status": self.review_status,
            "blockers": list(self.blockers),
            "shadow_observed_days": self.shadow_observed_days,
            "comparison_status": self.comparison_status,
            "drift_statuses": list(self.drift_statuses),
            "calibration_status": self.calibration_status,
            "rollback_artifact": self.rollback_artifact,
            "verification_artifacts": list(self.verification_artifacts),
            "rollback_required": self.rollback_required,
            "apply_promotion": self.apply_promotion,
            "auto_promotion_allowed": self.auto_promotion_allowed,
            "production_scheduler_allowed": self.production_scheduler_allowed,
        }


class MLPromotionReviewPackageService:
    def __init__(self, *, minimum_shadow_days: int = 20) -> None:
        if minimum_shadow_days <= 0:
            raise ValueError("minimum_shadow_days must be positive")
        self.minimum_shadow_days = minimum_shadow_days

    def build(
        self,
        *,
        model_id: str,
        dataset_id: str,
        champion_model_id: str,
        shadow_observed_days: int,
        comparison_status: str,
        drift_statuses: tuple[str, ...],
        calibration_status: str,
        rollback_artifact: str,
        verification_artifacts: tuple[str, ...],
    ) -> MLPromotionReviewPackage:
        blockers: list[str] = []
        if shadow_observed_days < self.minimum_shadow_days:
            blockers.append("insufficient_shadow_days")
        if "major_drift" in drift_statuses:
            blockers.append("major_feature_drift")
        if calibration_status != "passed":
            blockers.append("calibration_not_passed")
        if comparison_status not in {"challenger_directionally_better", "mixed_or_tied"}:
            blockers.append("challenger_comparison_not_reviewable")
        if not rollback_artifact.strip():
            blockers.append("missing_rollback_artifact")
        if not verification_artifacts:
            blockers.append("missing_verification_artifacts")
        unique = tuple(sorted(set(blockers)))
        return MLPromotionReviewPackage(
            model_id=model_id,
            dataset_id=dataset_id,
            champion_model_id=champion_model_id,
            review_status="defer" if unique else "eligible_for_human_review",
            blockers=unique,
            shadow_observed_days=shadow_observed_days,
            comparison_status=comparison_status,
            drift_statuses=drift_statuses,
            calibration_status=calibration_status,
            rollback_artifact=rollback_artifact,
            verification_artifacts=verification_artifacts,
        )
