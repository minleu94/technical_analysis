"""Repeatable Gate 7 ML shadow revalidation runbook builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app_module.engineering_gate_registry import EngineeringGateItem


VALID_TRIGGERS = frozenset(
    {
        "new_matured_evidence",
        "source_or_schema_change",
        "major_drift",
        "scheduled_review",
        "production_promotion",
    }
)


@dataclass(frozen=True)
class MLRevalidationStep:
    step_id: str
    command: str
    expected_artifact: str
    completion_rule: str

    def to_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class MLRevalidationRunbook:
    run_id: str
    trigger: str
    dataset_id: str
    current_model_id: str
    training_as_of: str
    owner: str
    steps: tuple[MLRevalidationStep, ...]
    candidate_alpha_bp: tuple[int, ...] = (0, 2000, 3500, 5000)
    promotion_policy_id: str = "allocation-promotion-v4"
    auto_retrain_allowed: bool = False
    auto_promotion_allowed: bool = False
    production_scheduler_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trigger": self.trigger,
            "dataset_id": self.dataset_id,
            "current_model_id": self.current_model_id,
            "training_as_of": self.training_as_of,
            "owner": self.owner,
            "steps": [step.to_dict() for step in self.steps],
            "candidate_alpha_bp": list(self.candidate_alpha_bp),
            "promotion_policy_id": self.promotion_policy_id,
            "auto_retrain_allowed": self.auto_retrain_allowed,
            "auto_promotion_allowed": self.auto_promotion_allowed,
            "production_scheduler_allowed": self.production_scheduler_allowed,
        }

    def to_gate_item(
        self, *, revision: int, earliest_validation_date: str
    ) -> EngineeringGateItem:
        return EngineeringGateItem(
            item_id=f"ml-revalidation:{self.run_id}",
            revision=revision,
            category="ml_revalidation",
            title=f"Revalidate ML shadow challenger ({self.trigger})",
            status="open",
            owner=self.owner,
            earliest_validation_date=earliest_validation_date,
            progress_bp=0,
            required_artifacts=tuple(step.expected_artifact for step in self.steps),
            validation_commands=tuple(step.command for step in self.steps),
            completion_rules=tuple(step.completion_rule for step in self.steps),
            prohibited_actions=(
                "do not fabricate elapsed shadow days or historical OOS",
                "do not bypass the machine promotion artifact",
                "do not use features after decision_at",
                "do not connect to a broker or emit orders",
            ),
            notes=f"dataset={self.dataset_id}; current_model={self.current_model_id}; as_of={self.training_as_of}",
        )


class MLRevalidationRunbookService:
    def build(
        self,
        *,
        run_id: str,
        trigger: str,
        dataset_id: str,
        current_model_id: str,
        training_as_of: str,
        owner: str,
    ) -> MLRevalidationRunbook:
        if trigger not in VALID_TRIGGERS:
            raise ValueError("unsupported revalidation trigger")
        if not all((run_id, dataset_id, current_model_id, training_as_of, owner)):
            raise ValueError("runbook identity fields are required")
        steps = tuple(
            MLRevalidationStep(*row)
            for row in (
                (
                    "freeze_dataset",
                    "build core_long_history and all_field_enriched manifests",
                    "dataset-manifest.json",
                    "manifest hashes, schema, vintages and source versions recorded",
                ),
                (
                    "audit_feature_eligibility",
                    "scan every table.column into the fail-closed eligibility registry",
                    "feature-eligibility.json",
                    "100 percent of discovered columns have an explicit disposition",
                ),
                (
                    "validate_available_dates",
                    "pytest tests/test_ml_available_date_boundary.py",
                    "available-date-report.json",
                    "zero accepted future features, revisions or immature labels",
                ),
                (
                    "validate_causal_portfolio_state",
                    "replay the T-1 paper ledger and allocation teacher",
                    "causal-portfolio-state.json",
                    "no same-day Advice or oracle portfolio state is consumed",
                ),
                (
                    "purged_walk_forward",
                    "run at least four expanding outer folds with purge=60 and embargo=5",
                    "walk-forward-folds.json",
                    "all folds pass date, purge, embargo and OOF isolation checks",
                ),
                (
                    "train_feature_pack_experts",
                    "train Ridge/Logistic champions and HGB challengers by feature pack",
                    "model-artifacts.json",
                    "imputers, normalizers and calibrators are fit inside each train fold",
                ),
                (
                    "train_meta_allocator",
                    "train the integer-bp allocation meta model from OOF expert predictions",
                    "allocation-model.json",
                    "public outputs are bp/shares/minor-units and feature-family weights total 10000bp",
                ),
                (
                    "write_shadow_predictions",
                    "append causal allocation proposals and four alpha lane replays",
                    "allocation-shadow-replay.json",
                    "alpha lanes 0/2000/3500/5000 are deterministic and constraint-complete",
                ),
                (
                    "measure_calibration_drift",
                    "measure OOF ECE, Brier and frozen-bin PSI",
                    "calibration-drift.json",
                    "all metrics use frozen OOF or post-freeze evidence",
                ),
                (
                    "compare_portfolio_lanes",
                    "run same-sample costed Rule versus blended portfolio replay",
                    "portfolio-lane-comparison.json",
                    "same matured samples, costs, constraints and benchmark are used",
                ),
                (
                    "evaluate_promotion",
                    "evaluate the allocation-promotion-v4 machine policy",
                    "promotion-authorization.json",
                    "artifact authorizes the smallest passing alpha or atomically returns alpha=0",
                ),
                (
                    "check_boundaries",
                    "python scripts/check_ml_shadow_boundary.py",
                    "boundary-and-replay-hash.json",
                    "zero future-prefix or constraint violations and identical replay hashes",
                ),
            )
        )
        promotion_mode = trigger == "production_promotion"
        return MLRevalidationRunbook(
            run_id,
            trigger,
            dataset_id,
            current_model_id,
            training_as_of,
            owner,
            steps,
            auto_retrain_allowed=False,
            auto_promotion_allowed=promotion_mode,
            production_scheduler_allowed=promotion_mode,
        )
