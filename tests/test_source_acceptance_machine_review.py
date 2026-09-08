from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from data_module.source_acceptance_decision_registry import (
    MACHINE_DECISION_ACTOR,
    MACHINE_DECISION_POLICY_VERSION,
    SourceAcceptanceDecisionRegistry,
    parse_source_acceptance_decision_revision,
)
from data_module.source_acceptance_governance import (
    MACHINE_EVIDENCE_SCHEMA_VERSION,
    SourceAcceptanceGovernance,
    calculate_machine_evidence_hash,
)
from scripts.append_source_acceptance_decision import (
    build_machine_decision_from_evidence,
    append_decision,
    inspect_decision_input,
    main,
)


SOURCE_ID = "institutional_flows"


def _producer_code_hash(filename: str) -> str:
    path = Path(__file__).resolve().parents[1] / "scripts" / filename
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _write_artifact(root: Path, name: str, payload: dict[str, object]) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    path.write_bytes(raw)
    return {
        "evidence_id": str(payload["evidence_id"]),
        "artifact_path": name,
        "content_sha256": f"sha256:{sha256(raw).hexdigest()}",
    }


def _machine_evidence(root: Path, **changes: object) -> dict[str, object]:
    license_id = "license:twse:terms:20260828"
    quality_id = "quality:institutional_flows:20260828"
    pit_id = "pit:institutional_flows:20260828"
    availability_id = "availability:institutional_flows:20260828"

    coverage = {
        "numerator": 196,
        "denominator": 200,
        "expected_universe_count": 200,
        "coverage_bp": 9800,
        "basis": "covered_expected_universe_members",
    }
    row_conservation = {
        "raw": 100,
        "accepted": 98,
        "quarantine": 1,
        "blocked": 1,
    }
    quarantine = {
        "status": "verified",
        "policy": "malformed rows isolated",
        "quarantined_rows": 1,
        "blocked_rows": 1,
    }
    maturity = {
        "status": "mature",
        "completed_periods": 4,
        "minimum_periods": 4,
        "lineage_complete": True,
    }

    license_artifact = {
        "schema_version": "source-acceptance-license-evidence.v1",
        "producer": "capture_p0_license_evidence.py",
        "producer_code_sha256": _producer_code_hash("capture_p0_license_evidence.py"),
        "source_id": SOURCE_ID,
        "evidence_id": license_id,
        "status": "approved",
        "source_url": "https://www.twse.com.tw/zh/terms/use.html",
        "final_url": "https://www.twse.com.tw/zh/terms/use.html",
        "http_status": 200,
        "content_sha256": "a" * 64,
        "captured_at_utc": "2026-08-28T11:00:00+00:00",
        "truncated": False,
        "keyword_flags": {"agreement_or_license": {"matched": True, "terms": ["terms"]}},
        "final_host_allowlisted": True,
        "agreement_or_license_present": True,
        "content_persisted": False,
    }
    quality_artifact = {
        "schema_version": "source-acceptance-quality-evidence.v1",
        "producer": "run_p0_source_evidence_audit.py",
        "producer_code_sha256": _producer_code_hash("run_p0_source_evidence_audit.py"),
        "source_id": SOURCE_ID,
        "source_version": "official-v1",
        "evidence_id": quality_id,
        "status": "verified",
        "quality_score_bp": 9800,
        "content_sha256": "b" * 64,
        "auto_verifiable": [
            "schema_validation_passed",
            "row_conservation_verified",
            "isolation_guaranteed",
            "payload_hash_verified",
            "maturity_window_verified",
        ],
        "checks": {
            "schema_valid": True,
            "reconciled": True,
            "quarantine_complete": True,
        },
        "expected_universe": {
            "source_id": SOURCE_ID,
            "evidence_id": "universe:institutional_flows:20260828",
            "content_sha256": "e" * 64,
            "count": 200,
            "as_of_date": "2026-08-27",
        },
        "coverage": coverage,
        "row_conservation": row_conservation,
        "quarantine": quarantine,
        "maturity": maturity,
    }
    pit_artifact = {
        "schema_version": "source-acceptance-pit-evidence.v1",
        "producer": "run_p0_source_evidence_audit.py",
        "producer_code_sha256": _producer_code_hash("run_p0_source_evidence_audit.py"),
        "source_id": SOURCE_ID,
        "source_version": "official-v1",
        "evidence_id": pit_id,
        "status": "verified",
        "lineage_complete": True,
        "content_sha256": "c" * 64,
        "auto_verifiable": ["payload_hash_verified"],
        "lineage_artifact_hashes": ["e" * 64],
        "observations": [
            {
                "source_id": SOURCE_ID,
                "source_version": "official-v1",
                "available_date": "2026-08-27",
                "available_at": "2026-08-27T16:00:00+00:00",
                "status": "verified",
            }
        ],
    }
    availability_artifact = {
        "schema_version": "source-acceptance-availability-evidence.v1",
        "producer": "run_p0_source_evidence_audit.py",
        "producer_code_sha256": _producer_code_hash("run_p0_source_evidence_audit.py"),
        "source_id": SOURCE_ID,
        "evidence_id": availability_id,
        "status": "available",
        "content_sha256": "d" * 64,
        "available_date": "2026-08-27",
        "available_at": "2026-08-27T16:00:00+00:00",
        "observed_at": "2026-08-28T11:30:00+00:00",
    }

    payload: dict[str, object] = {
        "schema_version": MACHINE_EVIDENCE_SCHEMA_VERSION,
        "policy_version": MACHINE_DECISION_POLICY_VERSION,
        "source_id": SOURCE_ID,
        "decision_date": "2026-08-28",
        "decision_timestamp": "2026-08-28T12:00:00+00:00",
        "decision_revision_id": "machine:institutional_flows:good",
        "parent_revision_id": None,
        "source_version": "official-v1",
        "license": _write_artifact(root, "license.json", license_artifact),
        "quality": _write_artifact(root, "quality.json", quality_artifact),
        "pit": _write_artifact(root, "pit.json", pit_artifact),
        "coverage": coverage,
        "row_conservation": row_conservation,
        "quarantine": quarantine,
        "availability": _write_artifact(root, "availability.json", availability_artifact),
        "maturity": maturity,
        "allowed_use_cases": ["research_shadow", "diagnostics"],
        "rollback_reference": "decision:disable:institutional_flows:machine",
    }
    payload.update(deepcopy(changes))
    payload["content_sha256"] = calculate_machine_evidence_hash(payload)
    return payload


