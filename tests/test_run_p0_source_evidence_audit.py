from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile

import pytest

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from scripts.run_p0_source_evidence_audit import (
    GROUPED_OWNER_PACKET_KEYS,
    build_p0_source_evidence_audit,
    export_p0_13_handoff_json,
    validate_approved_output_path,
)


def _sample_probe_report() -> dict[str, object]:
    return {
        "probe_date": "2026-07-26",
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
                "source_id": "twse_full_delivery",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 2,
                "accepted_row_count": 2,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "f" * 64,
            },
            {
                "source_id": "twse_halt_resume",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 1,
                "accepted_row_count": 1,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "1" * 64,
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
                "payload_sha256": "2" * 64,
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
                "payload_sha256": "3" * 64,
            },
            {
                "source_id": "twse_monthly_revenue",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 5,
                "accepted_row_count": 5,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "4" * 64,
            },
            {
                "source_id": "tpex_monthly_revenue",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 5,
                "accepted_row_count": 5,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 0,
                "payload_sha256": "5" * 64,
            },
            {
                "source_id": "twse_limit_lock",
                "schema_status": "matched",
                "timestamp_evidence": "first_observed_only",
                "raw_row_count": 100,
                "accepted_row_count": 2,
                "duplicate_row_count": 0,
                "quarantine_row_count": 0,
                "blocked_row_count": 98,
                "payload_sha256": "6" * 64,
            },
        ],
    }


def test_13_sources_coverage() -> None:
    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=_sample_probe_report(),
    )
    matrix = payload["machine_evidence_matrix"]
    assert len(matrix) == 13
    matrix_ids = tuple(item["source_id"] for item in matrix)
    assert matrix_ids == P0_SOURCE_IDS


def test_official_timestamp_vs_first_observed_distinction() -> None:
    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=_sample_probe_report(),
    )
    matrix = {item["source_id"]: item for item in payload["machine_evidence_matrix"]}

    # Credit transactions has explicit official_publication_timestamp -> machine_verified
    credit = matrix["credit_transactions"]
    assert credit["machine_status"] == "verified"
    assert credit["pit_status"] == "pit_date_verified"
    assert credit["timestamp_kind"] == "official_publication_timestamp"

    # Institutional flows has first_observed_only -> degraded
    inst = matrix["institutional_flows"]
    assert inst["machine_status"] == "degraded"
    assert inst["pit_status"] == "official_publication_timestamp_missing"
    assert inst["timestamp_kind"] == "first_observed_only"
    assert "official_publication_timestamp_missing" in inst["remaining_blocker"]


def test_http_headers_and_dates_not_upgraded_to_publication_timestamp() -> None:
    # Adding HTTP Date / Last-Modified or fetch_at header info must NOT convert first_observed_only to official_publication_timestamp
    report = _sample_probe_report()
    report["sources"][0]["http_date"] = "Sun, 26 Jul 2026 18:00:00 GMT"  # type: ignore[index]
    report["sources"][0]["last_modified"] = "Sun, 26 Jul 2026 17:30:00 GMT"  # type: ignore[index]

    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=report,
    )
    inst = next(item for item in payload["machine_evidence_matrix"] if item["source_id"] == "institutional_flows")
    assert inst["machine_status"] == "degraded"
    assert inst["timestamp_kind"] == "first_observed_only"
    assert inst["pit_status"] == "official_publication_timestamp_missing"


def test_mops_artifact_missing_required_fields_fails_closed() -> None:
    # Incomplete MOPS quarterly artifact (missing available_date, revision, content_hash)
    incomplete_artifact = {
        "source_id": "mops.statement.publication",
        "captured_at": "2026-07-19T18:22:14-07:00",
        "research_only": True,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "rows": [
            {
                "stock_code": "2330",
                "statement_type": "financial_report",
                # missing statement_scope, available_date, revision, content_hash, correction_status
            }
        ],
    }

    with pytest.raises(ValueError, match=r"mops artifact missing required provenance fields|MOPS quarterly artifact"):
        build_p0_source_evidence_audit(
            date(2026, 7, 26),
            probe_report=_sample_probe_report(),
            mops_quarterly_artifact=incomplete_artifact,
        )

    # When no artifact is supplied at all, pit.quarterly_financials must be missing / unavailable
    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=_sample_probe_report(),
        mops_quarterly_artifact=None,
    )
    quarterly = next(item for item in payload["machine_evidence_matrix"] if item["source_id"] == "pit.quarterly_financials")
    assert quarterly["machine_status"] == "missing"
    assert quarterly["pit_status"] == "unavailable"
    assert quarterly["availability"] == "artifact_missing"


