from __future__ import annotations

from datetime import date

import pytest

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from scripts.run_p0_candidate_audit import build_p0_candidate_audit


def _probe_report() -> dict[str, object]:
    return {
        "probe_date": "2026-07-16",
        "probe_mode": "bounded_official_read_only",
        "license_accepted": False,
        "source_accepted": False,
        "downstream_eligibility": "none",
        "production_scheduler_allowed": False,
        "human_decision": "requires_human_acceptance",
        "sources": [
            {
                "source_id": "twse_institutional",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 10,
                "accepted_row_count": 10,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "a" * 64,
            },
            {
                "source_id": "twse_credit",
                "schema_status": "matched",
                "timestamp_evidence": "official_publication_timestamp",
                "raw_row_count": 8,
                "accepted_row_count": 8,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "b" * 64,
            },
            {
                "source_id": "tdcc_shareholding",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 6,
                "accepted_row_count": 6,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "c" * 64,
            },
            {
                "source_id": "twse_disposition",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 1,
                "accepted_row_count": 1,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "d" * 64,
            },
            {
                "source_id": "twse_periodic_call_auction",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 1,
                "accepted_row_count": 1,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "e" * 64,
            },
            {
                "source_id": "twse_ex_dividend",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 2,
                "accepted_row_count": 2,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "e" * 64,
            },
            {
                "source_id": "twse_reduction",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 1,
                "accepted_row_count": 1,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "f" * 64,
            },
        ],
    }


def test_audit_keeps_all_p0_sources_visible_and_does_not_enable_scheduler() -> None:
    payload = build_p0_candidate_audit(
        date(2026, 7, 16),
        probe_report=_probe_report(),
    )

    assert tuple(item["source_id"] for item in payload["items"]) == P0_SOURCE_IDS
    assert payload["production_scheduler_allowed"] is False
    assert payload["downstream_eligibility"] == "none"
    assert payload["human_decision"] == "requires_human_acceptance"
    assert payload["lineage"]["probe_date"] == "2026-07-16"
    assert payload["lineage"]["probe_mode"] == "bounded_official_read_only"
    assert payload["lineage"]["probe_report_sha256"].startswith("sha256:")
    institutional = next(item for item in payload["items"] if item["source_id"] == "institutional_flows")
    assert institutional["audit_status"] == "observed_candidate"
    assert institutional["quality_status"] == "degraded"
    assert "official_publication_timestamp_missing" in institutional["blockers"]
    disposition = next(item for item in payload["items"] if item["source_id"] == "microstructure.disposition_stock")
    assert disposition["audit_status"] == "observed_candidate"
    assert disposition["quality_status"] == "degraded"
    periodic = next(item for item in payload["items"] if item["source_id"] == "microstructure.periodic_call_auction")
    assert periodic["audit_status"] == "observed_candidate"
    assert periodic["quality_status"] == "degraded"
    ex_dividend = next(item for item in payload["items"] if item["source_id"] == "corporate_action.ex_dividend_timeline")
    reduction = next(item for item in payload["items"] if item["source_id"] == "corporate_action.reduction_split_par_value")
    assert ex_dividend["audit_status"] == "observed_candidate"
    assert reduction["audit_status"] == "observed_candidate"
    unimplemented = next(item for item in payload["items"] if item["source_id"] == "pit.quarterly_financials")
    assert unimplemented["audit_status"] == "candidate_artifact_not_supplied"
    assert unimplemented["blockers"] == ["mops_candidate_artifact_not_supplied"]


def test_probe_report_hash_is_stable_across_source_order() -> None:
    report = _probe_report()
    reversed_report = {**report, "sources": list(reversed(report["sources"]))}  # type: ignore[arg-type]

    first = build_p0_candidate_audit(date(2026, 7, 16), probe_report=report)
    second = build_p0_candidate_audit(date(2026, 7, 16), probe_report=reversed_report)

    assert first["lineage"]["probe_report_sha256"] == second["lineage"]["probe_report_sha256"]


def test_mops_quarterly_artifact_is_a_research_only_candidate() -> None:
    artifact = {
        "source_id": "mops.statement.publication", "source_version": "mops-v1", "captured_at": "2026-07-19T18:22:14-07:00",
        "research_only": True, "formal_oos_allowed": False, "production_scheduler_allowed": False, "downstream_eligibility": "none",
        "rows": [{"stock_code": "2330", "statement_type": "financial_report", "statement_scope": "consolidated", "period": "2026-Q1", "period_end": "2026-03-31", "announcement_date": "2026-05-15T14:43:02+08:00", "available_date": "2026-05-15T14:43:02+08:00", "revision": 1, "content_hash": "a" * 64, "correction_status": "none"}],
    }
    payload = build_p0_candidate_audit(date(2026, 7, 16), probe_report=_probe_report(), mops_quarterly_artifact=artifact)
    pit = next(item for item in payload["items"] if item["source_id"] == "pit.quarterly_financials")
    assert pit["audit_status"] == "observed_candidate"
    assert pit["timestamp_evidence"] == "official_document_upload_timestamp"
    assert pit["blockers"] == ["research_only_not_source_accepted"]


