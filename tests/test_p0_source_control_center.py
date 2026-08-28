from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from app_module.p0_source_control_center import (
    CONTROL_CENTER_SCHEMA_VERSION,
    P0SourceControlCenterService,
)
from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.source_acceptance_decision_registry import SourceAcceptanceDecisionRevision


def _candidate_audit(*, machine_status: str = "verified") -> dict[str, object]:
    return {
        "schema_version": "p0-candidate-audit.v1",
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "human_decision": "requires_human_acceptance",
        "items": [
            {
                "source_id": source_id,
                "audit_status": "observed_candidate",
                "machine_status": machine_status if source_id == P0_SOURCE_IDS[0] else "verified",
                "row_count": 10,
                "accepted_row_count": 10,
                "blocked_row_count": 0,
                "payload_sha256": "a" * 64,
                "blockers": ["research_only_not_source_accepted"],
            }
            for source_id in P0_SOURCE_IDS
        ],
    }


def _license_evidence(*, status: str = "transport_error") -> dict[str, object]:
    return {
        "schema_version": "p0-license-evidence-capture.v1",
        "candidate_only": True,
        "source_acceptance_granted": False,
        "license_accepted": False,
        "downstream_eligibility": "none",
        "formal_eligible": False,
        "production_ingestion_allowed": False,
        "production_scheduler_allowed": False,
        "targets": [
            {
                "license_evidence_url": "https://www.twse.com.tw/zh/terms/use.html",
                "source_ids": ["institutional_flows"],
                "status": status,
                "content_sha256": "a" * 64 if status == "captured" else None,
                "keyword_flags": {
                    "automated_access_or_crawler": {"matched": True, "terms": ["自動"]}
                },
            }
        ],
    }


def test_default_center_is_authoritative_and_fail_closed() -> None:
    center = P0SourceControlCenterService().build()

    assert center.schema_version == CONTROL_CENTER_SCHEMA_VERSION
    assert center.p0_source_count == 13
    assert tuple(row.source_id for row in center.rows) == P0_SOURCE_IDS
    assert center.contract_only_count == 13
    assert center.accepted_count == 0
    assert center.limited_count == 0
    assert center.downstream_eligible_count == 0
    assert center.read_only is True
    assert center.writes_allowed is False
    assert center.production_ingestion_allowed is False
    assert center.production_scheduler_allowed is False
    assert center.formal_oos_allowed is False
    assert center.auto_accept_allowed is False
    assert all(row.downstream_eligibility == "none" for row in center.rows)
    assert all("candidate_audit_not_supplied" in row.blockers for row in center.rows)
    assert all("source_acceptance_decision_missing" in row.blockers for row in center.rows)


def test_candidate_audit_projects_machine_status_without_granting_acceptance() -> None:
    center = P0SourceControlCenterService().build(candidate_audit=_candidate_audit())

    first = center.rows[0]
    assert first.governance_status == "research_shadow"
    assert first.machine_status == "verified"
    assert first.audit_status == "observed_candidate"
    assert first.observed_rows == 10
    assert first.accepted_rows == 10
    assert first.downstream_eligibility == "none"
    assert "research_only_not_source_accepted" in first.blockers
    assert "license_not_accepted" in first.blockers
    assert center.research_shadow_count == 13
    assert center.downstream_eligible_count == 0


def test_degraded_machine_evidence_is_blocked_provenance() -> None:
    center = P0SourceControlCenterService().build(
        candidate_audit=_candidate_audit(machine_status="degraded")
    )

    assert center.rows[0].governance_status == "blocked_provenance"
    assert center.blocked_count == 1
    assert center.rows[1].governance_status == "research_shadow"


def test_official_evidence_matrix_is_supported_as_read_only_input() -> None:
    payload = {
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
                "raw_row_count": 2,
                "accepted_row_count": 2,
                "blocked_row_count": 0,
                "provider": "official",
                "remaining_blocker": "legal_and_license_acceptance_required",
            }
            for source_id in P0_SOURCE_IDS
        ],
    }

    center = P0SourceControlCenterService().build(candidate_audit=payload)

    assert center.rows[0].audit_status == "network_probed"
    assert center.rows[0].observed_rows == 2
    assert center.rows[0].accepted_rows == 2
    assert center.rows[0].governance_status == "research_shadow"
    assert center.downstream_eligible_count == 0


def test_license_candidate_evidence_is_visible_without_granting_acceptance() -> None:
    center = P0SourceControlCenterService().build(
        license_evidence=_license_evidence()
    )

    row = next(item for item in center.rows if item.source_id == "institutional_flows")
    assert row.license_evidence_urls == (
        "https://www.twse.com.tw/zh/terms/use.html",
    )
    assert row.license_evidence_capture_status == "capture_transport_error"
    assert row.license_evidence_content_sha256 == ()
    assert row.license_evidence_keyword_groups == (
        "automated_access_or_crawler",
    )
    assert row.license_status == "requires_review"
    assert row.downstream_eligibility == "none"


