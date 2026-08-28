import json
from pathlib import Path

from app_module.program_readiness_projection import (
    PROGRAM_READINESS_SCHEMA,
    load_program_readiness,
)
from ui_qt.views.update.update_formatters import format_program_readiness_summary


def _payload() -> dict:
    return {
        "schema_version": PROGRAM_READINESS_SCHEMA,
        "status": "action_required",
        "generated_at": "2026-08-28T20:56:20+08:00",
        "boundary": {
            "read_only": True,
            "writes_allowed": False,
            "broker_order_allowed": False,
            "formal_oos_allowed": False,
            "production_scheduler_allowed": False,
        },
        "workstreams": {
            "p0": {
                "status": "action_required",
                "blockers": ["source_acceptance_decision_missing"],
                "next_actions": ["完成 owner review"],
                "external_input_required": True,
                "details": {"must_not_leak": "large nested details"},
            },
            "runtime": {
                "status": "ready",
                "blockers": [],
                "next_actions": ["維持觀察"],
                "external_input_required": False,
            },
        },
    }


def test_missing_program_readiness_artifact_is_visible_and_fail_closed(tmp_path: Path):
    payload = load_program_readiness(tmp_path / "missing.json")

    assert payload["status"] == "missing"
    assert payload["read_only"] is True
    assert payload["writes_allowed"] is False
    assert payload["workstreams"] == {}
    assert "program_readiness_artifact_missing" in payload["diagnostics"][0]


def test_valid_program_readiness_projects_only_bounded_lane_fields(tmp_path: Path):
    path = tmp_path / "program-readiness.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    projected = load_program_readiness(path)

    assert projected["status"] == "action_required"
    assert projected["generated_at"] == "2026-08-28T20:56:20+08:00"
    assert projected["workstreams"]["p0"] == {
        "status": "action_required",
        "blockers": ["source_acceptance_decision_missing"],
        "next_actions": ["完成 owner review"],
        "external_input_required": True,
    }
    assert "details" not in projected["workstreams"]["p0"]
    assert projected["boundary"]["production_scheduler_allowed"] is False
    assert projected["read_only"] is True
    assert projected["writes_allowed"] is False


def test_unsupported_program_readiness_schema_is_invalid(tmp_path: Path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"schema_version": "other.v1"}), encoding="utf-8")

    projected = load_program_readiness(path)

    assert projected["status"] == "invalid"
    assert "program_readiness_schema_unsupported" in projected["diagnostics"][0]
    assert projected["writes_allowed"] is False


def test_program_readiness_summary_keeps_status_and_boundary_visible(tmp_path: Path):
    path = tmp_path / "program-readiness.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    summary = format_program_readiness_summary(load_program_readiness(path))

    assert "整體狀態：需處理（action_required）" in summary
    assert "Readiness lane：2 個；阻擋原因：1 個；需外部輸入：1 個" in summary
    assert "writes_allowed=False" in summary
    assert "broker_order_allowed=False" in summary
    assert "source_acceptance_decision_missing" not in summary
