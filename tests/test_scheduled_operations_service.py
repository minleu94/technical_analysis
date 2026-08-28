import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app_module.runtime_services.scheduled_operations_service import (
    ScheduledOperationsStatusService,
)


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _write_status(root: Path, job_id: str, payload: dict[str, object]) -> Path:
    path = root / job_id / "latest_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    timestamp = NOW.timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def _expected_evidence_payload() -> dict[str, object]:
    return {
        "status": "degraded",
        "checked_at": "2026-08-06T11:55:00+00:00",
        "natural_maturity_only": True,
        "manual_action_required": False,
        "pipeline_summary_available": True,
        "freshness_status": "passed",
        "pipeline_errors_count": 0,
        "pipeline_actionable_warning_count": 0,
        "pipeline_blocking_gaps": [],
        "source_coverage_blocking_gaps": [],
        "pipeline_diagnostic_codes": [],
    }


def test_snapshot_distinguishes_operational_core_from_guarded_safety_boundaries(tmp_path):
    root = tmp_path / "scheduled"
    for job_id in (
        "data_update_quick",
        "data_freshness",
        "recommendation_snapshot",
        "decision_evidence_capture",
        "paper_portfolio_daily",
    ):
        _write_status(root, job_id, {"status": "passed", "checked_at": NOW.isoformat()})
    _write_status(root, "evidence_pipeline_dry_run", _expected_evidence_payload())
    _write_status(
        root,
        "ml_allocation_copilot",
        {"status": "passed_rule_only", "decision_at": "2026-08-07T08:30:00+08:00"},
    )
    _write_status(root, "ml_promotion_evidence", {"status": "blocked"})
    _write_status(
        root,
        "ml_direct_chain_maintenance",
        {"status": "blocked_insufficient_storage"},
    )

    snapshot = ScheduledOperationsStatusService(root, now_provider=lambda: NOW).get_snapshot()
    operations = {operation.job_id: operation for operation in snapshot.operations}

    assert snapshot.overall_state == "operational"
    assert snapshot.core_ready_count == 6
    assert operations["evidence_pipeline_dry_run"].state == "guarded"
    assert operations["ml_allocation_copilot"].state == "guarded"
    assert operations["ml_allocation_copilot"].observed_at_source == "file_mtime"
    assert operations["ml_allocation_copilot"].updated_at == NOW
    assert operations["ml_promotion_evidence"].state == "guarded"
    assert operations["ml_direct_chain_maintenance"].label == "ML Direct/OOC 維護"
    assert operations["ml_direct_chain_maintenance"].state == "attention"
    assert operations["ml_direct_chain_maintenance"].diagnostic == (
        "direct_chain_storage_preflight_blocked"
    )


def test_evidence_degraded_fails_closed_without_complete_natural_maturity_proof(tmp_path):
    root = tmp_path / "scheduled"
    payload = _expected_evidence_payload()
    payload.pop("freshness_status")
    _write_status(root, "evidence_pipeline_dry_run", payload)

    snapshot = ScheduledOperationsStatusService(root, now_provider=lambda: NOW).get_snapshot()
    operation = next(
        item for item in snapshot.operations if item.job_id == "evidence_pipeline_dry_run"
    )

    assert operation.state == "attention"
    assert operation.diagnostic == "evidence_pipeline_degradation_requires_review"
    assert snapshot.overall_state == "attention"


def test_missing_or_stale_core_status_is_attention_not_success(tmp_path):
    root = tmp_path / "scheduled"
    old_payload = {"status": "passed", "checked_at": "2026-08-01T00:00:00+00:00"}
    _write_status(root, "data_update_quick", old_payload)

    snapshot = ScheduledOperationsStatusService(root, now_provider=lambda: NOW).get_snapshot()
    operations = {operation.job_id: operation for operation in snapshot.operations}

    assert operations["data_update_quick"].state == "attention"
    assert "latest_status_stale" in operations["data_update_quick"].diagnostic
    assert operations["data_freshness"].state == "attention"
    assert operations["data_freshness"].read_state == "missing"
    assert snapshot.overall_state == "attention"


def test_unavailable_snapshot_is_fail_closed_for_all_core_operations(tmp_path):
    snapshot = ScheduledOperationsStatusService(
        tmp_path,
        now_provider=lambda: NOW,
    ).build_unavailable_snapshot(
        "scheduled_operations_read_failed:OSError"
    )

    assert snapshot.overall_state == "attention"
    assert snapshot.observed_at == NOW
    assert snapshot.core_ready_count == 0
    assert snapshot.core_job_count == 6
    assert all(
        operation.state == "attention"
        for operation in snapshot.operations
        if operation.lane == "core"
    )
    assert all(
        operation.read_state == "service_error" for operation in snapshot.operations
    )


def test_future_checked_timestamp_falls_back_to_file_mtime_instead_of_hiding_staleness(tmp_path):
    root = tmp_path / "scheduled"
    _write_status(
        root,
        "data_update_quick",
        {"status": "passed", "checked_at": "2026-08-07T12:00:00+00:00"},
    )

    snapshot = ScheduledOperationsStatusService(root, now_provider=lambda: NOW).get_snapshot()
    operation = next(item for item in snapshot.operations if item.job_id == "data_update_quick")

    assert operation.updated_at == NOW
    assert operation.observed_at_source == "file_mtime"
    assert "future_status_timestamp:checked_at" in operation.diagnostic


def test_known_completed_and_non_trading_day_safety_statuses_are_not_reported_as_failures(
    tmp_path,
):
    root = tmp_path / "scheduled"
    _write_status(
        root,
        "ml_raw_pit_refresh",
        {"status": "completed", "completed_at": NOW.isoformat()},
    )
    _write_status(
        root,
        "ml_allocation_copilot",
        {"status": "skipped_non_trading_day"},
    )

    snapshot = ScheduledOperationsStatusService(root, now_provider=lambda: NOW).get_snapshot()
    operations = {operation.job_id: operation for operation in snapshot.operations}

    assert operations["ml_raw_pit_refresh"].state == "operational"
    assert operations["ml_raw_pit_refresh"].diagnostic == ""
    assert operations["ml_allocation_copilot"].state == "guarded"
    assert operations["ml_allocation_copilot"].diagnostic == "non_trading_day_noop"


def test_failed_safety_job_keeps_specific_failure_diagnostic(tmp_path):
    root = tmp_path / "scheduled"
    _write_status(root, "ml_direct_chain_maintenance", {"status": "failed"})

    snapshot = ScheduledOperationsStatusService(root, now_provider=lambda: NOW).get_snapshot()
    operation = next(
        item for item in snapshot.operations if item.job_id == "ml_direct_chain_maintenance"
    )

    assert operation.state == "attention"
    assert operation.diagnostic == "scheduled_job_failed"
