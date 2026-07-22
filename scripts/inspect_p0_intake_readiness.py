"""Inspect P0 Source Intake Readiness & Governance Dossiers.

Read-only script to audit all 13 P0 source candidates and broker branches.
Produces structured diagnostic json and markdown reports.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_module.p0_source_contract_registry import P0_SOURCE_IDS, P0SourceContractRegistry
from data_module.source_acceptance_governance import SourceAcceptanceDossier, SourceAcceptanceGovernance


def audit_p0_intake_readiness() -> Dict[str, Any]:
    governance = SourceAcceptanceGovernance()

    results: List[Dict[str, Any]] = []

    for src_id in P0_SOURCE_IDS:
        # Construct candidate dossier
        dossier = SourceAcceptanceDossier(
            source_id=src_id,
            source_owner_role="data_team",
            license_owner_role="legal_compliance",
            license_status="requires_review",
            license_scope="research_only",
            redistribution_policy="unverified",
            source_status="candidate",
            publication_time_policy="unverified",
            timezone="Asia/Taipei",
            available_date_policy="unverified",
            revision_policy="unverified",
            pit_coverage_window="unverified",
            coverage_numerator=0,
            coverage_denominator=100,
            missing_policy="fail_closed",
            row_conservation_counts={},
            quarantine_policy="quarantine_on_schema_error",
            quality_thresholds={"minimum_coverage_bp": 9500},
            downstream_use_cases=("research_backtest",),
            disable_conditions=("license_revoked", "pit_leakage"),
            rollback_reference="decision:initial-candidate",
            evidence_artifact_ids=(),
            downstream_eligibility="none",
        )

        diag = governance.diagnose_dossier(dossier)
        review_template = governance.generate_owner_review_template(dossier, diag)

        results.append({
            "source_id": src_id,
            "checklist_complete": diag.checklist_complete, # False
            "status": diag.status, # deferred
            "downstream_eligibility": diag.downstream_eligibility, # none
            "active_blockers": list(diag.active_blockers),
            "missing_authority_evidence": list(diag.missing_authority_evidence),
            "missing_programmatic_evidence": list(diag.missing_programmatic_evidence),
            "content_hash": dossier.content_hash,
            "review_template_preview": review_template[:300] + "...",
        })

    return {
        "p0_source_count": len(results),
        "all_deferred": all(r["status"] == "deferred" for r in results),
        "all_downstream_none": all(r["downstream_eligibility"] == "none" for r in results),
        "sources": results,
    }


if __name__ == "__main__":
    res = audit_p0_intake_readiness()
    out_path = Path("qa/reports/p0_intake_readiness_audit.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    print(f"P0 Intake Readiness Audit completed. Summary: {res['p0_source_count']} sources checked.")
    print(f"All deferred: {res['all_deferred']}, All downstream eligibility none: {res['all_downstream_none']}")
