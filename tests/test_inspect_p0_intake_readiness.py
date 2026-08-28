from __future__ import annotations

import copy
import json

import pytest

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from scripts.inspect_p0_intake_readiness import (
    P0_INTAKE_SCHEMA_VERSION,
    build_p0_intake_template,
    inspect_p0_intake,
    main,
    render_markdown,
)


def _complete_payload() -> dict[str, object]:
    payload = copy.deepcopy(build_p0_intake_template())
    dossiers = payload["dossiers"]
    assert isinstance(dossiers, list)
    for dossier in dossiers:
        assert isinstance(dossier, dict)
        dossier.update(
            {
                "source_owner_role": "data_owner",
                "license_owner_role": "legal_compliance",
                "license_status": "approved",
                "license_scope": "internal_research",
                "redistribution_policy": "internal_only",
                "publication_time_policy": "official_publication_timestamp_preserved",
                "available_date_policy": "available_date <= decision_date",
                "revision_policy": "append_only_revision_manifest",
                "pit_coverage_window": "2020-01-01..2026-08-27",
                "coverage_numerator": 100,
                "coverage_denominator": 100,
                "row_conservation_counts": {"raw": 100, "accepted": 100},
                "quarantine_policy": "quarantine_malformed_rows",
                "quality_thresholds": {"minimum_coverage_bp": 9500},
                "evidence_artifact_ids": [
                    "license:review-1",
                    "quality:review-1",
                    "pit:review-1",
                ],
                "reviewer_role": "reviewer",
                "decision_timestamp": "2026-08-27T12:00:00+08:00",
            }
        )
    return payload


def test_template_keeps_authoritative_denominator_and_safety_flags() -> None:
    payload = build_p0_intake_template()

    assert payload["schema_version"] == P0_INTAKE_SCHEMA_VERSION
    assert payload["safety_flags"] == {
        "read_only": True,
        "writes_allowed": False,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "auto_accept_allowed": False,
    }
    dossiers = payload["dossiers"]
    assert isinstance(dossiers, list)
    assert len(dossiers) == len(P0_SOURCE_IDS) == 13
    assert [item["source_id"] for item in dossiers] == list(P0_SOURCE_IDS)


def test_incomplete_template_is_deferred_but_not_invalid() -> None:
    result = inspect_p0_intake(build_p0_intake_template())

    assert result["status"] == "deferred"
    assert result["p0_source_count"] == 13
    assert result["valid_dossier_count"] == 13
    assert result["invalid_dossier_count"] == 0
    assert result["owner_review_ready_count"] == 0
    assert result["missing_source_ids"] == []
    assert all(row["status"] == "deferred" for row in result["rows"])
    assert all(row["decision_preview"]["status"] == "deferred" for row in result["rows"])
    assert result["boundary"]["writes_allowed"] is False


def test_complete_dossiers_are_ready_for_owner_review_but_never_accepted() -> None:
    result = inspect_p0_intake(_complete_payload())

    assert result["status"] == "ready_for_owner_review"
    assert result["valid_dossier_count"] == 13
    assert result["owner_review_ready_count"] == 13
    assert result["deferred_count"] == 0
    assert all(row["checklist_complete"] is True for row in result["rows"])
    assert all(row["decision_preview"]["status"] == "deferred" for row in result["rows"])
    assert all(row["decision_preview"]["allowed_use_cases"] == [] for row in result["rows"])
    assert result["boundary"]["formal_oos_allowed"] is False
    assert result["boundary"]["auto_accept_allowed"] is False


def test_missing_and_duplicate_dossiers_fail_closed_with_thirteen_rows() -> None:
    missing = build_p0_intake_template()
    missing_dossiers = missing["dossiers"]
    assert isinstance(missing_dossiers, list)
    removed_source_id = missing_dossiers[-1]["source_id"]
    missing_dossiers.pop()
    missing_result = inspect_p0_intake(missing)
    assert missing_result["status"] == "invalid_input"
    assert missing_result["missing_source_ids"] == [removed_source_id]
    assert len(missing_result["rows"]) == 13

    duplicate = build_p0_intake_template()
    duplicate_dossiers = duplicate["dossiers"]
    assert isinstance(duplicate_dossiers, list)
    duplicate_dossiers.append(copy.deepcopy(duplicate_dossiers[0]))
    duplicate_result = inspect_p0_intake(duplicate)
    assert duplicate_result["status"] == "invalid_input"
    assert duplicate_result["duplicate_source_ids"] == [P0_SOURCE_IDS[0]]
    assert len(duplicate_result["rows"]) == 13


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["safety_flags"].update({"writes_allowed": True}), "safety boundary"),
        (lambda payload: payload["dossiers"][0].update({"api_key": "secret"}), "unsupported fields"),
        (lambda payload: payload["dossiers"][0].update({"downstream_eligibility": "formal"}), "downstream_eligibility"),
    ],
)
def test_unsafe_or_malformed_input_is_rejected(
    mutation, message: str
) -> None:
    payload = build_p0_intake_template()
    mutation(payload)

    if message == "safety boundary":
        with pytest.raises(ValueError, match=message):
            inspect_p0_intake(payload)
        return
    result = inspect_p0_intake(payload)
    assert result["status"] == "invalid_input"
    assert result["invalid_dossier_count"] == 1
    assert any(message in str(item["error"]) for item in result["invalid_items"])


def test_markdown_and_cli_template_and_report_are_deterministic(tmp_path, capsys) -> None:
    template_path = tmp_path / "p0-intake-template.json"
    report_path = tmp_path / "p0-intake-report.md"
    input_path = tmp_path / "input.json"

    assert main(["--template-output", str(template_path)]) == 0
    template = json.loads(template_path.read_text(encoding="utf-8"))
    input_path.write_text(json.dumps(template, ensure_ascii=False), encoding="utf-8")
    assert main(
        [
            "--input",
            str(input_path),
            "--format",
            "markdown",
            "--output",
            str(report_path),
        ]
    ) == 0
    markdown = report_path.read_text(encoding="utf-8")
    assert "P0 Source Intake Readiness" in markdown
    assert "dossier_not_supplied" not in markdown
    assert "- Status: `deferred`" in markdown
    assert "p0_source_acceptance_pending" in markdown
    assert "P0 intake template written" in capsys.readouterr().out


def test_invalid_cli_input_returns_two_and_does_not_write_report(tmp_path) -> None:
    input_path = tmp_path / "invalid.json"
    report_path = tmp_path / "should-not-exist.json"
    input_path.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")

    assert main(["--input", str(input_path), "--output", str(report_path)]) == 2
    assert not report_path.exists()
