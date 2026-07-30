from __future__ import annotations

from pathlib import Path
import re

from scripts.build_v4_gate_revision_batch import build_gate_revisions


def _revisions() -> tuple[dict[str, object], ...]:
    source_rows = [
        {
            "source_id": f"source-{index:02d}",
            "machine_status": "degraded" if index < 12 else "missing",
            "pit_status": "official_publication_timestamp_missing",
            "remaining_blocker": "official_publication_timestamp_missing",
        }
        for index in range(13)
    ]
    return build_gate_revisions(
        decision_date="2026-07-29",
        pre_v2={
            "items": [
                {
                    "item_id": "weekly_history",
                    "observed_count": 0,
                    "required_count": 3,
                }
            ]
        },
        p0_audit={"machine_evidence_matrix": source_rows},
        pit_coverage={
            "families": [
                {"family_id": "monthly_revenue", "eligible": 3680, "total": 246331},
                {"family_id": "quarterly_statement", "eligible": 0, "total": 1645555},
                {"family_id": "corporate_action", "status": "coverage_deferred"},
            ]
        },
        evidence_hashes={
            "pre_v2": "sha256:" + "a" * 64,
            "p0_audit": "sha256:" + "b" * 64,
            "pit_coverage": "sha256:" + "c" * 64,
        },
    )


def test_gate_batch_closes_policy_gates_without_faking_elapsed_evidence() -> None:
    revisions = _revisions()
    by_id = {item["item_id"]: item for item in revisions}

    assert by_id["evidence:weekly-history-3"]["status"] == "insufficient_evidence"
    assert by_id["p0:source-acceptance-13"]["status"] == "complete"
    assert "accepted\":0" in by_id["p0:source-acceptance-13"]["notes"]
    assert by_id["paper:policy-approval"]["status"] == "complete"
    assert by_id["ml:promotion-policy"]["status"] == "complete"
    assert by_id["ml:revalidation"]["status"] == "in_progress"
    assert by_id["release:rule-operational"]["status"] == "complete"
    assert by_id["release:formal-gates"]["status"] == "insufficient_evidence"


def test_gate_batch_validation_test_files_exist() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    referenced_tests = {
        match
        for revision in _revisions()
        for command in revision["validation_commands"]
        for match in re.findall(r"tests/[A-Za-z0-9_./-]+\.py", str(command))
    }

    assert referenced_tests
    assert {
        path
        for path in referenced_tests
        if not (repository_root / path).is_file()
    } == set()
    promotion = next(
        item for item in _revisions() if item["item_id"] == "ml:promotion-policy"
    )
    assert promotion["validation_commands"] == [
        "pytest tests/test_ml_allocation_validation.py -q"
    ]


def test_gate_batch_assigns_next_append_only_revision() -> None:
    source_rows = [
        {
            "source_id": f"source-{index:02d}",
            "machine_status": "degraded",
            "pit_status": "official_publication_timestamp_missing",
            "remaining_blocker": "official_publication_timestamp_missing",
        }
        for index in range(13)
    ]
    revisions = build_gate_revisions(
        decision_date="2026-07-30",
        pre_v2={
            "items": [
                {
                    "item_id": "weekly_history",
                    "observed_count": 0,
                    "required_count": 3,
                }
            ]
        },
        p0_audit={"machine_evidence_matrix": source_rows},
        pit_coverage={
            "families": [
                {"family_id": "monthly_revenue", "eligible": 0, "total": 1},
                {"family_id": "quarterly_statement", "eligible": 0, "total": 1},
                {"family_id": "corporate_action", "status": "coverage_deferred"},
            ]
        },
        evidence_hashes={
            "pre_v2": "sha256:" + "a" * 64,
            "p0_audit": "sha256:" + "b" * 64,
            "pit_coverage": "sha256:" + "c" * 64,
        },
        current_revisions={
            "evidence:weekly-history-3": 4,
            "ml:revalidation": 2,
        },
    )
    by_id = {item["item_id"]: item for item in revisions}

    assert by_id["evidence:weekly-history-3"]["revision"] == 5
    assert by_id["ml:revalidation"]["revision"] == 3
    assert by_id["paper:policy-approval"]["revision"] == 1
