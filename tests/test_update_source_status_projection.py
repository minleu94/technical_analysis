from __future__ import annotations

from app_module.p0_source_control_center import P0SourceControlCenterService
from app_module.update_source_status_projection import (
    UPDATE_SOURCE_STATUS_PROJECTION_SCHEMA,
    compose_source_status_projection,
)
from data_module.p0_source_contract_registry import P0_SOURCE_IDS


def _evidence_audit() -> dict[str, object]:
    return {
        "schema_version": "p0-source-evidence-audit.v1",
        "safety_flags": {
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "production_allowed": False,
            "scheduler_allowed": False,
            "downstream_eligibility": "none",
            "human_decision": "requires_human_acceptance",
        },
        "machine_evidence_matrix": [
            {
                "source_id": source_id,
                "machine_status": "verified",
                "availability": "network_probed",
                "pit_status": "official_publication_timestamp_missing",
                "timestamp_kind": "first_observed_only",
                "probe_outcome": "observed",
                "schema_status": "matched",
                "raw_row_count": 4,
                "accepted_row_count": 3,
                "blocked_row_count": 1,
                "provider": "official",
                "acquisition_route_id": "route.primary",
                "fallback_used": source_id == P0_SOURCE_IDS[9],
                "fallback_from_acquisition_route_id": (
                    "route.legacy" if source_id == P0_SOURCE_IDS[9] else None
                ),
                "acquisition_routes": [
                    {"route_id": "route.legacy", "license_evidence_url": "https://license/legacy"},
                    {"route_id": "route.primary", "license_evidence_url": "https://license/primary"},
                ],
                "remaining_blocker": "legal_and_license_acceptance_required",
            }
            for source_id in P0_SOURCE_IDS
        ],
    }


def test_p0_evidence_route_and_coverage_survive_read_only_projection() -> None:
    center = P0SourceControlCenterService().build(candidate_audit=_evidence_audit())
    tdcc = center.rows[9]

    assert tdcc.acquisition_route_id == "route.primary"
    assert tdcc.acquisition_route_ids == ("route.legacy", "route.primary")
    assert tdcc.fallback_used is True
    assert tdcc.fallback_from_route_id == "route.legacy"
    assert tdcc.coverage_bp == 7500
    assert tdcc.pit_status == "official_publication_timestamp_missing"
    assert tdcc.timestamp_kind == "first_observed_only"
    assert tdcc.probe_outcome == "observed"
    assert tdcc.schema_status == "matched"
    assert tdcc.license_evidence_urls == ("https://license/legacy", "https://license/primary")


def test_update_projection_keeps_core_keys_and_fail_closed_boundary() -> None:
    center = P0SourceControlCenterService().build(candidate_audit=_evidence_audit())
    payload = compose_source_status_projection(
        {"daily_data": {"status": "current", "total_records": 10}},
        p0_control_center=center,
        p0_reference="audit.json",
    )

    assert payload["daily_data"]["status"] == "current"
    assert payload["p0_source_control"]["schema_version"] == UPDATE_SOURCE_STATUS_PROJECTION_SCHEMA
    assert payload["p0_source_control"]["status"] == "research_shadow"
    assert payload["p0_source_control"]["summary"]["observed_rows"] == 52
    assert payload["p0_source_control"]["summary"]["accepted_rows"] == 39
    assert payload["p0_source_control"]["boundary"]["writes_allowed"] is False
    assert payload["p0_source_control"]["boundary"]["downstream_eligibility"] == "none"
    assert payload["p0_source_control"]["rows"][9]["fallback_used"] is True


def test_update_projection_marks_artifact_read_error_without_fake_success() -> None:
    center = P0SourceControlCenterService().build()
    payload = compose_source_status_projection(
        {},
        p0_control_center=center,
        p0_load_error="artifact missing",
        p0_reference="missing.json",
    )

    p0 = payload["p0_source_control"]
    assert p0["status"] == "audit_unavailable"
    assert p0["load_error"] == "artifact missing"
    assert p0["boundary"]["formal_oos_allowed"] is False
    assert p0["boundary"]["production_ingestion_allowed"] is False
