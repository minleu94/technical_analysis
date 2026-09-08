import json
import os
from pathlib import Path

from app_module.program_readiness_projection import (
    PROGRAM_READINESS_SCHEMA,
    load_program_readiness,
)
from ui_qt.views.update.update_formatters import (
    format_program_readiness_blockers,
    format_program_readiness_lane_progress,
    format_program_readiness_summary,
)


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


def test_older_explicit_readiness_artifact_is_marked_without_replacement(tmp_path: Path):
    readiness_path = tmp_path / "program-readiness.json"
    reference_path = tmp_path / "data-update-status.json"
    readiness_path.write_text(json.dumps(_payload()), encoding="utf-8")
    reference_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    os.utime(readiness_path, (100.0, 100.0))
    os.utime(reference_path, (200.0, 200.0))

    projected = load_program_readiness(
        readiness_path,
        freshness_reference_paths=(reference_path,),
    )

    assert projected["path"] == str(readiness_path.resolve())
    assert projected["status"] == "action_required"
    assert any(
        item == "program_readiness_artifact_older_than_reference:data-update-status.json"
        for item in projected["diagnostics"]
    )


def test_program_readiness_summary_keeps_status_and_boundary_visible(tmp_path: Path):
    path = tmp_path / "program-readiness.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    summary = format_program_readiness_summary(load_program_readiness(path))

    assert "整體狀態：需處理（action_required）" in summary
    assert "Readiness lane：2/7 個（已載入/預期）；阻擋原因：1 個；需外部輸入：1 個" in summary
    assert "writes_allowed=False" in summary
    assert "broker_order_allowed=False" in summary
    assert "source_acceptance_decision_missing" not in summary


def test_projection_keeps_bounded_lane_progress_without_nested_details(tmp_path: Path):
    payload = _payload()
    payload["workstreams"]["p0"]["details"] = {
        "source_count": 13,
        "accepted_count": 0,
        "limited_count": 0,
        "projection": {
            "machine_status_counts": {"verified": 1, "degraded": 12},
            "rows": [
                {
                    "route_probe_statuses": [
                        {"status": "observed"},
                        {"status": "not_attempted"},
                    ]
                }
            ],
            "details_that_must_not_leak": {"large": "payload"},
        },
    }
    payload["workstreams"]["evidence"] = {
        "status": "waiting_for_external_input",
        "blockers": ["insufficient_weekly_history_records"],
        "next_actions": ["等待真實週期"],
        "external_input_required": True,
        "details": {
            "readiness": {
                "formal_credit_authorized": False,
                "items": [
                    {
                        "item_id": "weekly_history",
                        "observed_count": 0,
                        "required_count": 3,
                        "evidence": {
                            "pending_collection_periods": [
                                {"period_start": "2026-08-17", "period_end": "2026-08-23"},
                                {"period_start": "2026-08-24", "period_end": "2026-08-28"},
                                {"details_that_must_not_leak": {"large": "payload"}},
                            ]
                        },
                    },
                    {
                        "item_id": "multi_day_dry_run",
                        "observed_count": 2,
                        "required_count": 3,
                    },
                ],
            }
        },
    }
    path = tmp_path / "program-readiness.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    projected = load_program_readiness(path)

    assert projected["workstreams"]["p0"]["metrics"] == {
        "source_count": 13,
        "accepted_count": 0,
        "limited_count": 0,
        "machine_verified_count": 1,
        "machine_degraded_count": 12,
        "route_count": 2,
        "route_attempted_count": 1,
        "route_not_attempted_count": 1,
        "route_observed_count": 1,
    }
    assert projected["workstreams"]["evidence"]["metrics"] == {
        "weekly_observed_count": 0,
        "weekly_required_count": 3,
        "weekly_pending_count": 3,
        "dry_run_observed_count": 2,
        "dry_run_required_count": 3,
        "formal_credit_authorized": False,
    }
    assert "details" not in projected["workstreams"]["p0"]
    assert "details_that_must_not_leak" not in json.dumps(projected)

    p0_progress = format_program_readiness_lane_progress(
        "p0", projected["workstreams"]["p0"]
    )
    assert "accepted 0／limited 0" in p0_progress
    assert "route 已嘗試 1/2" in p0_progress
    evidence_progress = format_program_readiness_lane_progress(
        "evidence", projected["workstreams"]["evidence"]
    )
    assert "weekly 0/3" in evidence_progress
    assert "待人工審核 3 期" in evidence_progress
    assert "dry-run 2/3" in evidence_progress
    assert "formal credit=未授權" in evidence_progress

    blockers = format_program_readiness_blockers(
        ["source_acceptance_decision_missing", "formal_input_source_missing:pit_sector_membership"]
    )
    assert "尚未提供來源接受決議（source_acceptance_decision_missing）" in blockers
    assert "Formal 來源資料缺件：pit_sector_membership" in blockers


