from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect_v2_2_weekly_evidence.py"


def _create_source_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE daily_prices (日期 TEXT NOT NULL, 證券代號 TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO daily_prices (日期, 證券代號) VALUES (?, ?)",
            [("20260709", "2330"), ("20260710", "2330"), ("20260713", "2330")],
        )


def test_collect_cli_saves_pending_sidecar_record_and_reports(
    tmp_path: Path,
) -> None:
    source_db_path = tmp_path / "twstock.db"
    sidecar_db_path = tmp_path / "weekly-collection-sidecar.sqlite"
    output_root = tmp_path / "output"
    _create_source_database(source_db_path)
    source_bytes_before = source_db_path.read_bytes()

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-db-path",
            str(source_db_path),
            "--sidecar-db-path",
            str(sidecar_db_path),
            "--output-root",
            str(output_root),
            "--period-end",
            "2026-07-12",
            "--json-output",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["collection_status"] == "pending_human_review"
    assert payload["storage_status"] == "pending_human_review"
    assert payload["human_approval_required"] is True
    assert payload["automatic_revalidation"] is False
    assert payload["gate_credit_status"] == "pending_human_review"
    assert payload["write_intent"] is False
    assert payload["last_trading_date"] == "2026-07-10"
    assert source_db_path.read_bytes() == source_bytes_before
    with sqlite3.connect(sidecar_db_path) as connection:
        stored_statuses = connection.execute(
            "SELECT DISTINCT status FROM evidence_weekly_collections"
        ).fetchall()
        schema_version = connection.execute(
            "SELECT version FROM sidecar_schema_version"
        ).fetchall()
    assert stored_statuses == [("pending_human_review",)]
    assert schema_version == [(3,)]

    report_directory = output_root / "scheduled" / "v2_2_weekly_collection"
    json_reports = list(report_directory.glob("*.json"))
    markdown_reports = list(report_directory.glob("*.md"))
    assert len(json_reports) == 1
    assert len(markdown_reports) == 1
    assert (
        json.loads(json_reports[0].read_text(encoding="utf-8"))[
            "collection_status"
        ]
        == "pending_human_review"
    )
    markdown = markdown_reports[0].read_text(encoding="utf-8")
    assert "pending_human_review" in markdown
    assert "Human approval required: `true`" in markdown
    assert "Write intent: `false`" in markdown


def test_collect_cli_saves_failed_sidecar_record_for_invalid_period_end(tmp_path: Path) -> None:
    source_db_path = tmp_path / "twstock.db"
    sidecar_db_path = tmp_path / "weekly-collection-sidecar.sqlite"
    _create_source_database(source_db_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-db-path",
            str(source_db_path),
            "--sidecar-db-path",
            str(sidecar_db_path),
            "--output-root",
            str(tmp_path / "output"),
            "--period-end",
            "not-a-date",
            "--json-output",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["collection_status"] == "collection_failed"
    assert payload["error"]["type"] == "ValueError"
    with sqlite3.connect(sidecar_db_path) as connection:
        row = connection.execute(
            "SELECT status, error_type, error_message FROM evidence_weekly_collections"
        ).fetchone()
    assert row == ("collection_failed", "ValueError", "Invalid isoformat string: 'not-a-date'")


def test_collect_cli_replaces_pending_with_failed_record_when_report_output_is_unwritable(tmp_path: Path) -> None:
    source_db_path = tmp_path / "twstock.db"
    sidecar_db_path = tmp_path / "weekly-collection-sidecar.sqlite"
    output_root = tmp_path / "output-root-file"
    _create_source_database(source_db_path)
    output_root.write_text("not a directory", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-db-path",
            str(source_db_path),
            "--sidecar-db-path",
            str(sidecar_db_path),
            "--output-root",
            str(output_root),
            "--period-end",
            "2026-07-12",
            "--json-output",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["collection_status"] == "collection_failed"
    assert payload["error"]["type"] == "FileExistsError"
    assert payload["error"]["message"]
    with sqlite3.connect(sidecar_db_path) as connection:
        rows = connection.execute(
            "SELECT status, error_type, error_message FROM evidence_weekly_collections"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "collection_failed"
    assert rows[0][1] == "FileExistsError"
    assert rows[0][2]