def test_captured_license_candidate_hash_is_projected_but_not_accepted() -> None:
    center = P0SourceControlCenterService().build(
        license_evidence=_license_evidence(status="captured")
    )
    row = next(item for item in center.rows if item.source_id == "institutional_flows")
    assert row.license_evidence_capture_status == "captured_candidate"
    assert row.license_evidence_content_sha256 == ("a" * 64,)
    assert row.license_status == "requires_review"
    assert "license_not_accepted" in row.blockers


def test_mixed_license_candidate_capture_is_projected_as_partial() -> None:
    payload = _license_evidence(status="captured")
    targets = payload["targets"]
    assert isinstance(targets, list)
    targets.append(
        {
            "license_evidence_url": (
                "https://www.tpex.org.tw/web/inc/gtsm_disclaimer.php?l=zh-tw"
            ),
            "source_ids": ["institutional_flows"],
            "status": "http_error",
            "content_sha256": None,
            "keyword_flags": {},
        }
    )

    center = P0SourceControlCenterService().build(license_evidence=payload)
    row = next(item for item in center.rows if item.source_id == "institutional_flows")

    assert row.license_evidence_capture_status == "capture_partial"
    assert row.license_evidence_content_sha256 == ("a" * 64,)
    assert row.license_status == "requires_review"
    assert "license_not_accepted" in row.blockers


def test_decision_projection_is_visible_but_never_grants_downstream() -> None:
    decision = SourceAcceptanceDecisionRevision(
        source_id=P0_SOURCE_IDS[0],
        decision_revision_id="decision:source:r1",
        parent_revision_id=None,
        status="limited",
        allowed_use_cases=("internal_research_shadow",),
        blockers=(),
        license_evidence_ids=("license:review-1",),
        quality_evidence_ids=("quality:review-1",),
        pit_evidence_ids=("pit:review-1",),
        owner_role="owner",
        reviewer_role="reviewer",
        decided_at="2026-08-26T12:00:00+00:00",
        rollback_reference="decision:disable-next",
    )

    center = P0SourceControlCenterService().build(decisions=(decision,))

    row = center.rows[0]
    assert row.decision_status == "limited"
    assert row.governance_status == "limited"
    assert row.allowed_use_cases == ("internal_research_shadow",)
    assert row.downstream_eligibility == "none"
    assert center.limited_count == 1
    assert center.downstream_eligible_count == 0
    assert center.auto_accept_allowed is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("license_evidence_ids", (), "license evidence"),
        ("quality_evidence_ids", (), "quality evidence"),
        ("pit_evidence_ids", (), "PIT evidence"),
        ("blockers", ("pending_owner_review",), "cannot retain blockers"),
        ("allowed_use_cases", ("formal_scoring",), "formal or production"),
    ],
)
def test_control_center_rejects_malformed_applying_decision(
    field: str, value: tuple[str, ...], message: str
) -> None:
    values: dict[str, object] = {
        "source_id": P0_SOURCE_IDS[0],
        "decision_revision_id": "decision:source:invalid",
        "parent_revision_id": None,
        "status": "limited",
        "allowed_use_cases": ("internal_research_shadow",),
        "blockers": (),
        "license_evidence_ids": ("license:review-1",),
        "quality_evidence_ids": ("quality:review-1",),
        "pit_evidence_ids": ("pit:review-1",),
        "owner_role": "owner",
        "reviewer_role": "reviewer",
        "decided_at": "2026-08-26T12:00:00+00:00",
        "rollback_reference": "decision:disable-next",
    }
    values[field] = value
    decision = SourceAcceptanceDecisionRevision(**values)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=message):
        P0SourceControlCenterService().build(decisions=(decision,))


def test_control_center_rejects_timezone_less_decision() -> None:
    decision = SourceAcceptanceDecisionRevision(
        source_id=P0_SOURCE_IDS[0],
        decision_revision_id="decision:source:naive-time",
        parent_revision_id=None,
        status="deferred",
        allowed_use_cases=(),
        blockers=("pending",),
        license_evidence_ids=(),
        quality_evidence_ids=(),
        pit_evidence_ids=(),
        owner_role="owner",
        reviewer_role="reviewer",
        decided_at="2026-08-26T12:00:00",
        rollback_reference="decision:disable-next",
    )

    with pytest.raises(ValueError, match="timezone"):
        P0SourceControlCenterService().build(decisions=(decision,))