def test_valid_mops_artifact_upgrades_to_verified() -> None:
    valid_artifact = {
        "source_id": "mops.statement.publication",
        "source_version": "mops-v1",
        "captured_at": "2026-07-19T18:22:14-07:00",
        "research_only": True,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "rows": [
            {
                "stock_code": "2330",
                "statement_type": "financial_report",
                "statement_scope": "consolidated",
                "period": "2026-Q1",
                "period_end": "2026-03-31",
                "announcement_date": "2026-05-15T14:43:02+08:00",
                "available_date": "2026-05-15T14:43:02+08:00",
                "revision": 1,
                "content_hash": "a" * 64,
                "source_hash": "a" * 64,
                "correction_status": "none",
            }
        ],
    }

    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=_sample_probe_report(),
        mops_quarterly_artifact=valid_artifact,
    )
    quarterly = next(item for item in payload["machine_evidence_matrix"] if item["source_id"] == "pit.quarterly_financials")
    assert quarterly["machine_status"] == "verified"
    assert quarterly["pit_status"] == "pit_date_verified"
    assert quarterly["timestamp_kind"] == "official_document_upload_timestamp"


def test_grouped_owner_decision_packet_has_at_most_5_groups() -> None:
    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=_sample_probe_report(),
    )
    packet = payload["grouped_owner_decision_packet"]
    assert len(packet) <= 5
    assert len(packet) == 5

    group_keys = tuple(item["group_id"] for item in packet)
    assert group_keys == GROUPED_OWNER_PACKET_KEYS

    # Verify that each question strictly asks about research-only intent/terms acceptability and does not show raw row data
    for item in packet:
        assert "owner_question" in item
        assert "covered_source_ids" in item
        assert len(item["covered_source_ids"]) >= 1
        question = item["owner_question"]
        assert "內部研究" in question or "條款" in question or "意圖" in question
        assert "raw_row" not in item
        assert "data_rows" not in item


def test_live_mode_without_confirm_live_readonly_fails() -> None:
    with pytest.raises(ValueError, match="--confirm-live-readonly"):
        build_p0_source_evidence_audit(
            date(2026, 7, 26),
            live_mode=True,
            confirm_live_readonly=False,
        )


def test_output_path_must_be_in_approved_temp_root() -> None:
    temp_dir = Path(tempfile.gettempdir())
    valid_path = temp_dir / "technical_analysis_candidate_data" / "audit_test.json"
    assert validate_approved_output_path(valid_path) is True

    unapproved_repo_path = Path("C:/Projects/PythonProjects/technical_analysis/data/formal.db")
    assert validate_approved_output_path(unapproved_repo_path) is False
    assert validate_approved_output_path(
        Path("C:/Projects/PythonProjects/technical_analysis/candidate_reports/audit.json")
    ) is False

    with pytest.raises(ValueError, match="approved TEMP / candidate-safe"):
        build_p0_source_evidence_audit(
            date(2026, 7, 26),
            probe_report=_sample_probe_report(),
            output_path=unapproved_repo_path,
        )


def test_secret_redaction() -> None:
    report = _sample_probe_report()
    report["sources"][0]["request_parameters"] = {
        "api_key": "SECRET123",
        "cookie": "SESSIONID=XYZ",
        "date": "20260726",
    }
    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=report,
    )

    rendered = str(payload)
    assert "SECRET123" not in rendered
    assert "SESSIONID=XYZ" not in rendered
    assert "[REDACTED]" in rendered


def test_fault_isolation_one_source_failure_does_not_mask_others() -> None:
    report = _sample_probe_report()
    # Force one source probe failure
    report["sources"][0] = {
        "source_id": "twse_institutional",
        "network_status": "failed",
        "error": "connection timeout",
        "schema_status": "unavailable",
        "raw_row_count": 0,
        "accepted_row_count": 0,
        "duplicate_row_count": 0,
        "quarantine_row_count": 0,
        "blocked_row_count": 0,
    }

    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=report,
    )
    matrix = {item["source_id"]: item for item in payload["machine_evidence_matrix"]}

    # The failed source is marked missing
    inst = matrix["institutional_flows"]
    assert inst["machine_status"] == "missing"
    assert inst["availability"] == "probe_failed"

    # Other sources are unaffected
    credit = matrix["credit_transactions"]
    assert credit["machine_status"] == "verified"
    assert credit["availability"] == "network_probed"


def test_handoff_export_and_safety_flags() -> None:
    payload = build_p0_source_evidence_audit(
        date(2026, 7, 26),
        probe_report=_sample_probe_report(),
    )
    handoff_path = export_p0_13_handoff_json(payload)

    assert handoff_path.exists()
    assert handoff_path.name == "GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1.json"

    import json

    data = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert data["task_id"] == "GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1"
    assert data["status"] == "audit_generated_not_validation_handoff"
    assert data["test_suite_results"]["status"] == "not_run_by_cli"
    assert data["safety_flags"]["formal_oos_allowed"] is False
    assert data["safety_flags"]["formal_evidence_credit_authorized"] is False
    assert data["safety_flags"]["production_blend_alpha_bp"] == 0
    assert data["safety_flags"]["formal_rule_only_path_unchanged"] is True
    assert data["formal_clock_zeros"]["snapshot_count"] == 0
    assert len(data["machine_evidence_matrix"]) == 13
    assert len(data["grouped_owner_decision_packet"]) == 5