def _refresh_artifact(
    payload: dict[str, object], root: Path, section: str, **changes: object
) -> None:
    envelope = payload[section]
    assert isinstance(envelope, dict)
    path = root / str(envelope["artifact_path"])
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(artifact, dict)
    artifact.update(deepcopy(changes))
    raw = json.dumps(
        artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    path.write_bytes(raw)
    envelope["content_sha256"] = f"sha256:{sha256(raw).hexdigest()}"
    for field_name, value in changes.items():
        if field_name in {"coverage", "row_conservation", "quarantine", "maturity"}:
            payload[field_name] = deepcopy(value)
    payload["content_sha256"] = calculate_machine_evidence_hash(payload)


def test_complete_machine_evidence_decides_limited_without_named_reviewer(
    tmp_path: Path,
) -> None:
    payload = _machine_evidence(tmp_path)
    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=tmp_path
    )

    assert review.status == "machine_verified"
    assert review.blockers == ()
    assert review.decision is not None
    assert review.decision.status == "limited"
    assert review.decision.reviewer_role == ""
    assert review.decision.owner_role == MACHINE_DECISION_ACTOR
    assert review.decision.decision_actor == MACHINE_DECISION_ACTOR
    assert review.decision.decision_policy_version == MACHINE_DECISION_POLICY_VERSION
    assert review.decision.decision_evidence_hash == review.evidence_content_hash
    assert "no human attestation inferred" in review.decision.decision_reason
    assert set(review.decision.allowed_use_cases) == {"research_shadow", "diagnostics"}


def test_machine_caller_binds_artifacts_and_keeps_shadow_boundary(tmp_path: Path) -> None:
    evidence_path = tmp_path / "machine-evidence.json"
    output_path = tmp_path / "preview.json"
    payload = _machine_evidence(tmp_path)
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert main(
        ["--machine-evidence", str(evidence_path), "--output", str(output_path)]
    ) == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["decision"]["decision_actor"] == MACHINE_DECISION_ACTOR
    assert result["machine_evidence_binding"]["review_status"] == "machine_verified"
    assert result["safety_flags"]["downstream_eligibility"] == "none"
    assert result["safety_flags"]["formal_oos_allowed"] is False
    assert result["safety_flags"]["production_scheduler_allowed"] is False
    assert result["safety_flags"]["broker_order_allowed"] is False

    revision = build_machine_decision_from_evidence(payload, evidence_root=tmp_path)
    inspected = inspect_decision_input(revision, machine_evidence_path=evidence_path)
    assert (
        inspected["machine_evidence_binding"]["evidence_content_hash"]
        == payload["content_sha256"]
    )


def test_machine_caller_can_append_only_to_a_candidate_registry(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    payload = _machine_evidence(evidence_root)
    evidence_path = evidence_root / "machine-evidence.json"
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    registry_path = tmp_path / "candidate.sqlite"
    revision = build_machine_decision_from_evidence(payload, evidence_root=evidence_root)

    result = append_decision(
        revision,
        registry_path=registry_path,
        machine_evidence_path=evidence_path,
    )

    assert result["status"] == "appended"
    assert result["registry_append_confirmed"] is True
    assert result["safety_flags"]["downstream_eligibility"] == "none"
    stored = SourceAcceptanceDecisionRegistry(registry_path).current(SOURCE_ID)
    assert stored == revision


def test_tampered_child_artifact_is_rejected_by_recomputed_hash(tmp_path: Path) -> None:
    payload = _machine_evidence(tmp_path)
    quality_envelope = payload["quality"]
    assert isinstance(quality_envelope, dict)
    quality_path = tmp_path / str(quality_envelope["artifact_path"])
    quality_artifact = json.loads(quality_path.read_text(encoding="utf-8"))
    quality_artifact["quality_score_bp"] = 9900
    quality_path.write_text(json.dumps(quality_artifact), encoding="utf-8")

    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=tmp_path
    )

    assert review.decision is None
    assert "machine_evidence_quality_artifact_hash_mismatch" in review.blockers


