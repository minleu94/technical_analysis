"""Repeatable Gate 7 ML shadow revalidation runbook builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app_module.engineering_gate_registry import EngineeringGateItem


VALID_TRIGGERS = frozenset(
    {"new_matured_evidence", "source_or_schema_change", "major_drift", "scheduled_review"}
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
                "do not auto-retrain from production scheduler",
                "do not auto-promote challenger",
                "do not replace rule-generated signals",
                "do not emit trading advice",
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
                ("freeze_dataset", "build frozen dataset manifest", "dataset-manifest.json", "manifest hash and source versions recorded"),
                ("validate_available_dates", "pytest tests/test_ml_available_date_boundary.py", "available-date-report.json", "zero accepted future features or immature labels"),
                ("purged_walk_forward", "pytest tests/test_ml_purged_walk_forward.py", "walk-forward-folds.json", "all folds pass purge and embargo checks"),
                ("train_challengers", "run boosted shadow challenger training", "model-artifact.joblib", "artifact hash registered as shadow_candidate"),
                ("calibrate_oof", "run OOF isotonic calibration", "calibration.json", "at least two OOF folds and two label classes"),
                ("write_shadow_predictions", "append shadow prediction registry", "shadow-predictions.json", "all prediction available dates are causal"),
                ("measure_drift", "run frozen-bin PSI drift comparison", "drift-report.json", "all feature drift statuses recorded"),
                ("compare_champion", "run same-sample champion comparison", "champion-comparison.json", "same matured sample ids used"),
                ("build_review_package", "python scripts/build_ml_promotion_review.py ...", "promotion-review.json", "review package remains non-applying"),
                ("check_shadow_boundary", "python scripts/check_ml_shadow_boundary.py", "shadow-boundary.json", "zero dependency or true-flag violations"),
            )
        )
        return MLRevalidationRunbook(
            run_id, trigger, dataset_id, current_model_id, training_as_of, owner, steps
        )
