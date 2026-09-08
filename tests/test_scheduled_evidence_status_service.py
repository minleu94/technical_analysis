from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app_module.scheduled_evidence_status_service import ScheduledEvidenceStatusService


class _Config:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root


def _write_minimal_scheduled_statuses(output_root: Path) -> None:
    for name in (
        "data_freshness",
        "recommendation_snapshot",
        "evidence_pipeline_dry_run",
    ):
        (output_root / "scheduled" / name).mkdir(parents=True, exist_ok=True)
    (output_root / "scheduled" / "data_freshness" / "latest_status.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "checked_at": "2026-09-07T05:00:00Z",
                "checks": {"daily_prices_latest_date": "20260907"},
            }
        ),
        encoding="utf-8",
    )
    (output_root / "scheduled" / "recommendation_snapshot" / "latest_status.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "checked_at": "2026-09-07T05:01:00Z",
                "decision_date": "2026-09-07",
                "result_id": "scheduled_rec_20260907_050100",
                "recommendations_count": 2,
                "writes_recommendation_result": True,
                "writes_evidence_db": False,
                "auto_trading": False,
                "lifecycle_action": False,
            }
        ),
        encoding="utf-8",
    )
    (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "pipeline_overall_status": "passed",
                "checked_at": "2026-09-07T05:02:00Z",
                "decision_date": "2026-09-07",
                "dry_run": True,
                "exit_code": 0,
                "writes_evidence_db": False,
                "confirm": False,
                "pipeline_blocking_gaps": [],
            }
        ),
        encoding="utf-8",
    )


def test_scheduled_status_has_unknown_state_before_first_observation(tmp_path: Path) -> None:
    service = ScheduledEvidenceStatusService(
        _Config(tmp_path / "output"),
        clock=lambda: datetime(2026, 9, 7, 5, 0, tzinfo=timezone.utc),
    )

    status = service.load_latest()

    assert status.load_state == "unknown"
    assert status.is_stale is False
    assert status.last_good_loaded_at is None
    assert status.machine_status_classification == "unknown"
    assert any(item.startswith("status_missing:") for item in status.diagnostics)


