from __future__ import annotations

import json
from pathlib import Path

from app_module.simulated_phase_progress_service import (
    SimulatedPhaseProgressService,
    render_simulated_phase_progress_markdown,
)
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.use_sqlite = True
    return config


def _write_replay_summary(
    path: Path,
    *,
    days: int = 3,
    events_seen: int = 12,
    outcomes_created: int = 4,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "replay_run_id": "hre_fixture_001",
        "replay_mode": "historical_replay",
        "source_label": "simulated_scheduler",
        "start_date": "2026-07-01",
        "end_date": "2026-07-03",
        "dry_run": False,
        "confirm": True,
        "outcome_mode": "final",
        "days": [
            {
                "decision_date": f"2026-07-{index + 1:02d}",
                "events_seen": events_seen // days,
                "events_inserted": events_seen // days,
                "outcomes_created": 0,
                "outcomes_updated": 0,
                "outcomes_pending": 0,
                "blocking_gaps": [],
                "diagnostics": [],
            }
            for index in range(days)
        ],
        "final_outcome_summary": {
            "outcomes_created": outcomes_created,
            "outcomes_updated": 0,
            "pending_insufficient_future_data": 1,
            "data_as_of_date": "2026-07-03",
        },
        "totals": {
            "days": days,
            "events_seen": events_seen,
            "events_inserted": events_seen,
            "outcomes_created": outcomes_created,
            "outcomes_updated": 0,
            "outcomes_pending": 1,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_scheduled_status(root: Path, *, decision_date: str = "2026-07-07") -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": "baldr-evidence-pipeline-dry-run-daily",
        "status": "passed",
        "dry_run": True,
        "writes_evidence_db": False,
        "decision_date": decision_date,
        "exit_code": 0,
        "pipeline_summary_available": True,
        "pipeline_warnings_count": 0,
        "pipeline_errors_count": 0,
        "pipeline_blocking_gaps": [],
        "pipeline_diagnostic_codes": [],
        "scheduler_readiness_after": "ready_for_manual_confirm",
    }
    (root / "latest_status.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_multi_day_record(path: Path, *, rows: int) -> None:
    lines = [
        "| Date | Data update status | Source coverage status | Dry-run pipeline status | Working-copy confirm smoke status | Events seen | Events inserted in working copy | Outcomes created in working copy | Summary groups | Warnings count | Blocking gaps | Dashboard review completed | Human reviewer notes | Decision |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|",
    ]
    for index in range(rows):
        lines.append(
            f"| 2026-07-{index + 2:02d} | passed | ready | passed | passed | 10 | 10 | 10 | 1 | 0 |  | yes | reviewed | continue dry-run |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def test_simulated_phase_report_marks_replay_and_keeps_official_gate_blocked(tmp_path: Path) -> None:
    config = _config(tmp_path)
    replay_summary = tmp_path / "replay.json"
    _write_replay_summary(replay_summary, days=3, events_seen=12, outcomes_created=4)
    scheduled_root = tmp_path / "output" / "scheduled" / "evidence_pipeline_dry_run"
    _write_scheduled_status(scheduled_root, decision_date="2026-07-07")
    record_path = tmp_path / "multi-day.md"
    _write_multi_day_record(record_path, rows=1)

    report = SimulatedPhaseProgressService(config, evidence_db_path=tmp_path / "missing.db").build_report(
        decision_date="2026-07-07",
        replay_summary_path=replay_summary,
        scheduled_output_root=scheduled_root,
        multi_day_record_path=record_path,
    )

    assert report.production_scheduler_allowed is False
    assert report.official_phase_5_status == "blocked"
    assert report.replay_tags.official_gate_credit is False
    assert report.replay_tags.requires_real_world_validation is True
    assert report.replay_tags.replay_mode == "historical_replay"
    assert report.replay_tags.source_label == "simulated_scheduler"
    assert report.replay_tags.replay_run_id == "hre_fixture_001"
    assert report.replay_tags.replay_decision_dates == ("2026-07-01", "2026-07-02", "2026-07-03")
    assert report.replay_tags.replay_data_as_of_dates == ("2026-07-01", "2026-07-02", "2026-07-03")
    assert {item.phase_id for item in report.items} == {
        "phase_0",
        "phase_1",
        "phase_2",
        "phase_3",
        "phase_4",
        "phase_5",
    }
    assert report.items[-1].simulated_status == "simulated_ready"
    assert report.items[-1].official_status == "official_gate_not_satisfied"


def test_simulated_phase_markdown_excludes_forbidden_runtime_terms(tmp_path: Path) -> None:
    config = _config(tmp_path)
    replay_summary = tmp_path / "replay.json"
    _write_replay_summary(replay_summary, days=1, events_seen=2, outcomes_created=0)
    scheduled_root = tmp_path / "output" / "scheduled" / "evidence_pipeline_dry_run"
    _write_scheduled_status(scheduled_root)

    report = SimulatedPhaseProgressService(config, evidence_db_path=tmp_path / "missing.db").build_report(
        decision_date="2026-07-07",
        replay_summary_path=replay_summary,
        scheduled_output_root=scheduled_root,
    )
    markdown = render_simulated_phase_progress_markdown(report)

    assert "official_gate_credit: `false`" in markdown
    assert "requires_real_world_validation: `true`" in markdown
    forbidden_terms = ("official_ready", "phase_complete", "scheduler_approved", "production_ready")
    assert all(term not in markdown for term in forbidden_terms)
