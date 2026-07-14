"""Experiment V1 preregistration schema and fail-closed validation.

The contract records pre-unblind intent only.  It contains no training, outcome
reading, comparison, promotion, or production execution behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Literal


_SHA256_FIELDS = (
    "k_policy_hash",
    "cost_policy_hash",
    "sample_policy_hash",
    "bootstrap_policy_hash",
    "search_budget_hash",
    "multiple_testing_policy_hash",
    "failure_policy_hash",
    "point_in_time_universe_hash",
    "dataset_manifest_hash",
    "model_manifest_hash",
    "rule_champion_content_hash",
)


@dataclass(frozen=True)
class ExperimentPreregistration:
    """Immutable V1 payload; human-bound entries intentionally default to missing."""

    experiment_id: str
    generation_id: str
    created_at: str
    hypothesis: str
    champion_snapshot_family_id: str
    challenger_model_id: str
    k_policy_hash: str
    cost_policy_hash: str
    sample_policy_hash: str
    bootstrap_policy_hash: str
    search_budget_hash: str
    multiple_testing_policy_hash: str
    failure_policy_hash: str
    point_in_time_universe_id: str
    point_in_time_universe_hash: str
    dataset_manifest_hash: str
    model_manifest_hash: str
    rule_champion_content_hash: str
    oos_custody_report_id: str | None
    oos_custody_status: str | None
    minimum_material_effect_bp: int | None
    downside_noninferiority_margin_bp: int | None
    quant_validation_owner: str | None
    risk_owner: str | None
    independent_experiment_reviewer: str | None
    owner_decision_timestamp: str | None
    owner_signature_artifact_ids: tuple[str, ...]
    primary_label_id: Literal["relative_return_20d_bp"] = "relative_return_20d_bp"
    primary_horizon_trading_days: Literal[20] = 20
    downside_guardrail_id: Literal["downside_20d_flag"] = "downside_20d_flag"
    downside_threshold_bp: Literal[-500] = -500
    sensitivity_horizons_trading_days: tuple[Literal[5], Literal[10]] = (5, 10)
    diagnostic_horizons_trading_days: tuple[Literal[60]] = (60,)
    confidence_level_bp: Literal[9500] = 9500
    sample_unit: Literal["decision_date_symbol_paired"] = "decision_date_symbol_paired"
    decision_time_policy: Literal["decision_time_available_data_only"] = "decision_time_available_data_only"
    execution_semantics: Literal["same_point_in_time_top_k_after_cost"] = "same_point_in_time_top_k_after_cost"
    cost_basis: Literal["after_cost"] = "after_cost"
    bootstrap_unit: Literal["decision_date_block"] = "decision_date_block"
    metric_family: Literal["after_cost_paired_effect_and_downside_guardrail"] = "after_cost_paired_effect_and_downside_guardrail"
    multiple_testing_policy: Literal["predeclared_primary_guardrail_sensitivity_diagnostic"] = "predeclared_primary_guardrail_sensitivity_diagnostic"
    outcome_revision_policy: Literal["append_only_verified_current_projection"] = "append_only_verified_current_projection"
    unblinded_at_freeze: Literal[False] = False
    frozen: bool = False
    formal_oos_allowed: Literal[False] = False
    production_blend_alpha_bp: Literal[0] = 0
    schema_version: Literal["ExperimentPreregistration.v1"] = "ExperimentPreregistration.v1"
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "experiment_id", "generation_id", "created_at", "hypothesis",
            "champion_snapshot_family_id", "challenger_model_id", "point_in_time_universe_id",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} is required")
        for field_name in _SHA256_FIELDS:
            _require_sha256(getattr(self, field_name), field_name=field_name)
        for field_name in ("minimum_material_effect_bp", "downside_noninferiority_margin_bp"):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise TypeError(f"{field_name} must be an integer basis-point value or None")
        if self.primary_label_id != "relative_return_20d_bp":
            raise ValueError("primary_label_id is fixed for Experiment V1")
        if self.primary_horizon_trading_days != 20:
            raise ValueError("primary_horizon_trading_days is fixed for Experiment V1")
        if self.downside_guardrail_id != "downside_20d_flag" or self.downside_threshold_bp != -500:
            raise ValueError("downside guardrail is fixed for Experiment V1")
        if self.sensitivity_horizons_trading_days != (5, 10) or self.diagnostic_horizons_trading_days != (60,):
            raise ValueError("sensitivity and diagnostic horizons are fixed for Experiment V1")
        if self.confidence_level_bp != 9500:
            raise ValueError("confidence_level_bp is fixed for Experiment V1")
        if self.sample_unit != "decision_date_symbol_paired":
            raise ValueError("sample_unit is fixed for Experiment V1")
        if self.decision_time_policy != "decision_time_available_data_only":
            raise ValueError("decision_time_policy is fixed for Experiment V1")
        if self.execution_semantics != "same_point_in_time_top_k_after_cost":
            raise ValueError("execution_semantics is fixed for Experiment V1")
        if self.cost_basis != "after_cost" or self.bootstrap_unit != "decision_date_block":
            raise ValueError("cost and bootstrap semantics are fixed for Experiment V1")
        if self.metric_family != "after_cost_paired_effect_and_downside_guardrail":
            raise ValueError("metric_family is fixed for Experiment V1")
        if self.multiple_testing_policy != "predeclared_primary_guardrail_sensitivity_diagnostic":
            raise ValueError("multiple testing policy is fixed for Experiment V1")
        if self.outcome_revision_policy != "append_only_verified_current_projection":
            raise ValueError("outcome revision policy is fixed for Experiment V1")
        if self.unblinded_at_freeze is not False:
            raise ValueError("unblinded_at_freeze must remain false")
        if self.formal_oos_allowed is not False:
            raise ValueError("formal_oos_allowed must remain false")
        if self.production_blend_alpha_bp != 0:
            raise ValueError("production_blend_alpha_bp must remain zero")
        if any(not artifact_id.strip() for artifact_id in self.owner_signature_artifact_ids):
            raise ValueError("owner_signature_artifact_ids cannot contain empty values")
        object.__setattr__(self, "content_hash", _payload_hash(self._hash_payload()))

    def _hash_payload(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "content_hash"
        }

    def to_manifest(self) -> dict[str, Any]:
        payload = self._hash_payload()
        payload["owner_signature_artifact_ids"] = list(self.owner_signature_artifact_ids)
        payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class PreregistrationValidationDecision:
    status: Literal[
        "needs_human_decision",
        "preregistration_frozen_pending_external_gate",
        "preregistration_ready_pending_external_gate",
    ]
    blockers: tuple[str, ...]
    formal_oos_allowed: Literal[False] = False
    production_blend_alpha_bp: Literal[0] = 0
    unblind_allowed: Literal[False] = False


class ExperimentPreregistrationValidator:
    """Validate only the pre-unblind contract; external Gates stay closed."""

    def validate(self, preregistration: ExperimentPreregistration) -> PreregistrationValidationDecision:
        blockers: list[str] = []
        for field_name in ("minimum_material_effect_bp", "downside_noninferiority_margin_bp"):
            if getattr(preregistration, field_name) is None:
                blockers.append(field_name)
        for field_name in (
            "quant_validation_owner", "risk_owner", "independent_experiment_reviewer",
            "owner_decision_timestamp",
        ):
            value = getattr(preregistration, field_name)
            if value is None or not value.strip():
                blockers.append(field_name)
        if not preregistration.owner_signature_artifact_ids:
            blockers.append("owner_signature_artifact_ids")
        if (
            not preregistration.oos_custody_report_id
            or preregistration.oos_custody_status != "custody_verified_unopened"
        ):
            blockers.append("ev3_custody_result")
        if blockers:
            return PreregistrationValidationDecision(
                status="needs_human_decision",
                blockers=tuple(blockers),
            )
        return PreregistrationValidationDecision(
            status=(
                "preregistration_frozen_pending_external_gate"
                if preregistration.frozen
                else "preregistration_ready_pending_external_gate"
            ),
            blockers=("formal_oos_allowed=false", "production_blend_alpha_bp=0"),
        )


class ExperimentPreregistrationRegistry:
    """In-memory identity guard: changing content requires a new experiment ID."""

    def __init__(self) -> None:
        self._by_experiment_id: dict[str, ExperimentPreregistration] = {}

    def register(self, preregistration: ExperimentPreregistration) -> ExperimentPreregistration:
        existing = self._by_experiment_id.get(preregistration.experiment_id)
        if existing is None:
            self._by_experiment_id[preregistration.experiment_id] = preregistration
            return preregistration
        if existing.content_hash != preregistration.content_hash:
            raise ValueError("changed preregistration content requires a new experiment_id and new holdout")
        return existing


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
