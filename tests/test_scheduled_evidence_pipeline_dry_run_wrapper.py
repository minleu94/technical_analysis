from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

from scripts.scheduled import run_scheduled_evidence_pipeline_dry_run


def test_scheduled_wrapper_stdout_survives_cp1252_console_with_chinese_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "輸出"
    db_path = tmp_path / "資料" / "sqlite" / "twstock.db"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="pipeline ok\n")

    output_buffer = io.BytesIO()
    stdout = io.TextIOWrapper(output_buffer, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(subprocess, "run", fake_run)

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--data-root",
            str(tmp_path / "資料"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
            "--sources",
            "all",
        ]
    )

    stdout.flush()
    raw_output = output_buffer.getvalue().decode("cp1252")
    payload = json.loads(raw_output)
    assert exit_code == 0
    assert payload["db_path"] == str(db_path)
    assert "輸出" in payload["report_path"]
    assert "\\u8f38\\u51fa" in raw_output
    assert (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").exists()


def test_scheduled_wrapper_persists_pipeline_source_coverage_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    db_path = tmp_path / "data" / "sqlite" / "twstock.db"
    pipeline_summary = {
        "warnings_count": 3,
        "errors_count": 0,
        "blocking_gaps": [],
        "diagnostic_codes": ["source_missing_screening_matrix"],
        "scheduler_readiness_before": "dry_run_only",
        "scheduler_readiness_after": "ready_for_manual_confirm",
        "source_coverage": {
            "warnings": ["screening_matrix_missing"],
            "blocking_gaps": [],
            "recommendation_screening_matrix_available": False,
            "recommendation_exclusion_payload_available": True,
            "source_coverage_basis": "dry_run_transient_decision_desk_snapshot",
        },
    }

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        stdout = "config log before json\n" + json.dumps(pipeline_summary)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
            "--sources",
            "all",
        ]
    )

    status_path = output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["pipeline_summary_available"] is True
    assert payload["pipeline_diagnostic_codes"] == ["source_missing_screening_matrix"]
    assert payload["source_coverage_warnings"] == ["screening_matrix_missing"]
    assert payload["recommendation_screening_matrix_available"] is False
    assert payload["recommendation_exclusion_payload_available"] is True
    assert payload["source_coverage_basis"] == "dry_run_transient_decision_desk_snapshot"