@pytest.mark.parametrize("schema_version", [None, "unknown.v1"])
def test_unknown_audit_schema_fails_closed(schema_version: object) -> None:
    payload = _candidate_audit()
    payload["schema_version"] = schema_version

    with pytest.raises(ValueError, match="unsupported P0 audit schema"):
        P0SourceControlCenterService().build(candidate_audit=payload)


def test_audit_boundary_and_source_denominator_are_strict() -> None:
    unsafe = _candidate_audit()
    unsafe["formal_oos_allowed"] = True
    with pytest.raises(ValueError, match="boundary mismatch"):
        P0SourceControlCenterService().build(candidate_audit=unsafe)

    missing = _candidate_audit()
    missing["items"] = list(missing["items"][:-1])  # type: ignore[index]
    with pytest.raises(ValueError, match="missing sources"):
        P0SourceControlCenterService().build(candidate_audit=missing)


def test_payload_is_immutable_and_serializable() -> None:
    center = P0SourceControlCenterService().build()

    with pytest.raises(TypeError):
        center.status_counts["new"] = 1  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        center.rows = ()  # type: ignore[misc]

    payload = center.to_dict()
    assert payload["schema_version"] == CONTROL_CENTER_SCHEMA_VERSION
    assert payload["p0_source_count"] == 13
    assert len(payload["rows"]) == 13
    assert payload["boundary"]["auto_accept_allowed"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("accepted_count", 1, "accepted_count"),
        ("status_counts", {"accepted": 1}, "status_counts"),
        ("machine_status_counts", {"verified": 13}, "machine_status_counts"),
        ("decision_status_counts", {"accepted": 1}, "decision_status_counts"),
        ("read_only", False, "read_only"),
        ("production_scheduler_allowed", True, "production_scheduler_allowed"),
    ],
)
def test_control_center_rejects_inconsistent_counts_or_boundary(
    field: str, value: object, message: str
) -> None:
    center = P0SourceControlCenterService().build()

    with pytest.raises((TypeError, ValueError), match=message):
        replace(center, **{field: value})


def test_control_center_cli_emits_json_and_markdown(tmp_path, capsys) -> None:
    from scripts.inspect_p0_source_control_center import main

    json_path = tmp_path / "control-center.json"
    markdown_path = tmp_path / "control-center.md"
    assert main(["--format", "json", "--output", str(json_path)]) == 0
    assert main(["--format", "markdown", "--output", str(markdown_path)]) == 0

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["p0_source_count"] == 13
    assert "downstream_eligibility_none" in payload["global_blockers"]
    assert "P0 Data Source Control Center" in markdown
    assert "candidate_audit_not_supplied" in markdown
    _ = capsys.readouterr()


def test_control_center_cli_accepts_single_owner_review_deferred_decision(tmp_path) -> None:
    decision_path = tmp_path / "owner-review.json"
    decision_path.write_text(
        json.dumps(
            {
                "schema_version": "source-acceptance-owner-review-decision.v1",
                "source_id": P0_SOURCE_IDS[0],
                "decision_revision_id": "decision:source:deferred",
                "parent_revision_id": None,
                "status": "deferred",
                "owner_role": "owner",
                "reviewer_role": "reviewer",
                "decision_timestamp": "2026-08-27T12:00:00+08:00",
                "active_blockers": ["source_acceptance_not_authorized"],
                "rollback_reference": "owner-policy:disable",
            }
        ),
        encoding="utf-8",
    )

    from scripts.inspect_p0_source_control_center import inspect_p0_source_control_center

    payload = inspect_p0_source_control_center(decision_path=decision_path)

    row = payload["rows"][0]
    assert row["decision_status"] == "deferred"
    assert row["revision"] == "decision:source:deferred"
    assert "source_acceptance_not_authorized" in row["blockers"]
    assert payload["accepted_count"] == 0


def test_control_center_cli_reports_out_of_denominator_decision_without_traceback(
    tmp_path, capsys
) -> None:
    decision_path = tmp_path / "fubon-owner-review.json"
    decision_path.write_text(
        json.dumps(
            {
                "schema_version": "source-acceptance-owner-review-decision.v1",
                "source_id": "fubon.marketdata",
                "decision_revision_id": "decision:fubon:deferred",
                "parent_revision_id": None,
                "status": "deferred",
                "owner_role": "owner",
                "reviewer_role": "reviewer",
                "decision_timestamp": "2026-08-27T12:00:00+08:00",
                "active_blockers": ["source_acceptance_not_authorized"],
                "rollback_reference": "owner-policy:disable",
            }
        ),
        encoding="utf-8",
    )

    from scripts.inspect_p0_source_control_center import main

    assert main(["--decision-json", str(decision_path), "--format", "json"]) == 2
    assert "outside P0 denominator" in capsys.readouterr().err
