from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from scripts.build_p0_intake_from_audit import (
    AUDIT_SCHEMA_VERSION,
    build_candidate_intake,
    main,
)
from scripts.inspect_p0_intake_readiness import inspect_p0_intake


def _audit_payload() -> dict[str, object]:
    matrix = []
    for index, source_id in enumerate(P0_SOURCE_IDS):
        matrix.append(
            {
                "source_id": source_id,
                "machine_status": "verified" if index == 0 else "degraded",
                "availability": "network_probed",
                "timestamp_kind": "official_publication_timestamp",
                "pit_status": "pit_date_verified",
                "raw_row_count": 100 + index,
                "accepted_row_count": 90 + index,
                "quarantine_row_count": index,
                "blocked_row_count": 0,
                "payload_sha256": f"payload-{index}",
            }
        )
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "decision_date": "2026-08-28",
        "machine_evidence_matrix": matrix,
        "safety_flags": {
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_allowed": False,
            "training_allowed": False,
            "promotion_allowed": False,
            "scheduler_allowed": False,
            "unblind_allowed": False,
            "production_blend_alpha_bp": 0,
            "downstream_eligibility": "none",
        },
    }


def test_machine_audit_is_projected_without_authority_upgrade() -> None:
    payload = build_candidate_intake(_audit_payload())

    assert payload["schema_version"] == "p0-source-intake.v1"
    assert payload["safety_flags"]["auto_accept_allowed"] is False
    dossiers = payload["dossiers"]
    assert isinstance(dossiers, list)
    assert len(dossiers) == 13
    assert [item["source_id"] for item in dossiers] == list(P0_SOURCE_IDS)
    assert dossiers[0]["coverage_numerator"] == 90
    assert dossiers[0]["coverage_denominator"] == 100
    assert dossiers[0]["row_conservation_counts"] == {
        "raw": 100,
        "accepted": 90,
        "quarantine": 0,
        "blocked": 0,
    }
    assert dossiers[0]["license_status"] == "requires_review"
    assert dossiers[0]["source_owner_role"] == ""
    assert dossiers[0]["downstream_eligibility"] == "none"
    assert all("unverified" in item["publication_time_policy"] for item in dossiers)

    inspected = inspect_p0_intake(payload)
    assert inspected["status"] == "deferred"
    assert inspected["valid_dossier_count"] == 13
    assert inspected["owner_review_ready_count"] == 0
    assert all(row["decision_preview"]["status"] == "deferred" for row in inspected["rows"])


def test_invalid_audit_denominator_and_safety_are_rejected() -> None:
    payload = _audit_payload()
    matrix = payload["machine_evidence_matrix"]
    assert isinstance(matrix, list)
    matrix[-1] = copy.deepcopy(matrix[0])
    with pytest.raises(ValueError, match="denominator/order"):
        build_candidate_intake(payload)

    unsafe = _audit_payload()
    unsafe["safety_flags"]["production_allowed"] = True
    with pytest.raises(ValueError, match="production_allowed"):
        build_candidate_intake(unsafe)


def test_absent_machine_counts_remain_missing_not_zero_observation() -> None:
    payload = _audit_payload()
    matrix = payload["machine_evidence_matrix"]
    assert isinstance(matrix, list)
    for key in ("raw_row_count", "accepted_row_count", "quarantine_row_count", "blocked_row_count"):
        matrix[-1].pop(key)

    candidate = build_candidate_intake(payload)
    dossiers = candidate["dossiers"]
    assert isinstance(dossiers, list)
    assert dossiers[-1]["row_conservation_counts"] == {}
    assert dossiers[-1]["coverage_numerator"] == 0
    assert dossiers[-1]["coverage_denominator"] == 0


def test_cli_writes_temp_candidate_and_rejects_production_path(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(_audit_payload()), encoding="utf-8")
    output_path = tmp_path / "candidate-intake.json"
    assert main(["--audit", str(audit_path), "--output", str(output_path)]) == 0
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["provenance"]["machine_evidence_only"] is True

    production_path = Path("D:/Min/Python/Project/FA_Data") / "candidate-intake.json"
    assert main(["--audit", str(audit_path), "--output", str(production_path)]) == 2
    assert not production_path.exists()
