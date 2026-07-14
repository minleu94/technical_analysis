from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from data_module.fundamental_availability import (
    CoverageWindow,
    EligibilityResult,
    evaluate_label_window_eligibility,
)

CORPORATE_ACTION_LABEL_POLICY_VERSION = "corporate-action-label-policy.v1"


def evaluate_corporate_action_label_window(
    *,
    label_start: str,
    label_end: str,
    coverage_start: str | None,
    coverage_end: str | None,
    coverage_quality: str,
    mode: str,
) -> EligibilityResult:
    if mode not in {"strict", "research"}:
        raise ValueError("mode must be strict or research")
    return evaluate_label_window_eligibility(
        label_start=date.fromisoformat(label_start),
        label_end=date.fromisoformat(label_end),
        coverage=CoverageWindow(
            source_id="corporate_action",
            data_family="corporate_action",
            coverage_start=(date.fromisoformat(coverage_start) if coverage_start else None),
            coverage_end=(date.fromisoformat(coverage_end) if coverage_end else None),
            quality=coverage_quality,
        ),
        strict=mode == "strict",
    )


@dataclass(frozen=True)
class CorporateActionPricePolicy:
    policy_id: str
    label: str
    allowed_for_decision_features: bool
    allowed_for_research_presentation: bool
    requires_available_date: bool
    source_capability_id: str
    description: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "label": self.label,
            "allowed_for_decision_features": self.allowed_for_decision_features,
            "allowed_for_research_presentation": self.allowed_for_research_presentation,
            "requires_available_date": self.requires_available_date,
            "source_capability_id": self.source_capability_id,
            "description": self.description,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class CorporateActionTableCandidate:
    table_name: str
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...]
    unique_key: tuple[str, ...]
    migration_created: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "required_columns": list(self.required_columns),
            "optional_columns": list(self.optional_columns),
            "unique_key": list(self.unique_key),
            "migration_created": self.migration_created,
        }


@dataclass(frozen=True)
class CorporateActionPolicyInspection:
    policies: tuple[CorporateActionPricePolicy, ...]
    table_candidate: CorporateActionTableCandidate
    default_decision_price_policy: str = "raw_close_price"

    @property
    def policy_by_id(self) -> dict[str, CorporateActionPricePolicy]:
        return {policy.policy_id: policy for policy in self.policies}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "production_data_writes": False,
            "migration_created": self.table_candidate.migration_created,
            "default_decision_price_policy": self.default_decision_price_policy,
            "policies": [policy.to_dict() for policy in self.policies],
            "table_candidate": self.table_candidate.to_dict(),
            "boundary": (
                "raw close remains the default decision price; full hindsight adjusted prices "
                "must not be used for decision features"
            ),
        }

    def to_markdown(self) -> str:
        payload = self.to_dict()
        rows = [
            "| policy_id | decision_features | research_presentation | warnings |",
            "|---|---:|---:|---|",
        ]
        for policy in payload["policies"]:
            rows.append(
                "| `{policy_id}` | {decision} | {research} | {warnings} |".format(
                    policy_id=policy["policy_id"],
                    decision=str(policy["allowed_for_decision_features"]).lower(),
                    research=str(policy["allowed_for_research_presentation"]).lower(),
                    warnings=", ".join(policy["warnings"]) or "none",
                )
            )
        return "\n".join(
            [
                "# Corporate Action Price Policy",
                "",
                f"- schema_version: {payload['schema_version']}",
                f"- production_data_writes: {str(payload['production_data_writes']).lower()}",
                f"- default_decision_price_policy: {payload['default_decision_price_policy']}",
                "",
                *rows,
                "",
                "## Table Candidate",
                "",
                f"- table_name: {payload['table_candidate']['table_name']}",
                f"- required_columns: {', '.join(payload['table_candidate']['required_columns'])}",
                f"- migration_created: {str(payload['migration_created']).lower()}",
            ]
        )


def inspect_corporate_action_policy() -> CorporateActionPolicyInspection:
    return CorporateActionPolicyInspection(
        policies=(
            CorporateActionPricePolicy(
                policy_id="raw_close_price",
                label="Raw close price",
                allowed_for_decision_features=True,
                allowed_for_research_presentation=True,
                requires_available_date=False,
                source_capability_id="sqlite.daily_prices",
                description="目前決策與 replay 的預設價格政策，沿用本地 daily_prices / raw daily CSV。",
            ),
            CorporateActionPricePolicy(
                policy_id="decision_date_adjusted_candidate",
                label="Decision-date adjusted candidate",
                allowed_for_decision_features=False,
                allowed_for_research_presentation=True,
                requires_available_date=True,
                source_capability_id="corporate_action.ex_dividend_timeline",
                description=(
                    "後續若建立具 available_date 的除權息時間軸，可作為候選 adjusted series；"
                    "在 source 尚未 ingested 前不得進決策特徵。"
                ),
                warnings=("source_not_ingested", "candidate_only"),
            ),
            CorporateActionPricePolicy(
                policy_id="full_hindsight_adjusted_price",
                label="Full hindsight adjusted price",
                allowed_for_decision_features=False,
                allowed_for_research_presentation=False,
                requires_available_date=True,
                source_capability_id="corporate_action.ex_dividend_timeline",
                description=(
                    "事後完整還原價含未來 corporate action 知識，不得用於回測訊號、"
                    "推薦特徵、forward outcome 或 lifecycle gate。"
                ),
                warnings=("look_ahead_risk", "hindsight_adjustment_forbidden"),
            ),
        ),
        table_candidate=CorporateActionTableCandidate(
            table_name="corporate_action_events",
            required_columns=(
                "source_event_id",
                "stock_code",
                "event_type",
                "event_date",
                "announced_date",
                "available_date",
                "source",
                "source_version",
                "quality",
            ),
            optional_columns=(
                "cash_dividend",
                "stock_dividend",
                "reference_price",
                "adjustment_factor",
                "warnings_json",
                "metadata_json",
            ),
            unique_key=("source", "source_event_id"),
        ),
    )
