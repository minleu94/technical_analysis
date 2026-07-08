from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


ALLOWED_ML_ROLES = (
    "weight_learning",
    "probability_calibration",
    "meta_labeling",
    "ranking",
)

FORBIDDEN_ML_ACTIONS = (
    "production model training",
    "replacing rule-generated signals",
    "changing recommendation thresholds",
    "auto lifecycle action",
    "trading advice",
)

ML_ACCESS_BOUNDARY = {
    "production_model_training_allowed": False,
    "rule_signal_replacement_allowed": False,
    "recommendation_threshold_changes_allowed": False,
    "auto_lifecycle_action_allowed": False,
    "trading_advice_allowed": False,
    "production_scheduler_allowed": False,
}


@dataclass(frozen=True)
class MLReadinessContractReport:
    generated_at: str
    shadow_only: bool
    allowed_ml_roles: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    feature_policy: tuple[str, ...]
    label_policy: dict[str, Any]
    split_policy: dict[str, str]
    model_family_sequence: tuple[str, ...]
    required_preconditions: tuple[str, ...]
    access_boundary: dict[str, bool]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_ml_roles"] = list(self.allowed_ml_roles)
        payload["forbidden_actions"] = list(self.forbidden_actions)
        payload["feature_policy"] = list(self.feature_policy)
        payload["model_family_sequence"] = list(self.model_family_sequence)
        payload["required_preconditions"] = list(self.required_preconditions)
        payload["limitations"] = list(self.limitations)
        return payload


class MLReadinessContractService:
    """Static shadow-only ML readiness contract; no model training."""

    def build_report(self) -> MLReadinessContractReport:
        return MLReadinessContractReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            shadow_only=True,
            allowed_ml_roles=ALLOWED_ML_ROLES,
            forbidden_actions=FORBIDDEN_ML_ACTIONS,
            feature_policy=(
                "decision_time_features_only",
                "feature_available_date_lte_decision_date",
                "no_cross_sectional_normalization_after_decision_date",
                "record_feature_list_and_source_trace",
            ),
            label_policy={
                "horizon_maturity_required": True,
                "allowed_labels": [
                    "future_5d_return_gt_0",
                    "future_10d_return_gt_0",
                    "future_20d_return_gt_0",
                    "future_20d_return_beats_taiex",
                    "future_20d_same_day_universe_top_20pct",
                ],
            },
            split_policy={
                "policy_id": "walk_forward_expanding_t_minus_1",
                "description": "訓練與校準只能使用決策日前已成熟的 feature / label snapshot。",
            },
            model_family_sequence=(
                "logistic_regression_baseline",
                "random_forest_or_gradient_boosting_after_baseline",
                "xgboost_or_lightgbm_only_after_registry_and_dependency_review",
            ),
            required_preconditions=(
                "score_bucket_audit_reviewable",
                "threshold_robustness_matrix_reviewable",
                "component_ablation_readiness_reviewable",
            ),
            access_boundary=dict(ML_ACCESS_BOUNDARY),
            limitations=(
                "shadow_only=true；此 contract 不訓練 production model。",
                "ML 只能作為研究輔助，不取代 rule-generated signals，不改推薦 threshold。",
                "不得把機率輸出解讀為勝率保證、交易建議或 lifecycle 自動動作。",
            ),
        )