def test_scheduled_status_keeps_partial_initial_read_unknown(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    _write_minimal_scheduled_statuses(output_root)
    (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").unlink()
    service = ScheduledEvidenceStatusService(
        _Config(output_root),
        clock=lambda: datetime(2026, 9, 7, 5, 2, tzinfo=timezone.utc),
    )

    status = service.load_latest()

    assert status.load_state == "unknown"
    assert status.is_stale is False
    assert status.last_good_loaded_at is None
    assert status.machine_status_classification == "source_missing"
    assert "status_no_observation" not in status.diagnostics


def test_scheduled_status_preserves_last_known_good_when_latest_payload_breaks(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    _write_minimal_scheduled_statuses(output_root)
    clock_values = iter(
        (
            datetime(2026, 9, 7, 5, 3, tzinfo=timezone.utc),
            datetime(2026, 9, 7, 5, 4, tzinfo=timezone.utc),
            datetime(2026, 9, 7, 5, 5, tzinfo=timezone.utc),
        )
    )
    service = ScheduledEvidenceStatusService(_Config(output_root), clock=lambda: next(clock_values))

    first = service.load_latest()
    (output_root / "scheduled" / "recommendation_snapshot" / "latest_status.json").write_text(
        "{broken-json",
        encoding="utf-8",
    )
    stale = service.load_latest()

    assert first.load_state == "current"
    assert first.last_good_loaded_at == "2026-09-07T05:03:00+00:00"
    assert stale.load_state == "stale"
    assert stale.is_stale is True
    assert stale.last_good_loaded_at == first.last_good_loaded_at
    assert stale.recommendation_result_id == first.recommendation_result_id
    assert stale.machine_status_classification == "stale"
    assert "last_known_good_preserved" in stale.diagnostics
    assert any(item.startswith("status_unreadable:") for item in stale.diagnostics)


def test_scheduled_status_recovers_to_current_after_payload_is_repaired(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    _write_minimal_scheduled_statuses(output_root)
    clock_values = iter(
        (
            datetime(2026, 9, 7, 5, 6, tzinfo=timezone.utc),
            datetime(2026, 9, 7, 5, 7, tzinfo=timezone.utc),
            datetime(2026, 9, 7, 5, 8, tzinfo=timezone.utc),
        )
    )
    service = ScheduledEvidenceStatusService(_Config(output_root), clock=lambda: next(clock_values))

    first = service.load_latest()
    (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").unlink()
    stale = service.load_latest()
    _write_minimal_scheduled_statuses(output_root)
    recovered = service.load_latest()

    assert first.load_state == "current"
    assert stale.is_stale is True
    assert recovered.load_state == "current"
    assert recovered.is_stale is False
    assert recovered.last_good_loaded_at == "2026-09-07T05:08:00+00:00"


def test_scheduled_evidence_status_reads_latest_status_and_report(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    freshness_dir = output_root / "scheduled" / "data_freshness"
    dry_run_dir = output_root / "scheduled" / "evidence_pipeline_dry_run"
    recommendation_dir = output_root / "scheduled" / "recommendation_snapshot"
    report_dir = dry_run_dir / "reports"
    freshness_dir.mkdir(parents=True)
    recommendation_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    report_path = report_dir / "20260707_evidence_pipeline_dry_run.md"
    report_path.write_text(
        "# Evidence Pipeline Dry-run Report\n\n"
        "## Run Metadata\n"
        "- decision_date: 2026-07-07\n"
        "- dry_run: True\n"
        "- confirm: False\n",
        encoding="utf-8",
    )
    (freshness_dir / "latest_status.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "checked_at": "2026-07-07T05:00:01",
                "checks": {"daily_prices_latest_date": "20260707"},
                "warnings": [],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    (dry_run_dir / "latest_status.json").write_text(
        json.dumps(
            {
                "status": "degraded",
                "pipeline_overall_status": "degraded",
                "checked_at": "2026-07-07T05:15:39",
                "decision_date": "2026-07-07",
                "dry_run": True,
                "exit_code": 0,
                "report_path": str(report_path),
                "pipeline_blocking_gaps": [],
                "pipeline_warnings_count": 7,
                "pipeline_warning_unique_count": 2,
                "pipeline_advisories_count": 3,
                "pipeline_advisory_unique_count": 2,
                "pipeline_advisory_top_counts": [
                    {"advisory": "portfolio_alerts_chip_estimated:2330", "count": 1},
                ],
                "pipeline_warning_top_counts": [
                    {"warning": "risk_prompt_source_quality:portfolio_alerts:estimated", "count": 4},
                    {"warning": "relative_strength_liquidity_skipped_symbols:1", "count": 3},
                ],
                "source_coverage_warnings": ["screening_matrix_missing"],
                "writes_evidence_db": False,
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "20260706_evidence_pipeline_dry_run.md").write_text("older report", encoding="utf-8")
    (recommendation_dir / "latest_status.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "checked_at": "2026-07-07T05:10:01",
                "decision_date": "2026-07-07",
                "result_id": "scheduled_rec_20260707_051001",
                "recommendations_count": 12,
                "screening_matrix_rows": 200,
                "why_not_payload_rows": 188,
                "liquidity_gate_payload_rows": 9,
                "writes_recommendation_result": True,
                "writes_evidence_db": False,
                "auto_trading": False,
                "lifecycle_action": False,
                "confirm": False,
            }
        ),
        encoding="utf-8",
    )
    runs_dir = output_root / "recommendation" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "scheduled_rec_20260706_051001.json").write_text("{}", encoding="utf-8")
    (runs_dir / "scheduled_rec_20260707_051001.json").write_text("{}", encoding="utf-8")

    status = ScheduledEvidenceStatusService(_Config(output_root)).load_latest()

    assert status.freshness_status == "passed"
    assert status.latest_data_date == "20260707"
    assert status.evidence_status == "degraded"
    assert status.pipeline_overall_status == "degraded"
    assert status.recommendation_status == "passed"
    assert status.recommendation_result_id == "scheduled_rec_20260707_051001"
    assert status.recommendations_count == 12
    assert status.screening_matrix_rows == 200
    assert status.writes_recommendation_result is True
    assert status.auto_trading is False
    assert status.lifecycle_action is False
    assert status.recommendation_snapshot_observed_days == 2
    assert status.evidence_dry_run_observed_days == 2
    assert status.scheduled_joint_observed_days == 2
    assert status.scheduled_joint_observed_dates == ("20260706", "20260707")
    assert status.decision_date == "2026-07-07"
    assert status.report_path == report_path
    assert status.report_exists is True
    assert status.writes_evidence_db is False
    assert status.source_coverage_warnings == ("screening_matrix_missing",)
    assert getattr(status, "pipeline_warnings_count", None) == 7
    assert getattr(status, "pipeline_warning_unique_count", None) == 2
    assert getattr(status, "pipeline_advisories_count", None) == 3
    assert getattr(status, "pipeline_advisory_unique_count", None) == 2
    assert getattr(status, "pipeline_advisory_top_counts", ()) == (
        ("portfolio_alerts_chip_estimated:2330", 1),
    )
    assert getattr(status, "pipeline_warning_top_counts", ()) == (
        ("risk_prompt_source_quality:portfolio_alerts:estimated", 4),
        ("relative_strength_liquidity_skipped_symbols:1", 3),
    )
    assert "Run Metadata" in status.report_preview


def test_scheduled_evidence_status_uses_same_day_manual_recommendation_when_scheduled_status_missing(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    freshness_dir = output_root / "scheduled" / "data_freshness"
    dry_run_dir = output_root / "scheduled" / "evidence_pipeline_dry_run"
    runs_dir = output_root / "recommendation" / "runs"
    freshness_dir.mkdir(parents=True)
    dry_run_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)

    (freshness_dir / "latest_status.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "checked_at": "2026-07-07T05:00:01",
                "checks": {"daily_prices_latest_date": "20260707"},
                "warnings": [],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    (dry_run_dir / "latest_status.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "checked_at": "2026-07-07T05:15:39",
                "decision_date": "2026-07-07",
                "dry_run": True,
                "exit_code": 0,
                "pipeline_blocking_gaps": [],
                "writes_evidence_db": False,
                "confirm": False,
            }
        ),
        encoding="utf-8",
    )
    manual_path = runs_dir / "rec_20260707_113744.json"
    manual_path.write_text(
        json.dumps(
            {
                "result_id": "rec_20260707_113744",
                "created_at": "2026-07-07T11:37:44.761292",
                "recommendations": [{"stock_code": "1409"}, {"stock_code": "1466"}],
                "screening_matrix_json": [{"stock_code": "1409"}],
                "why_not_payload_json": [{"stock_code": "2330"}],
                "liquidity_gate_payload_json": [],
                "exclusion_quality": "observed",
                "exclusion_warnings_json": ["screening_matrix_persisted_v1"],
            }
        ),
        encoding="utf-8",
    )

    status = ScheduledEvidenceStatusService(_Config(output_root)).load_latest()

    assert status.recommendation_status == "manual_observed"
    assert status.recommendation_source == "manual_result"
    assert status.manual_recommendation_result_path == manual_path
    assert status.recommendation_result_id == "rec_20260707_113744"
    assert status.recommendation_checked_at == "2026-07-07T11:37:44.761292"
    assert status.recommendations_count == 2
    assert status.screening_matrix_rows == 1
    assert status.why_not_payload_rows == 1
    assert status.writes_recommendation_result is True
    assert status.writes_evidence_db is False
    assert status.confirm is False
    assert status.recommendation_snapshot_observed_days == 0
    assert status.manual_recommendation_observed_days == 1
    assert status.scheduled_joint_observed_days == 0