def test_missing_or_unstructured_license_does_not_pass_as_evidence(tmp_path: Path) -> None:
    payload = _machine_evidence(tmp_path, license="reviewed")
    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=tmp_path
    )

    assert review.decision is None
    assert "machine_evidence_license_missing" in review.blockers
    assert "machine_evidence_license_status_not_approved" in review.blockers


def test_immature_or_unavailable_evidence_remains_blocked(tmp_path: Path) -> None:
    immature_root = tmp_path / "immature"
    immature = _machine_evidence(immature_root)
    _refresh_artifact(
        immature,
        immature_root,
        "quality",
        maturity={
            "status": "immature",
            "completed_periods": 3,
            "minimum_periods": 4,
            "lineage_complete": True,
        },
    )
    review_immature = SourceAcceptanceGovernance().evaluate_machine_evidence(
        immature, evidence_root=immature_root
    )
    assert "machine_evidence_maturity_incomplete" in review_immature.blockers

    unavailable_root = tmp_path / "unavailable"
    unavailable = _machine_evidence(unavailable_root)
    _refresh_artifact(unavailable, unavailable_root, "availability", status="unavailable")
    review_unavailable = SourceAcceptanceGovernance().evaluate_machine_evidence(
        unavailable, evidence_root=unavailable_root
    )
    assert "machine_evidence_availability_unavailable" in review_unavailable.blockers


def test_future_capture_and_observation_timestamps_are_blocked(tmp_path: Path) -> None:
    payload = _machine_evidence(tmp_path)
    _refresh_artifact(
        payload,
        tmp_path,
        "availability",
        observed_at="2099-01-01T00:00:00+00:00",
    )
    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=tmp_path
    )

    assert review.decision is None
    assert "machine_evidence_availability_observed_after_decision" in review.blockers


def test_future_license_capture_and_same_day_pit_timestamp_are_blocked(
    tmp_path: Path,
) -> None:
    license_payload = _machine_evidence(tmp_path / "license")
    _refresh_artifact(
        license_payload,
        tmp_path / "license",
        "license",
        captured_at_utc="2099-01-01T00:00:00+00:00",
    )
    license_review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        license_payload, evidence_root=tmp_path / "license"
    )
    assert "machine_evidence_license_capture_after_decision" in license_review.blockers

    pit_payload = _machine_evidence(tmp_path / "pit")
    _refresh_artifact(
        pit_payload,
        tmp_path / "pit",
        "pit",
        observations=[
            {
                "source_id": SOURCE_ID,
                "source_version": "official-v1",
                "available_date": "2026-08-28",
                "available_at": "2026-08-28T13:00:00+00:00",
                "status": "verified",
            }
        ],
    )
    pit_review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        pit_payload, evidence_root=tmp_path / "pit"
    )
    assert "machine_evidence_pit_available_after_decision" in pit_review.blockers


def test_typed_coverage_failure_is_fail_closed_without_integer_coercion(
    tmp_path: Path,
) -> None:
    payload = _machine_evidence(tmp_path)
    _refresh_artifact(
        payload,
        tmp_path,
        "quality",
        coverage={
            "numerator": 196,
            "denominator": 200,
            "expected_universe_count": 200,
            "coverage_bp": None,
            "basis": "covered_expected_universe_members",
        },
    )
    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=tmp_path
    )

    assert review.decision is None
    assert "machine_evidence_coverage_invalid" in review.blockers


def test_expected_universe_is_independent_from_raw_row_count(tmp_path: Path) -> None:
    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        _machine_evidence(tmp_path), evidence_root=tmp_path
    )

    assert review.status == "machine_verified"
    assert review.decision is not None


def test_unauthorized_scope_is_rejected_and_cannot_expand_machine_decision(
    tmp_path: Path,
) -> None:
    payload = _machine_evidence(
        tmp_path, allowed_use_cases=["research_shadow", "formal_scoring"]
    )
    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=tmp_path
    )

    assert review.decision is None
    assert "machine_evidence_use_scope_unauthorized" in review.blockers


def test_machine_decision_round_trips_through_registry_parser(tmp_path: Path) -> None:
    revision = build_machine_decision_from_evidence(
        _machine_evidence(tmp_path), evidence_root=tmp_path
    )
    restored = parse_source_acceptance_decision_revision(revision.to_dict())

    assert restored == revision
    assert restored.reviewer_role == ""
    assert restored.decision_actor == MACHINE_DECISION_ACTOR
