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

P0_CANDIDATE_SOURCE_ALIGNMENT_VERSION = "p0-candidate-source-alignment.v1"
_P0_CANDIDATE_SOURCE_ALIGNMENTS = {
    # Phase 3C adapters use provider-facing identities.  Keep those names
    # explicit so a candidate observation can be traced to the canonical P0
    # governance contract without silently rewriting a decision.
    "twse_institutional": "institutional_flows",
    "twse_credit": "credit_transactions",
    "tdcc_shareholding": "tdcc_shareholding",
    "mops.statement.publication": "pit.quarterly_financials",
}

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
class CandidateSourceIdAlignment:
    """Identity-only candidate mapping; it cannot grant source acceptance."""

    candidate_source_id: str
    source_id: str | None
    mapping_version: str
    blockers: tuple[str, ...]
    numeric_source_id: str | None = None
    availability_source_id: str | None = None


@dataclass(frozen=True)
class MOPSNumericPITSourceIdentityMapping:
    """Formal fail-closed governance mapping contract for MOPS numeric PIT candidates.

    Preserves all four distinct identities:
    1. artifact_source_id (e.g. mops.statement.publication)
    2. numeric_source_id (e.g. mops.t163sb06.financial_ratio)
    3. availability_source_id (e.g. mops.document_listing.statement_publication)
    4. governance_source_id (e.g. pit.quarterly_financials)
    """

    artifact_source_id: str
    numeric_source_id: str
    availability_source_id: str
    governance_source_id: str | None
    mapping_version: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_source_id": self.artifact_source_id,
            "numeric_source_id": self.numeric_source_id,
            "availability_source_id": self.availability_source_id,
            "governance_source_id": self.governance_source_id,
            "mapping_version": self.mapping_version,
            "blockers": list(self.blockers),
        }


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


def map_candidate_source_id(candidate_source_id: str) -> CandidateSourceIdAlignment:
    """Map an explicitly governed candidate identity to one P0 contract."""
    source_id = _P0_CANDIDATE_SOURCE_ALIGNMENTS.get(candidate_source_id)
    if source_id is None:
        return CandidateSourceIdAlignment(
            candidate_source_id=candidate_source_id,
            source_id=None,
            mapping_version=P0_CANDIDATE_SOURCE_ALIGNMENT_VERSION,
            blockers=("unmapped_candidate_source_id",),
        )
    numeric_source_id = "mops.t163sb06.financial_ratio" if candidate_source_id == "mops.statement.publication" else None
    availability_source_id = "mops.document_listing.statement_publication" if candidate_source_id == "mops.statement.publication" else None
    return CandidateSourceIdAlignment(
        candidate_source_id=candidate_source_id,
        source_id=source_id,
        mapping_version=P0_CANDIDATE_SOURCE_ALIGNMENT_VERSION,
        blockers=(),
        numeric_source_id=numeric_source_id,
        availability_source_id=availability_source_id,
    )


def resolve_mops_numeric_pit_source_mapping(
    *,
    artifact_source_id: str,
    numeric_source_id: str,
    availability_source_id: str,
) -> MOPSNumericPITSourceIdentityMapping:
    """Validate and map candidate source identities to the governed P0 source contract.

    Fail-closed rules:
    - Blank, unknown, or mismatched source identities generate explicit blockers.
    - mops.ezsearch.statement_publication is an availability lane, NOT numeric source acceptance.
    """
    blockers: list[str] = []
    art_id = artifact_source_id.strip()
    num_id = numeric_source_id.strip()
    avail_id = availability_source_id.strip()

    if not art_id or not num_id or not avail_id:
        blockers.append("missing_source_identity")

    if art_id == "mops.ezsearch.statement_publication" or num_id == "mops.ezsearch.statement_publication":
        blockers.append("availability_lane_cannot_be_numeric_source")

    if art_id != "mops.statement.publication":
        blockers.append("unmapped_candidate_artifact_source_id")

    if num_id not in {"mops.t163sb06.financial_ratio", "mops.financial_statement.raw"}:
        blockers.append("unmapped_numeric_source_id")

    if avail_id not in {
        "mops.document_listing.statement_publication",
        "mops.t57sb01.statement_publication",
        "mops.ezsearch.statement_publication",
    }:
        blockers.append("unmapped_availability_source_id")

    governance_source_id = "pit.quarterly_financials" if not blockers else None

    return MOPSNumericPITSourceIdentityMapping(
        artifact_source_id=artifact_source_id,
        numeric_source_id=numeric_source_id,
        availability_source_id=availability_source_id,
        governance_source_id=governance_source_id,
        mapping_version=P0_CANDIDATE_SOURCE_ALIGNMENT_VERSION,
        blockers=tuple(sorted(set(blockers))),
    )



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