def test_formal_progress_explains_evidence_states_without_named_reviewer_gate(
    tmp_path: Path,
):
    payload = _payload()
    payload["workstreams"]["formal_ml"] = {
        "status": "action_required",
        "blockers": [
            "formal_input_source_missing:causal_non_cash_portfolio_ledger",
            "formal_input_source_missing:formal_rule_champion_snapshot_history",
            "formal_input_machine_candidate:pit_sector_membership",
        ],
        "next_actions": ["補齊正式來源 evidence"],
        "external_input_required": True,
        "details": {
            "readiness": {
                "status": "waiting_for_formal_inputs",
                "ready_input_count": 0,
                "machine_verified_input_count": 1,
                "machine_candidate_input_count": 1,
                "formal_consumer_compatible_count": 0,
                "missing_input_count": 2,
                "unknown_input_count": 0,
                "invalid_input_count": 0,
                "input_count": 3,
                "ready_input_ratio": "0/3",
            }
        },
    }
    path = tmp_path / "program-readiness-formal.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    formal = load_program_readiness(path)["workstreams"]["formal_ml"]
    assert formal["metrics"] == {
        "ready_input_count": 0,
        "machine_verified_input_count": 1,
        "machine_candidate_input_count": 1,
        "formal_consumer_compatible_count": 0,
        "missing_input_count": 2,
        "unknown_input_count": 0,
        "invalid_input_count": 0,
        "input_count": 3,
        "ready_input_ratio": "0/3",
        "readiness_status": "waiting_for_formal_inputs",
    }
    progress = format_program_readiness_lane_progress("formal_ml", formal)
    assert "formal consumer verified 0/3" in progress
    assert "機器候選 1" in progress
    assert "來源缺件 2" in progress
    blockers = format_program_readiness_blockers(formal["blockers"])
    assert "Formal 來源資料缺件：causal_non_cash_portfolio_ledger" in blockers
    assert "Formal 僅有機器候選：pit_sector_membership" in blockers
    assert "具名" not in blockers


def test_projection_surfaces_performance_owner_packet_review_state(tmp_path: Path):
    payload = _payload()
    payload["workstreams"]["performance"] = {
        "status": "partial",
        "blockers": ["technical_production_single_writer_canary_not_completed"],
        "next_actions": ["等待 owner review"],
        "external_input_required": True,
        "details": {
            "owner_packet": {
                "status": "needs_named_owner_reviewer",
                "review_lane_count": 4,
                "pending_lane_count": 3,
                "observed_lane_count": 1,
                "candidate_only": True,
                "write_performed": False,
                "destructive_action_performed": False,
            },
            "artifacts": {
                "technical_canary": {"status": "confirmation_required"},
                "broker": {"status": "measured"},
                "ml_direct_chain": {"status": "blocked_insufficient_storage"},
            },
        },
    }
    path = tmp_path / "program-readiness.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    projected = load_program_readiness(path)
    performance = projected["workstreams"]["performance"]

    assert performance["metrics"] == {
        "owner_packet_status": "needs_named_owner_reviewer",
        "review_lane_count": 4,
        "pending_lane_count": 3,
        "observed_lane_count": 1,
        "candidate_only": True,
        "write_performed": False,
        "destructive_action_performed": False,
        "technical_canary_status": "confirmation_required",
        "broker_status": "measured",
        "ml_direct_chain_status": "blocked_insufficient_storage",
    }
    progress = format_program_readiness_lane_progress("performance", performance)
    assert "owner packet 待具名 owner／reviewer（needs_named_owner_reviewer）" in progress
    assert "owner review 待處理 3/4" in progress


def test_paper_progress_explains_missing_cost_ledger(tmp_path: Path):
    payload = _payload()
    payload["workstreams"]["paper"] = {
        "status": "partial",
        "blockers": ["paper_weekly_report_not_computable"],
        "next_actions": ["提供真實 fills"],
        "external_input_required": True,
        "details": {
            "readiness": {
                "snapshot_count": 21,
                "benchmark_observation_count": 21,
                "cost_record_count": 0,
                "filled_event_count": 0,
                "partial_fill_event_count": 0,
                "rejected_event_count": 0,
                "override_event_count": 0,
                "cost_ledger_status": "missing",
                "weekly_report_status": "not_computable_cost_ledger_missing",
            }
        },
    }
    path = tmp_path / "program-readiness.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    projected = load_program_readiness(path)
    progress = format_program_readiness_lane_progress(
        "paper", projected["workstreams"]["paper"]
    )

    assert "成本帳 缺漏（missing）" in progress
    assert "週報 尚不可計算（成本帳缺漏）（not_computable_cost_ledger_missing）" in progress
