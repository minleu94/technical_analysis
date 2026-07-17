from __future__ import annotations

from datetime import date

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from scripts.run_p0_candidate_audit import build_p0_candidate_audit


def test_audit_keeps_all_p0_sources_visible_and_does_not_enable_scheduler() -> None:
    payload = build_p0_candidate_audit(
        date(2026, 7, 16),
        probe_report={
            "sources": [
                {
                    "source_id": "twse_institutional",
                    "schema_status": "matched",
                    "timestamp_evidence": "first_observed_only",
                    "raw_row_count": 10,
                    "accepted_row_count": 10,
                    "payload_sha256": "a" * 64,
                },
                {
                    "source_id": "twse_credit",
                    "schema_status": "matched",
                    "timestamp_evidence": "official_publication_timestamp",
                    "raw_row_count": 8,
                    "accepted_row_count": 8,
                    "payload_sha256": "b" * 64,
                },
                {
                    "source_id": "tdcc_shareholding",
                    "schema_status": "matched",
                    "timestamp_evidence": "first_observed_only",
                    "raw_row_count": 6,
                    "accepted_row_count": 6,
                    "payload_sha256": "c" * 64,
                },
            ]
        },
    )

    assert tuple(item["source_id"] for item in payload["items"]) == P0_SOURCE_IDS
    assert payload["production_scheduler_allowed"] is False
    assert payload["downstream_eligibility"] == "none"
    assert payload["human_decision"] == "requires_human_acceptance"
    institutional = next(item for item in payload["items"] if item["source_id"] == "institutional_flows")
    assert institutional["audit_status"] == "observed_candidate"
    assert institutional["quality_status"] == "degraded"
    assert "official_publication_timestamp_missing" in institutional["blockers"]
    unimplemented = next(item for item in payload["items"] if item["source_id"] == "pit.quarterly_financials")
    assert unimplemented["audit_status"] == "not_started_no_candidate_adapter"
    assert unimplemented["blockers"] == ["candidate_adapter_not_implemented"]
