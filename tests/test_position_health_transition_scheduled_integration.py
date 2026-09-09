from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import subprocess

from scripts.scheduled import run_scheduled_evidence_pipeline_dry_run


def test_scheduled_wrapper_wires_transition_evaluation_to_isolated_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    paper_operation_root = tmp_path / "paper-operation"
    health_path = output_root / "position_health" / "latest.json"
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True)
    freshness_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeHealthRefresh:
        def __init__(self, **kwargs: object) -> None:
            captured["health_init"] = kwargs

        def refresh(self, **kwargs: object) -> dict[str, object]:
            captured["health_refresh"] = kwargs
            health_path.parent.mkdir(parents=True, exist_ok=True)
            health_path.write_text(
                json.dumps(
                    {
                        "as_of_date": "2026-09-08",
                        "source_snapshot_id": "snapshot-1",
                        "source_snapshot_rows_sha256": "sha256:rows",
                        "positions": [],
                    }
                ),
                encoding="utf-8",
            )
            return {
                "status": "passed",
                "latest_path": str(health_path),
                "baseline_path": str(health_path),
                "blockers": [],
                "warnings": [],
            }

    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "PositionHealthDailyRefreshService",
        FakeHealthRefresh,
    )
    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "scheduled_now",
        lambda: datetime(2026, 9, 8, 5, 15, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    def fake_transition_evaluation(**kwargs: object) -> dict[str, object]:
        captured["transition_evaluation"] = kwargs
        return {
            "status": "degraded",
            "blockers": [],
            "warnings": ["thesis_contract_missing"],
            "positions": [],
        }

    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "evaluate_baseline_file",
        fake_transition_evaluation,
    )
    pipeline_summary = {
        "overall_status": "ready",
        "warnings_count": 0,
        "warning_counts": {},
        "errors_count": 0,
        "blocking_gaps": [],
        "source_coverage": {},
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(pipeline_summary),
        ),
    )

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--refresh-paper-health",
            "--evaluate-position-health-transition",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(tmp_path / "data" / "sqlite" / "twstock.db"),
            "--paper-evidence-operation-root",
            str(paper_operation_root),
        ]
    )

    status_path = output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    transition_call = captured["transition_evaluation"]

    assert exit_code == 0
    assert isinstance(transition_call, dict)
    assert transition_call["baseline_path"] == health_path
    assert transition_call["output_dir"] == output_root / "position_health_transition"
    assert transition_call["transition_repository_path"] == (
        output_root / "position_health_transition" / "position_health_transitions.sqlite"
    )
    assert payload["status"] == "degraded"
    assert payload["position_health_transition_status"] == "degraded"
    assert payload["position_health_transition_output"] == str(
        output_root / "position_health_transition"
    )
    assert payload["manual_action_required"] is True
