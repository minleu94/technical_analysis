"""Fail-closed materialization readiness gate for MOPS numeric PIT research artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any, Mapping

from data_module.mops_numeric_pit_aggregator import (
    DEFAULT_MINIMUM_COVERAGE_BP,
    validate_mops_numeric_pit_aggregate_payload,
)
from data_module.p0_source_contract_registry import resolve_mops_numeric_pit_source_mapping
from data_module.source_acceptance_decision_registry import SourceAcceptanceDecisionRevision
from data_module.source_acceptance_governance import SourceAcceptanceDossier


_SHA256_REF_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PERIOD_RE = re.compile(r"^\d{4}-Q[1-4]\Z")


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
    minimum_coverage_bp: int = DEFAULT_MINIMUM_COVERAGE_BP,
    decision_revision: SourceAcceptanceDecisionRevision | None = None,
) -> MaterializationPreflightResult:
    """Require a verified aggregate and an explicit applying registry revision.

    A readiness package or dossier is descriptive evidence only.  Materialization
    requires a separately supplied `accepted`/`limited` decision revision whose
    source, evidence, use case, timestamp, rollback and dossier identity agree.
    """
    blockers: list[str] = []
    aggregate_valid = True
    try:
        validate_mops_numeric_pit_aggregate_payload(aggregate_payload)
    except (TypeError, ValueError):
        aggregate_valid = False
        blockers.append("invalid_aggregate_contract")

    art_src = aggregate_payload.get("artifact_source_id")
    num_src = aggregate_payload.get("numeric_source_id")
    avail_src = aggregate_payload.get("availability_source_id")
    art_id = art_src if isinstance(art_src, str) else ""
    num_id = num_src if isinstance(num_src, str) else ""
    avail_id = avail_src if isinstance(avail_src, str) else ""
    mapping = resolve_mops_numeric_pit_source_mapping(
        artifact_source_id=art_id,
        numeric_source_id=num_id,
        availability_source_id=avail_id,
    )
    if mapping.blockers or mapping.governance_source_id != "pit.quarterly_financials":
        blockers.append("invalid_source_identity_mapping")

    cov_bp = _strict_int(aggregate_payload.get("cumulative_coverage_bp"), default=0)
    if minimum_coverage_bp != DEFAULT_MINIMUM_COVERAGE_BP:
        blockers.append("minimum_threshold_policy_violation")
    if cov_bp < minimum_coverage_bp:
        blockers.append("coverage_below_minimum")
    if not aggregate_valid:
        cov_bp = 0

    lic_present = False
    decision_present = False
    allowed_use_cases: tuple[str, ...] = ()
    if dossier is None:
        blockers.extend(("missing_license_evidence", "missing_owner_reviewer_decision", "unauthorized_use_case"))
    else:
        allowed_use_cases = tuple(dossier.downstream_use_cases)
        if dossier.source_id != mapping.governance_source_id:
            blockers.append("dossier_source_id_mismatch")
        if not dossier.source_owner_role.strip() or not dossier.reviewer_role.strip():
            blockers.append("missing_owner_reviewer_decision")
        if not dossier.decision_timestamp.strip():
            blockers.append("missing_decision_timestamp")
        if decision_revision is None:
            blockers.append("missing_registered_decision_revision")
        else:
            if decision_revision.source_id != mapping.governance_source_id:
                blockers.append("decision_source_id_mismatch")
            if decision_revision.status not in {"accepted", "limited"}:
                blockers.append("decision_not_applying")
            if decision_revision.blockers:
                blockers.append("decision_retains_blockers")
            if "development_feature_materialization" not in decision_revision.allowed_use_cases:
                blockers.append("unauthorized_use_case")
            if dossier.decision_revision_id != decision_revision.decision_revision_id:
                blockers.append("decision_revision_id_mismatch")
            if dossier.downstream_eligibility != decision_revision.status:
                blockers.append("downstream_eligibility_mismatch")
            if dossier.rollback_reference != decision_revision.rollback_reference:
                blockers.append("rollback_reference_mismatch")
            required_evidence = set(
                decision_revision.license_evidence_ids
                + decision_revision.quality_evidence_ids
                + decision_revision.pit_evidence_ids
            )
            if not required_evidence.issubset(set(dossier.evidence_artifact_ids)):
                blockers.append("decision_evidence_not_bound_to_dossier")
            try:
                decided_at = datetime.fromisoformat(decision_revision.decided_at.replace("Z", "+00:00"))
                dossier_at = datetime.fromisoformat(dossier.decision_timestamp.replace("Z", "+00:00"))
                if decided_at.tzinfo is None or dossier_at.tzinfo is None or decided_at != dossier_at:
                    blockers.append("decision_timestamp_mismatch")
            except ValueError:
                blockers.append("invalid_decision_timestamp")
            if not decision_revision.owner_role.strip() or not decision_revision.reviewer_role.strip():
                blockers.append("missing_owner_reviewer_decision")
            decision_present = not any(
                code in blockers
                for code in (
                    "decision_source_id_mismatch",
                    "dossier_source_id_mismatch",
                    "decision_not_applying",
                    "decision_retains_blockers",
                    "decision_revision_id_mismatch",
                    "downstream_eligibility_mismatch",
                    "rollback_reference_mismatch",
                    "decision_evidence_not_bound_to_dossier",
                    "decision_timestamp_mismatch",
                    "invalid_decision_timestamp",
                    "missing_owner_reviewer_decision",
                    "missing_decision_timestamp",
                )
            )
            lic_present = bool(
                decision_present
                and dossier.license_status == "approved"
                and decision_revision.license_evidence_ids
                and set(decision_revision.license_evidence_ids).issubset(
                    set(dossier.evidence_artifact_ids)
                )
            )

        if not lic_present:
            blockers.append("missing_license_evidence")
        if not decision_present:
            blockers.append("missing_owner_reviewer_decision")
        if "development_feature_materialization" not in allowed_use_cases:
            blockers.append("unauthorized_use_case")

    formal_oos_allowed = aggregate_payload.get("formal_oos_allowed")
    alpha_value = aggregate_payload.get("production_blend_alpha_bp")
    if not isinstance(formal_oos_allowed, bool) or not isinstance(alpha_value, int) or isinstance(alpha_value, bool):
        blockers.append("missing_safety_flags")
        formal_oos_allowed = False
        alpha_bp = 0
    else:
        alpha_bp = alpha_value
    if formal_oos_allowed:
        blockers.append("formal_oos_prohibited")
    if alpha_bp != 0:
        blockers.append("production_alpha_prohibited")

    unique_blockers = tuple(sorted(set(blockers)))
    return MaterializationPreflightResult(
        materialization_ready=not unique_blockers,
        governance_source_id=mapping.governance_source_id or "",
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
    minimum_coverage_bp: int = DEFAULT_MINIMUM_COVERAGE_BP,
    decision_revision: SourceAcceptanceDecisionRevision | None = None,
) -> dict[str, Any]:
    """Generate a lineage-bound TEMP-only overlay after the preflight gate."""
    preflight = check_mops_materialization_readiness(
        aggregate_payload,
        dossier=dossier,
        minimum_coverage_bp=minimum_coverage_bp,
        decision_revision=decision_revision,
    )
    if not preflight.materialization_ready:
        raise PermissionError(f"materialization preflight failed; blockers: {preflight.active_blockers}")

    aggregate_candidate_identities = {
        str(candidate["candidate_sha256"]): (
            str(candidate["stock_code"]).strip(),
            str(candidate["period"]).strip(),
        )
        for candidate in aggregate_payload["candidates"]
    }
    candidates_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_rows:
        candidate_hash = row.get("candidate_sha256")
        if not isinstance(candidate_hash, str) or _SHA256_REF_RE.fullmatch(candidate_hash) is None:
            raise ValueError("candidate row must carry a valid candidate_sha256")
        if candidate_hash not in aggregate_candidate_identities:
            raise ValueError("candidate row is not present in aggregate lineage")
        symbol = str(row.get("stock_code", "")).strip()
        period = str(row.get("period", "")).strip()
        if not symbol or _PERIOD_RE.fullmatch(period) is None:
            raise ValueError("candidate row stock_code/period identity is invalid")
        if aggregate_candidate_identities[candidate_hash] != (symbol, period):
            raise ValueError("candidate row identity does not match aggregate lineage")
        available_date_text = str(row.get("available_date", "")).strip()
        try:
            available_date = date.fromisoformat(available_date_text)
        except ValueError as exc:
            raise ValueError("candidate row available_date must be an ISO date") from exc
        revision = row.get("revision", 1)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("candidate row revision must be a positive integer")
        items = row.get("statement_items")
        if not isinstance(items, Mapping) or not items:
            raise ValueError("candidate row statement_items must be a non-empty object")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in items.values()):
            raise ValueError("candidate row statement_items must use integer units")
        normalized = dict(row)
        normalized["_available_date"] = available_date
        candidates_by_symbol.setdefault(symbol, []).append(normalized)
    for rows in candidates_by_symbol.values():
        rows.sort(
            key=lambda row: (row["_available_date"], str(row["period"]), int(row["revision"])),
            reverse=True,
        )

    canonical_rows: list[tuple[str, dict[str, Any]]] = []
    for split in ("fit_rows", "evaluation_rows"):
        rows = canonical_dataset_payload.get(split, [])
        if not isinstance(rows, list):
            raise ValueError(f"canonical dataset {split} must be a list")
        canonical_rows.extend((split, row) for row in rows if isinstance(row, dict))

    overlay_rows: list[dict[str, Any]] = []
    for split, canonical_row in canonical_rows:
        symbol = str(canonical_row.get("symbol", "")).strip()
        decision_date_text = str(canonical_row.get("decision_date", "")).strip()
        try:
            decision_date = date.fromisoformat(decision_date_text)
        except ValueError as exc:
            raise ValueError("canonical decision_date must be an ISO date") from exc
        matched = next(
            (
                candidate
                for candidate in candidates_by_symbol.get(symbol, [])
                if candidate["_available_date"] <= decision_date
            ),
            None,
        )
        if matched is None:
            overlay_rows.append({
                "symbol": symbol,
                "decision_date": decision_date_text,
                "dataset_split": split,
                "pit_available_date": None,
                "period": None,
                "revision": None,
                "candidate_sha256": None,
                "revenue_twd_cents": None,
                "gross_margin_bp": None,
                "operating_margin_bp": None,
                "pretax_margin_bp": None,
                "net_margin_bp": None,
                "provenance": "missing",
                "quality_tier": "unmatched_canonical_row",
            })
            continue
        items = matched["statement_items"]
        overlay_rows.append({
            "symbol": symbol,
            "decision_date": decision_date_text,
            "dataset_split": split,
            "pit_available_date": matched["available_date"],
            "period": matched["period"],
            "revision": matched["revision"],
            "candidate_sha256": matched["candidate_sha256"],
            "revenue_twd_cents": items.get("revenue_twd_cents"),
            "gross_margin_bp": items.get("gross_margin_bp"),
            "operating_margin_bp": items.get("operating_margin_bp"),
            "pretax_margin_bp": items.get("pretax_margin_bp"),
            "net_margin_bp": items.get("net_margin_bp"),
            "provenance": "mops.t163sb06.financial_ratio",
            "quality_tier": "development_research_overlay",
        })

    return {
        "schema_version": "mops-development-feature-overlay.v1",
        "research_only": True,
        "governance_source_id": "pit.quarterly_financials",
        "canonical_manifest_sha256": aggregate_payload["canonical_manifest_sha256"],
        "canonical_dataset_sha256": aggregate_payload["canonical_dataset_sha256"],
        "decision_revision_id": decision_revision.decision_revision_id if decision_revision else None,
        "canonical_row_count": len(canonical_rows),
        "overlay_row_count": len(overlay_rows),
        "matched_pit_row_count": sum(1 for row in overlay_rows if row["pit_available_date"] is not None),
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "overlay_rows": overlay_rows,
    }


def _strict_int(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value
