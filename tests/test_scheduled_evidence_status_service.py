from __future__ import annotations

import json
from pathlib import Path

from app_module.scheduled_evidence_status_service import ScheduledEvidenceStatusService


class _Config:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root


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
                "status": "passed",
                "checked_at": "2026-07-07T05:15:39",
                "decision_date": "2026-07-07",
                "dry_run": True,
                "exit_code": 0,
                "report_path": str(report_path),
                "pipeline_blocking_gaps": [],
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
    assert status.evidence_status == "passed"
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
