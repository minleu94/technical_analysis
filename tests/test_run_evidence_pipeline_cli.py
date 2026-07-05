from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys

from scripts import run_evidence_pipeline
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


def test_cli_stdout_survives_cp1252_console_with_chinese_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class DummySummary:
        def to_dict(self) -> dict[str, object]:
            return {"diagnostics": ["持倉警示"], "dry_run": True}

    class DummyRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def run(self, request: object) -> DummySummary:
            return DummySummary()

    output_buffer = io.BytesIO()
    stdout = io.TextIOWrapper(output_buffer, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(run_evidence_pipeline, "EvidencePipelineRunner", DummyRunner)

    exit_code = run_evidence_pipeline.main(
        [
            "--decision-date",
            "2026-07-04",
            "--db-path",
            str(tmp_path / "twstock.db"),
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(tmp_path / "output"),
            "--dry-run",
        ]
    )

    stdout.flush()
    raw_output = output_buffer.getvalue().decode("cp1252")
    payload = json.loads(raw_output)
    assert exit_code == 0
    assert payload["diagnostics"] == ["持倉警示"]
    assert "\\u6301\\u5009\\u8b66\\u793a" in raw_output
