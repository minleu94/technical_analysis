"""Versioned, fail-closed contracts for the Gate 3 P0 source set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


P0_SOURCE_IDS = (
    "corporate_action.ex_dividend_timeline",
    "corporate_action.reduction_split_par_value",
    "microstructure.suspended_halt_resume",
    "microstructure.disposition_stock",
    "microstructure.periodic_call_auction",
    "microstructure.full_delivery",
    "microstructure.limit_lock",
    "institutional_flows",
    "credit_transactions",
    "tdcc_shareholding",
    "twse.monthly_revenue_announcement",
    "tpex.monthly_revenue_announcement",
    "pit.quarterly_financials",
)

ACCESS_BOUNDARY = {
    "production_ingestion_allowed": False,
    "scoring_allowed": False,
    "advice_allowed": False,
    "portfolio_allowed": False,
    "scheduler_allowed": False,
}


@dataclass(frozen=True)
class LegacySourceIdAlignment:
    """Name-only alignment; it has no authority to rewrite historical decisions."""

    legacy_source_id: str
    source_id: str | None
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class P0SourceContract:
    source_id: str
    family: str
    contract_version: str
    available_date_policy: str
    missing_policy: str
    freshness_policy: str
    coverage_policy: str
    retry_policy: str
    license_status: str = "requires_review"
    human_decision: str = "requires_human_acceptance"
    downstream_eligibility: str = "none"
    available_date_required: bool = True
    production_ingestion_allowed: bool = False

    def __post_init__(self) -> None:
        if self.source_id not in P0_SOURCE_IDS:
            raise ValueError(f"unknown P0 source: {self.source_id}")
        if self.downstream_eligibility != "none":
            raise ValueError("unaccepted P0 contracts cannot have downstream eligibility")
        if self.production_ingestion_allowed:
            raise ValueError("P0 engineering contracts cannot enable production ingestion")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "family": self.family,
            "contract_version": self.contract_version,
            "available_date_policy": self.available_date_policy,
            "available_date_required": self.available_date_required,
            "missing_policy": self.missing_policy,
            "freshness_policy": self.freshness_policy,
            "coverage_policy": self.coverage_policy,
            "retry_policy": self.retry_policy,
            "license_status": self.license_status,
            "human_decision": self.human_decision,
            "downstream_eligibility": self.downstream_eligibility,
            "production_ingestion_allowed": self.production_ingestion_allowed,
        }


class P0SourceContractRegistry:
    def __init__(self, contracts: Iterable[P0SourceContract]) -> None:
        items = tuple(contracts)
        if len({item.source_id for item in items}) != len(items):
            raise ValueError("duplicate P0 source contract")
        self._contracts = {item.source_id: item for item in items}

    def get(self, source_id: str) -> P0SourceContract | None:
        return self._contracts.get(source_id)

    def require(self, source_id: str) -> P0SourceContract:
        contract = self.get(source_id)
        if contract is None:
            raise KeyError(source_id)
        return contract

    def list(self) -> tuple[P0SourceContract, ...]:
        return tuple(self._contracts[source_id] for source_id in P0_SOURCE_IDS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "p0-source-contract-registry.v1",
            "access_boundary": dict(ACCESS_BOUNDARY),
            "sources": [item.to_dict() for item in self.list()],
        }


def build_p0_source_contract_registry() -> P0SourceContractRegistry:
    return P0SourceContractRegistry(_contract(source_id) for source_id in P0_SOURCE_IDS)


def map_legacy_source_id(legacy_source_id: str) -> LegacySourceIdAlignment:
    """Return an explicit blocker whenever a legacy id lacks a one-to-one name match."""
    if legacy_source_id in P0_SOURCE_IDS:
        return LegacySourceIdAlignment(legacy_source_id, legacy_source_id, ())
    return LegacySourceIdAlignment(legacy_source_id, None, ("unmapped_legacy_id",))


def _contract(source_id: str) -> P0SourceContract:
    family = source_id.split(".", 1)[0]
    if source_id in {"institutional_flows", "credit_transactions", "tdcc_shareholding"}:
        family = source_id
    freshness = "daily publication window must be verified"
    if source_id == "tdcc_shareholding":
        freshness = "weekly publication available date must be preserved"
    if "monthly_revenue" in source_id:
        freshness = "monthly announcement publication date must be preserved"
    if source_id == "pit.quarterly_financials":
        freshness = "quarterly announcement and revision dates must be preserved"
    return P0SourceContract(
        source_id=source_id,
        family=family,
        contract_version="1.0.0",
        available_date_policy="available_date must be explicit and <= decision_date",
        missing_policy="fail_closed_and_emit_diagnostic",
        freshness_policy=freshness,
        coverage_policy="report observed date and symbol coverage; never infer completeness",
        retry_policy="quarantine malformed observations; bounded manual shadow retry only",
    )
