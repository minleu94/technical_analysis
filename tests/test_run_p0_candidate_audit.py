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
    ex_dividend = next(item for item in payload["items"] if item["source_id"] == "corporate_action.ex_dividend_timeline")
    reduction = next(item for item in payload["items"] if item["source_id"] == "corporate_action.reduction_split_par_value")
    assert ex_dividend["audit_status"] == "observed_candidate"
    assert reduction["audit_status"] == "observed_candidate"
    unimplemented = next(item for item in payload["items"] if item["source_id"] == "pit.quarterly_financials")
    assert unimplemented["audit_status"] == "not_started_no_candidate_adapter"
    assert unimplemented["blockers"] == ["candidate_adapter_not_implemented"]


def test_probe_report_hash_is_stable_across_source_order() -> None:
    report = _probe_report()
    reversed_report = {**report, "sources": list(reversed(report["sources"]))}  # type: ignore[arg-type]

    first = build_p0_candidate_audit(date(2026, 7, 16), probe_report=report)
    second = build_p0_candidate_audit(date(2026, 7, 16), probe_report=reversed_report)

    assert first["lineage"]["probe_report_sha256"] == second["lineage"]["probe_report_sha256"]


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
