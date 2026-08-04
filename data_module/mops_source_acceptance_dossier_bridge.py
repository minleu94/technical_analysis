"""P0 source acceptance readiness and dossier bridge for MOPS numeric PIT aggregate artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

from data_module.config import TWStockConfig
from data_module.mops_numeric_pit_aggregator import (
    DEFAULT_MINIMUM_COVERAGE_BP,
    validate_mops_numeric_pit_aggregate_payload,
)
from data_module.p0_source_contract_registry import resolve_mops_numeric_pit_source_mapping
from development_module.output_guard import resolve_development_output_dir
from data_module.source_acceptance_governance import (
    SourceAcceptanceDiagnosis,
    SourceAcceptanceDossier,
    SourceAcceptanceGovernance,
)


@dataclass(frozen=True)
class MOPSReadinessPackage:
    source_id: str
    governance_source_id: str
    artifact_source_id: str
    numeric_source_id: str
    availability_source_id: str
    status: str
    diagnostics: tuple[str, ...]
    programmatic_evidence: tuple[str, ...]
    authority_evidence: tuple[str, ...]
    formal_time_evidence: tuple[str, ...]
    dossier: SourceAcceptanceDossier
    diagnosis: SourceAcceptanceDiagnosis
    owner_review_template: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "mops-source-acceptance-readiness-package.v1",
            "source_id": self.source_id,
            "governance_source_id": self.governance_source_id,
            "artifact_source_id": self.artifact_source_id,
            "numeric_source_id": self.numeric_source_id,
            "availability_source_id": self.availability_source_id,
            "status": self.status,
            "diagnostics": list(self.diagnostics),
            "programmatic_evidence": list(self.programmatic_evidence),
            "authority_evidence": list(self.authority_evidence),
            "formal_time_evidence": list(self.formal_time_evidence),
            "dossier": self.dossier.to_dict(),
            "formal_acceptance_applied": False,
            "downstream_eligibility": "none",
        }


def build_mops_readiness_package(
    aggregate_payload: Mapping[str, Any],
    *,
    license_evidence_id: str = "",
    minimum_coverage_bp: int = DEFAULT_MINIMUM_COVERAGE_BP,
    owner_role: str = "data_engineering_lead",
    reviewer_role: str = "",
    decision_timestamp: str = "",
) -> MOPSReadinessPackage:
    """Build a non-applying P0 Source Acceptance readiness package from an aggregate artifact.

    Fail-closed governance:
    1. Derive P0 source_id = pit.quarterly_financials via mapping contract automatically.
    2. Missing license_evidence_id -> status = blocked, diagnostic = missing_license_evidence.
    3. Missing reviewer_role / decision_timestamp -> human_decision = requires_human_acceptance.
    4. Coverage < 8000 bp -> diagnostic = coverage_below_minimum.
    5. Even if programmatic evidence passes, max status is eligible_for_human_review (never auto-accepted).
    6. downstream_eligibility remains 'none'.
    """
    validate_mops_numeric_pit_aggregate_payload(aggregate_payload)
    if minimum_coverage_bp != DEFAULT_MINIMUM_COVERAGE_BP:
        raise ValueError("minimum_coverage_bp is a fixed policy threshold of 8000 bp")
    art_src = aggregate_payload.get("artifact_source_id")
    num_src = aggregate_payload.get("numeric_source_id")
    avail_src = aggregate_payload.get("availability_source_id")
    if not all(isinstance(value, str) and value.strip() for value in (art_src, num_src, avail_src)):
        raise ValueError("aggregate source identity fields are required")

    mapping = resolve_mops_numeric_pit_source_mapping(
        artifact_source_id=str(art_src),
        numeric_source_id=str(num_src),
        availability_source_id=str(avail_src),
    )
    if mapping.blockers or not mapping.governance_source_id:
        raise ValueError(f"aggregate artifact source identity mapping failed: {mapping.blockers}")

    p0_source_id = mapping.governance_source_id

    num_rows = aggregate_payload["pit_eligible_row_count"]
    den_rows = aggregate_payload["canonical_denominator"]
    cov_bp = aggregate_payload["cumulative_coverage_bp"]

    evidence_ids: list[str] = [
        f"pit:candidate_count:{aggregate_payload.get('candidate_count', 0)}",
        f"pit:eligible_rows:{num_rows}",
        f"pit:coverage_bp:{cov_bp}",
    ]
    if license_evidence_id.strip():
        evidence_ids.append(f"license:{license_evidence_id.strip()}")

    # A supplied identifier is only a review reference.  Approval can only come
    # from a separately validated applying decision revision.
    license_status = "requires_review"

    dossier = SourceAcceptanceDossier(
        source_id=p0_source_id,
        source_owner_role=owner_role,
        license_owner_role="legal_compliance_officer",
        license_status=license_status,
        license_scope="research_development_only",
        redistribution_policy="internal_research_only_no_redistribution",
        source_status="research_candidate",
        publication_time_policy="mops_official_announcement_timestamp_verified",
        timezone="Asia/Taipei",
        available_date_policy="conservative_next_day_available_date_policy",
        revision_policy="listing_reported_corrections_and_immutable_revisions",
        pit_coverage_window="2025_q1_bounded_research_candidates",
        coverage_numerator=num_rows,
        coverage_denominator=den_rows,
        missing_policy="fail_closed_missing_data_policy",
        row_conservation_counts={
            "canonical_rows": den_rows,
            "matching_rows": aggregate_payload["matching_decision_row_count"],
            "eligible_rows": num_rows,
        },
        quarantine_policy="quarantine_malformed_html_or_hash_mismatches",
        quality_thresholds={"minimum_coverage_bp": minimum_coverage_bp},
        downstream_use_cases=("development_feature_materialization",),
        downstream_eligibility="none",
        disable_conditions=("license_revoked", "hash_tampered", "future_data_detected"),
        rollback_reference="decision:pit.quarterly_financials:none",
        evidence_artifact_ids=tuple(evidence_ids),
        reviewer_role=reviewer_role,
        decision_timestamp=decision_timestamp,
    )

    gov = SourceAcceptanceGovernance()
    diagnosis = gov.diagnose_dossier(dossier)
    template = gov.generate_owner_review_template(dossier, diagnosis)

    prog_ev: list[str] = [
        f"candidate_count:{aggregate_payload.get('candidate_count', 0)}",
        f"canonical_denominator:{den_rows}",
        f"pit_eligible_rows:{num_rows}",
        f"coverage_bp:{cov_bp}",
        f"canonical_manifest_sha256:{aggregate_payload.get('canonical_manifest_sha256')}",
        f"canonical_dataset_sha256:{aggregate_payload.get('canonical_dataset_sha256')}",
    ]
    auth_ev: list[str] = []
    if license_evidence_id.strip():
        auth_ev.append(f"license_evidence:{license_evidence_id.strip()}")
    if owner_role.strip():
        auth_ev.append(f"owner_role:{owner_role.strip()}")
    if reviewer_role.strip():
        auth_ev.append(f"reviewer_role:{reviewer_role.strip()}")

    time_ev: list[str] = [
        "formal_snapshot_count:0",
        "formal_credit_authorized:false",
        "naturally_matured_outcomes:0",
    ]

    all_diagnostics: list[str] = list(diagnosis.active_blockers)
    if cov_bp < minimum_coverage_bp and "missing_coverage_bp" in all_diagnostics:
        all_diagnostics.remove("missing_coverage_bp")
        all_diagnostics.append("coverage_below_minimum")

    if not license_evidence_id.strip() and "missing_license_evidence" not in all_diagnostics:
        all_diagnostics.append("missing_license_evidence")

    if not reviewer_role.strip() or not decision_timestamp.strip():
        all_diagnostics.append("requires_human_acceptance")

    unique_diag = tuple(sorted(set(all_diagnostics)))
    pkg_status = "blocked" if {
        "missing_license_evidence",
        "license_not_accepted",
        "coverage_below_minimum",
    }.intersection(unique_diag) else (
        "eligible_for_human_review" if not unique_diag or unique_diag == ("requires_human_acceptance",) else "blocked"
    )

    return MOPSReadinessPackage(
        source_id=p0_source_id,
        governance_source_id=p0_source_id,
        artifact_source_id=str(art_src),
        numeric_source_id=str(num_src),
        availability_source_id=str(avail_src),
        status=pkg_status,
        diagnostics=unique_diag,
        programmatic_evidence=tuple(prog_ev),
        authority_evidence=tuple(auth_ev),
        formal_time_evidence=tuple(time_ev),
        dossier=dossier,
        diagnosis=diagnosis,
        owner_review_template=template,
    )


def export_mops_readiness_package(
    aggregate_json_path: Path,
    *,
    output_root: Path,
    run_id: str,
    license_evidence_id: str = "",
    minimum_coverage_bp: int = DEFAULT_MINIMUM_COVERAGE_BP,
    owner_role: str = "data_engineering_lead",
    reviewer_role: str = "",
    decision_timestamp: str = "",
) -> Path:
    aggregate_payload = json.loads(aggregate_json_path.read_text(encoding="utf-8"))
    pkg = build_mops_readiness_package(
        aggregate_payload,
        license_evidence_id=license_evidence_id,
        minimum_coverage_bp=minimum_coverage_bp,
        owner_role=owner_role,
        reviewer_role=reviewer_role,
        decision_timestamp=decision_timestamp,
    )
    config = TWStockConfig()
    target_dir = resolve_development_output_dir(
        output_root,
        run_id,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )
    if target_dir.exists():
        raise ValueError(f"output directory {target_dir} already exists")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=str(target_dir.parent)))
    try:
        out_json = staging_dir / "readiness-package.json"
        out_json.write_text(
            json.dumps(pkg.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        out_tmpl = staging_dir / "owner-review-template.md"
        out_tmpl.write_text(pkg.owner_review_template, encoding="utf-8")
        os.replace(staging_dir, target_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return target_dir / "readiness-package.json"