def test_fubon_projection_is_exposed_only_as_degraded_research_supplement() -> None:
    projection = {
        "schema_version": "fubon-p0-research-projection.v1",
        "source": "fubon.marketdata",
        "research_only": True,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "production_blend_alpha_bp": 0,
        "observations": [
            {
                "source_id": "microstructure.disposition_stock",
                "quality": "degraded",
                "availability_evidence_kind": "first_observed_only",
                "downstream_eligibility": "none",
                "production_scheduler_allowed": False,
            },
            {
                "source_id": "microstructure.limit_lock",
                "quality": "degraded",
                "availability_evidence_kind": "first_observed_only",
                "downstream_eligibility": "none",
                "production_scheduler_allowed": False,
            }
        ],
    }
    payload = build_p0_candidate_audit(
        date(2026, 7, 16), probe_report=_probe_report(), fubon_projection=projection
    )

    disposition = next(item for item in payload["items"] if item["source_id"] == "microstructure.disposition_stock")
    assert disposition["fubon_research_supplement"]["status"] == "observed_research_only"
    assert disposition["quality_status"] == "degraded"
    limit_lock = next(item for item in payload["items"] if item["source_id"] == "microstructure.limit_lock")
    assert limit_lock["audit_status"] == "observed_research_only"
    assert limit_lock["quality_status"] == "degraded"
    assert limit_lock["timestamp_evidence"] == "first_observed_only"
    assert limit_lock["fubon_research_supplement"]["row_count"] == 1
    assert payload["formal_oos_allowed"] is False


@pytest.mark.parametrize(
    ("key", "unsafe_value"),
    [
        ("probe_date", "2026-07-15"),
        ("probe_mode", "write_enabled"),
        ("license_accepted", True),
        ("source_accepted", True),
        ("downstream_eligibility", "formal"),
        ("production_scheduler_allowed", True),
        ("human_decision", "accepted"),
    ],
)
def test_probe_report_boundary_mismatch_fails_closed(key: str, unsafe_value: object) -> None:
    report = _probe_report()
    report[key] = unsafe_value

    with pytest.raises(ValueError, match=key):
        build_p0_candidate_audit(date(2026, 7, 16), probe_report=report)


def test_duplicate_probe_source_id_fails_closed() -> None:
    report = _probe_report()
    sources = report["sources"]
    sources.append(dict(sources[0]))  # type: ignore[union-attr, index]

    with pytest.raises(ValueError, match="duplicate probe source_id"):
        build_p0_candidate_audit(date(2026, 7, 16), probe_report=report)


def test_unknown_probe_source_id_fails_closed() -> None:
    report = _probe_report()
    report["sources"].append({"source_id": "unknown"})  # type: ignore[union-attr]

    with pytest.raises(ValueError, match="unknown probe source_id"):
        build_p0_candidate_audit(date(2026, 7, 16), probe_report=report)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("raw_row_count", True, "raw_row_count"),
        ("accepted_row_count", -1, "accepted_row_count"),
        ("accepted_row_count", 9, "row conservation"),
        ("payload_sha256", "not-a-digest", "payload_sha256"),
    ],
)
def test_matched_probe_count_and_hash_boundaries_fail_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    report = _probe_report()
    report["sources"][0][field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        build_p0_candidate_audit(date(2026, 7, 16), probe_report=report)


def test_audit_p0_13_sources_have_candidate_adapters_and_owner_questions() -> None:
    report = _probe_report()
    # Add probes for all remaining mapped sources
    all_mapped_probes = [
        "twse_institutional", "twse_credit", "tdcc_shareholding",
        "twse_disposition", "twse_periodic_call_auction", "twse_ex_dividend",
            "twse_reduction", "twse_full_delivery", "twse_halt_resume",
            "twse_monthly_revenue", "tpex_monthly_revenue", "twse_limit_lock"
    ]
    report["sources"] = [
        {
            "source_id": pid,
            "schema_status": "matched",
            "timestamp_evidence": "official_publication_timestamp",
            "raw_row_count": 5,
            "accepted_row_count": 5,
            "duplicate_row_count": 0,
            "quarantine_row_count": 0,
            "blocked_row_count": 0,
            "payload_sha256": "f" * 64,
        }
        for pid in all_mapped_probes
    ]

    payload = build_p0_candidate_audit(date(2026, 7, 16), probe_report=report)

    assert len(payload["items"]) == 13
    assert payload["machine_vs_owner_blocker_summary"]["total_sources"] == 13
    assert payload["machine_vs_owner_blocker_summary"]["unavailable_sources"] == 1
    assert payload["machine_vs_owner_blocker_summary"]["owner_decision_questions_required"] == 12

    for item in payload["items"]:
        assert item["adapter_status"] == "candidate_adapter_ready"
        if item["source_id"] == "pit.quarterly_financials":
            assert item["owner_action_required"] is False
            assert item["remaining_blocker_category"] == "mops_candidate_artifact_not_supplied"
        else:
            assert item["owner_action_required"] is True
            assert item["minimum_owner_question"].startswith("是否核准將來自")
            assert item["remaining_blocker_category"] == "legal_and_license_acceptance_required"


def test_export_p0_handoff_packet_generates_valid_temp_json() -> None:
    from scripts.run_p0_candidate_audit import export_p0_handoff_packet, main
    import json

    report = _probe_report()
    payload = build_p0_candidate_audit(date(2026, 7, 16), probe_report=report)
    target_path = export_p0_handoff_packet(payload)

    assert target_path.exists()
    content = json.loads(target_path.read_text(encoding="utf-8"))
    assert content["task_id"] == "GEMINI-P0-13-MACHINE-AUDIT-AND-BLOCKER-REDUCTION-V1"
    assert content["base_head"] == "3319b1c0372503ab865c45e376e299e52d943834"
    assert len(content["matrix_13_sources"]) == 13
    assert content["safety_flags"]["no_formal_db_mutation"] is True
    assert content["status"] == "audit_generated_not_validation_handoff"
