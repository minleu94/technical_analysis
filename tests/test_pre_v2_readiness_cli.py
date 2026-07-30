from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _empty_record(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "| Date | Data update status | Source coverage status | Dry-run pipeline status | Working-copy confirm smoke status | Events seen | Events inserted in working copy | Outcomes created in working copy | Summary groups | Warnings count | Blocking gaps | Dashboard review completed | Human reviewer notes | Decision |",
                "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|",
            ]
        ),
        encoding="utf-8",
    )


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/inspect_pre_v2_readiness.py",
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


def test_pre_v2_readiness_cli_reports_json_without_creating_missing_db(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing" / "evidence.db"
    record_path = tmp_path / "multi-day.md"
    _empty_record(record_path)

    result = _run_cli(
        tmp_path,
        "--db-path",
        str(missing_db),
        "--decision-date",
        "2026-07-06",
        "--multi-day-record-path",
        str(record_path),
        "--json-output",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["overall_status"] == "action_required"
    assert payload["production_scheduler_allowed"] is False
    assert payload["rule_operational_scheduler_allowed"] is True
    assert payload["required_human_action"] is False
    assert payload["blocking_scope"] == "formal_evidence_credit_only"
    assert any(item["item_id"] == "weekly_history" for item in payload["items"])
    assert not missing_db.exists()


def test_pre_v2_readiness_cli_can_emit_markdown_report_file(tmp_path: Path) -> None:
    record_path = tmp_path / "multi-day.md"
    report_path = tmp_path / "pre-v2.md"
    _empty_record(record_path)

    result = _run_cli(
        tmp_path,
        "--db-path",
        str(tmp_path / "missing.db"),
        "--multi-day-record-path",
        str(record_path),
        "--markdown",
        "--report-output",
        str(report_path),
    )

    assert result.returncode == 0
    assert "# Pre-V2 Readiness Report" in result.stdout
    assert "V2.0" in report_path.read_text(encoding="utf-8")
