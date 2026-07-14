import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from data_module.twse_t86_candidate_source import fetch_t86_envelope
from scripts.recover_twse_t86_candidate import resolve_completed_dates, run_pilot
from tests.test_twse_t86_candidate_normalizer import FIELDS, row


def test_cli_is_directly_executable():
    result = subprocess.run(
        [sys.executable, "scripts/recover_twse_t86_candidate.py", "--help"],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr


def make_db(path: Path):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE daily_prices (日期 TEXT, 證券代號 TEXT)")
        for day in range(1, 22):
            date_text = f"2026-06-{day:02d}"
            connection.executemany("INSERT INTO daily_prices VALUES (?, ?)", [(date_text, "2330"), (date_text, "2317")])


def test_resolves_and_freezes_latest_twenty_completed_dates(tmp_path: Path):
    db = tmp_path / "prices.db"
    make_db(db)
    dates = resolve_completed_dates(db, cutoff_date="2026-06-21")
    assert len(dates) == 20
    assert dates[0] == "2026-06-02"
    assert dates[-1] == "2026-06-21"


def test_resolves_compact_production_date_format(tmp_path: Path):
    db = tmp_path / "prices.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE daily_prices (日期 TEXT, 證券代號 TEXT)")
        connection.executemany("INSERT INTO daily_prices VALUES (?, '2330')", [(f"202606{day:02d}",) for day in range(1, 22)])
    dates = resolve_completed_dates(db, cutoff_date="2026-06-21")
    assert dates[0] == "2026-06-02"
    assert dates[-1] == "2026-06-21"


def test_pilot_reports_partial_failure_and_never_changes_source_db(tmp_path: Path):
    db = tmp_path / "prices.db"
    make_db(db)
    before = (sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns)
    body = json.dumps({"stat": "OK", "fields": FIELDS, "data": [row()]}, ensure_ascii=False).encode()

    class Response:
        status_code = 200
        content = body
        headers = {"Content-Type": "application/json"}

    def fake_fetch(day):
        if day.day == 10:
            raise RuntimeError("injected_failure")
        return fetch_t86_envelope(day, transport=lambda **_: Response(), sleep=lambda _: None, now=lambda: datetime(2026, 7, 13, 8, tzinfo=UTC))

    output = tmp_path / "development"
    manifest = run_pilot(db_path=db, development_output_root=output, cutoff_date="2026-06-21", fetcher=fake_fetch)
    assert manifest["source_status"] == "deferred"
    assert manifest["source_accepted"] is False
    assert manifest["formal_validation_allowed"] is False
    assert len(manifest["resolved_dates"]) == 20
    assert len(manifest["failed_dates"]) == 1
    assert manifest["coverage"][0]["missing_symbols"] == ["2317"]
    assert (sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns) == before
    assert (output / "manifest.json").exists()
    assert (output / "source_dossier.json").exists()
