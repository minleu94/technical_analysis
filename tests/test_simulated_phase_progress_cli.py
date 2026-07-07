from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_replay_summary(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "replay_run_id": "hre_cli_fixture",
        "replay_mode": "historical_replay",
        "source_label": "simulated_scheduler",
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
        "dry_run": False,
        "confirm": True,
        "days": [
            {
                "decision_date": "2026-07-01",
                "events_seen": 5,
                "events_inserted": 5,
                "outcomes_created": 0,
                "outcomes_updated": 0,
                "outcomes_pending": 0,
                "blocking_gaps": [],
                "diagnostics": [],
            },
            {
                "decision_date": "2026-07-02",
                "events_seen": 5,
                "events_inserted": 5,
                "outcomes_created": 0,
                "outcomes_updated": 0,
                "outcomes_pending": 0,
                "blocking_gaps": [],
                "diagnostics": [],
            },
        ],
        "final_outcome_summary": {
            "outcomes_created": 3,
            "outcomes_updated": 0,
            "pending_insufficient_future_data": 0,
            "data_as_of_date": "2026-07-02",
        },
        "totals": {
            "days": 2,
            "events_seen": 10,
            "events_inserted": 10,
            "outcomes_created": 3,
            "outcomes_updated": 0,
            "outcomes_pending": 0,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_scheduled_status(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": "baldr-evidence-pipeline-dry-run-daily",
        "status": "passed",
        "dry_run": True,
        "writes_evidence_db": False,
        "decision_date": "2026-07-07",
        "pipeline_summary_available": True,
        "pipeline_warnings_count": 0,
        "pipeline_errors_count": 0,
        "pipeline_blocking_gaps": [],
        "pipeline_diagnostic_codes": [],
        "scheduler_readiness_after": "ready_for_manual_confirm",
    }
    (root / "latest_status.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/inspect_simulated_phase_progress.py",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(tmp_path / "output"),
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_simulated_phase_progress_cli_emits_json_without_creating_missing_db(tmp_path: Path) -> None:
    replay_summary = tmp_path / "replay.json"
    _write_replay_summary(replay_summary)
    scheduled_root = tmp_path / "output" / "scheduled" / "evidence_pipeline_dry_run"
    _write_scheduled_status(scheduled_root)
    missing_db = tmp_path / "missing" / "evidence.db"

    result = _run_cli(
        tmp_path,
        "--db-path",
        str(missing_db),
        "--replay-summary-path",
        str(replay_summary),
        "--scheduled-output-root",
        str(scheduled_root),
        "--decision-date",
        "2026-07-07",
        "--json-output",
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["production_scheduler_allowed"] is False
    assert payload["official_phase_5_status"] == "blocked"
    assert payload["replay_tags"]["official_gate_credit"] is False
    assert payload["replay_tags"]["requires_real_world_validation"] is True
    assert payload["scheduled_dry_run_summary"]["manual_record_credit"] is False
    assert not missing_db.exists()


def test_simulated_phase_progress_cli_can_emit_markdown_report_file(tmp_path: Path) -> None:
    replay_summary = tmp_path / "replay.json"
    _write_replay_summary(replay_summary)
    scheduled_root = tmp_path / "output" / "scheduled" / "evidence_pipeline_dry_run"
    _write_scheduled_status(scheduled_root)
    report_path = tmp_path / "simulated-phase-progress.md"

    result = _run_cli(
        tmp_path,
        "--db-path",
        str(tmp_path / "missing.db"),
        "--replay-summary-path",
        str(replay_summary),
        "--scheduled-output-root",
        str(scheduled_root),
        "--markdown",
        "--report-output",
        str(report_path),
    )

    report_text = report_path.read_text(encoding="utf-8")
    assert result.returncode == 0
    assert "# V2.2 Simulated Phase Progress" in result.stdout
    assert "official_gate_credit: `false`" in report_text
    assert "requires_real_world_validation: `true`" in report_text
