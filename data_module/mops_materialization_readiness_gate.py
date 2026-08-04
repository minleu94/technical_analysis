"""Fail-closed materialization readiness gate and TEMP-only feature materializer for MOPS numeric PIT candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping

from data_module.p0_source_contract_registry import resolve_mops_numeric_pit_source_mapping
from data_module.source_acceptance_governance import SourceAcceptanceDossier


@dataclass(frozen=True)
class MaterializationPreflightResult:
    materialization_ready: bool
    governance_source_id: str
    active_blockers: tuple[str, ...]
    coverage_bp: int
    minimum_coverage_bp: int
    license_evidence_present: bool
    owner_reviewer_decision_present: bool
    allowed_use_cases: tuple[str, ...]
    formal_oos_allowed: bool
    production_blend_alpha_bp: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mops-materialization-preflight-result.v1",
            "materialization_ready": self.materialization_ready,
            "governance_source_id": self.governance_source_id,
            "active_blockers": list(self.active_blockers),
            "coverage_bp": self.coverage_bp,
            "minimum_coverage_bp": self.minimum_coverage_bp,
            "license_evidence_present": self.license_evidence_present,
            "owner_reviewer_decision_present": self.owner_reviewer_decision_present,
            "allowed_use_cases": list(self.allowed_use_cases),
            "formal_oos_allowed": self.formal_oos_allowed,
            "production_blend_alpha_bp": self.production_blend_alpha_bp,
        }


def check_mops_materialization_readiness(
    aggregate_payload: Mapping[str, Any],
    dossier: SourceAcceptanceDossier | None = None,
    *,
    minimum_coverage_bp: int = 8000,
) -> MaterializationPreflightResult:
    """Preflight gate for development feature materialization.

    Fail-closed requirements:
    1. Valid source identity mapping (governance_source_id == pit.quarterly_financials).
    2. Aggregate lineage valid.
    3. Coverage >= minimum_coverage_bp (default 8,000 bp).
    4. License evidence present.
    5. Named owner/reviewer decision present.
    6. Decision allowed use cases includes 'development_feature_materialization'.
    7. formal_oos_allowed == False.
    8. production_blend_alpha_bp == 0.
    """
    blockers: list[str] = []

    art_src = str(aggregate_payload.get("artifact_source_id") or "mops.statement.publication")
    num_src = str(aggregate_payload.get("numeric_source_id") or "mops.t163sb06.financial_ratio")
    avail_src = str(aggregate_payload.get("availability_source_id") or "mops.document_listing.statement_publication")

    mapping = resolve_mops_numeric_pit_source_mapping(
        artifact_source_id=art_src,
        numeric_source_id=num_src,
        availability_source_id=avail_src,
    )
    if mapping.blockers or mapping.governance_source_id != "pit.quarterly_financials":
        blockers.append("invalid_source_identity_mapping")

    cov_bp = int(aggregate_payload.get("cumulative_coverage_bp", 0))
    if cov_bp < minimum_coverage_bp:
        blockers.append("coverage_below_minimum")

    lic_present = False
    decision_present = False
    allowed_use_cases: tuple[str, ...] = ()

    if dossier is not None:
        lic_present = bool(dossier.license_status == "approved" and any(e.startswith("license:") for e in dossier.evidence_artifact_ids))
        decision_present = bool(dossier.reviewer_role.strip() and dossier.decision_timestamp.strip())
        allowed_use_cases = tuple(dossier.downstream_use_cases)
    else:
        # Check aggregate payload readiness diagnostics
        diags = aggregate_payload.get("source_acceptance_readiness_diagnostics", [])
        if "missing_license_evidence" in diags or "license_not_accepted" in diags:
            blockers.append("missing_license_evidence")
        if "requires_human_acceptance" in diags or "missing_source_owner" in diags:
            blockers.append("missing_owner_reviewer_decision")

    if not lic_present:
        blockers.append("missing_license_evidence")
    if not decision_present:
        blockers.append("missing_owner_reviewer_decision")
    if "development_feature_materialization" not in allowed_use_cases:
        blockers.append("unauthorized_use_case")

    formal_oos_allowed = bool(aggregate_payload.get("formal_oos_allowed", False))
    alpha_bp = int(aggregate_payload.get("production_blend_alpha_bp", 0))

    if formal_oos_allowed:
        blockers.append("formal_oos_prohibited")
    if alpha_bp != 0:
        blockers.append("production_alpha_prohibited")

    unique_blockers = tuple(sorted(set(blockers)))
    is_ready = len(unique_blockers) == 0

    return MaterializationPreflightResult(
        materialization_ready=is_ready,
        governance_source_id="pit.quarterly_financials",
        active_blockers=unique_blockers,
        coverage_bp=cov_bp,
        minimum_coverage_bp=minimum_coverage_bp,
        license_evidence_present=lic_present,
        owner_reviewer_decision_present=decision_present,
        allowed_use_cases=allowed_use_cases,
        formal_oos_allowed=formal_oos_allowed,
        production_blend_alpha_bp=alpha_bp,
    )


def materialize_development_feature_overlay(
    aggregate_payload: Mapping[str, Any],
    canonical_dataset_payload: Mapping[str, Any],
    candidate_rows: list[dict[str, Any]],
    dossier: SourceAcceptanceDossier | None = None,
    *,
    minimum_coverage_bp: int = 8000,
) -> dict[str, Any]:
    """Generate a 2025 development feature overlay ONLY if preflight gate passes.

    Fail-closed rules:
    - If preflight check fails, raises PermissionError / ValueError and emits diagnostics.
    - Preserves available_date: rows are eligible ONLY if decision_date >= available_date.
    - Revenue in integer cents, Margins in integer bp.
    - Does NOT write to DB, ScoringEngine, Recommendation, Portfolio, or ML training.
    """
    preflight = check_mops_materialization_readiness(
        aggregate_payload,
        dossier=dossier,
        minimum_coverage_bp=minimum_coverage_bp,
    )
    if not preflight.materialization_ready:
        raise PermissionError(f"materialization preflight failed; blockers: {preflight.active_blockers}")

    # Build lookup table for candidate rows by symbol & period
    candidates_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for r in candidate_rows:
        sym = str(r["stock_code"]).strip()
        candidates_by_symbol.setdefault(sym, []).append(r)

    overlay_rows: list[dict[str, Any]] = []
    canonical_rows = [
        row for key in ("fit_rows", "evaluation_rows")
        for row in canonical_dataset_payload.get(key, [])
        if isinstance(row, dict)
    ]

    for crow in canonical_rows:
        symbol = str(crow.get("symbol", "")).strip()
        decision_date_str = str(crow.get("decision_date", "")).strip()

        matched_cand = None
        if symbol in candidates_by_symbol:
            for cand in candidates_by_symbol[symbol]:
                avail_date = str(cand["available_date"])
                if decision_date_str >= avail_date:
                    matched_cand = cand
                    break

        if matched_cand is not None:
            items = matched_cand.get("statement_items", {})
            overlay_rows.append({
                "symbol": symbol,
                "decision_date": decision_date_str,
                "pit_available_date": matched_cand["available_date"],
                "period": matched_cand["period"],
                "revenue_twd_cents": items.get("revenue_twd_cents"),
                "gross_margin_bp": items.get("gross_margin_bp"),
                "operating_margin_bp": items.get("operating_margin_bp"),
                "pretax_margin_bp": items.get("pretax_margin_bp"),
                "net_margin_bp": items.get("net_margin_bp"),
                "provenance": "mops.t163sb06.financial_ratio",
                "quality_tier": "development_research_overlay",
            })
        else:
            overlay_rows.append({
                "symbol": symbol,
                "decision_date": decision_date_str,
                "pit_available_date": None,
                "period": None,
                "revenue_twd_cents": None,
                "gross_margin_bp": None,
                "operating_margin_bp": None,
                "pretax_margin_bp": None,
                "net_margin_bp": None,
                "provenance": "missing",
                "quality_tier": "unmatched_canonical_row",
            })

    return {
        "schema_version": "mops-development-feature-overlay.v1",
        "research_only": True,
        "governance_source_id": "pit.quarterly_financials",
        "canonical_row_count": len(canonical_rows),
        "overlay_row_count": len(overlay_rows),
        "matched_pit_row_count": sum(1 for r in overlay_rows if r["pit_available_date"] is not None),
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "overlay_rows": overlay_rows,
    }
