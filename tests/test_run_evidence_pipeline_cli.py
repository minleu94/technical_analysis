from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tests.test_evidence_pipeline_runner import _config, _seed_recommendation
from tests.test_evidence_pipeline_smoke import _seed_market_db


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/run_evidence_pipeline.py", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_cli_defaults_to_dry_run(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)

    completed = _run(
        "--decision-date",
        "2026-07-01",
        "--db-path",
        str(config.db_file),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--result-id",
        result_id,
        "--windows",
        "5",
        "--json-output",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True
    assert payload["events_inserted"] == 0
    assert payload["outcomes_created"] == 0


def test_cli_rejects_confirm_without_db_path() -> None:
    completed = _run("--decision-date", "2026-07-01", "--confirm")

    assert completed.returncode != 0
    assert "explicit --db-path" in completed.stderr


def test_cli_rejects_dry_run_and_confirm_together(tmp_path: Path) -> None:
    config = _config(tmp_path)

    completed = _run(
        "--decision-date",
        "2026-07-01",
        "--db-path",
        str(config.db_file),
        "--dry-run",
        "--confirm",
    )

    assert completed.returncode != 0
    assert "mutually exclusive" in completed.stderr


def test_cli_writes_markdown_report_to_requested_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)
    report_path = tmp_path / "runner-report.md"

    completed = _run(
        "--decision-date",
        "2026-07-01",
        "--db-path",
        str(config.db_file),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--result-id",
        result_id,
        "--windows",
        "5",
        "--report-output",
        str(report_path),
        "--json-output",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["report_output"] == str(report_path)
    assert report_path.exists()
    assert "Scheduler Readiness" in report_path.read_text(encoding="utf-8")
