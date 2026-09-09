from __future__ import annotations

import csv
import json
import sqlite3

import pytest

from scripts.apply_tdcc_shareholding_candidate import CONFIRM_TOKEN, _verified_sqlite_backup, review_or_apply


def _candidate(path, *, symbol: str = "2330", tier_json: str | None = None) -> None:
    fields = [
        "stock_code", "decision_date", "source_version", "publication_at", "first_observed_at",
        "observed_at", "available_at", "available_date", "quality", "shareholding_tiers",
        "large_holder_ratio_bp", "retail_holder_ratio_bp", "dispersion_index_bp",
    ]
    tier_json = tier_json or json.dumps([{"tier": n} for n in range(1, 18)])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "stock_code": symbol, "decision_date": "2026-09-04", "source_version": "tdcc-official-od-1-5",
            "publication_at": "", "first_observed_at": "2026-09-09T05:03:00Z", "observed_at": "2026-09-09T05:03:00Z",
            "available_at": "2026-09-09T05:03:00Z", "available_date": "2026-09-10", "quality": "degraded",
            "shareholding_tiers": tier_json, "large_holder_ratio_bp": "6200", "retail_holder_ratio_bp": "1800",
            "dispersion_index_bp": "-4400",
        })


def _db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE tdcc_shareholding (
            stock_code TEXT, decision_date TEXT, available_date TEXT, source_version TEXT,
            quality TEXT, shareholding_tiers TEXT, large_holder_ratio_bp INTEGER,
            retail_holder_ratio_bp INTEGER, dispersion_index_bp INTEGER,
            PRIMARY KEY (stock_code, decision_date))""")


def test_dry_run_does_not_write(tmp_path) -> None:
    candidate = tmp_path / "candidate.csv"
    db = tmp_path / "target.sqlite"
    _candidate(candidate)
    _db(db)
    report = review_or_apply(candidate, db)
    assert report.dry_run is True
    assert report.added == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tdcc_shareholding").fetchone()[0] == 0


def test_apply_requires_backup_and_confirmation(tmp_path) -> None:
    candidate = tmp_path / "candidate.csv"
    db = tmp_path / "target.sqlite"
    _candidate(candidate)
    _db(db)
    with pytest.raises(PermissionError):
        review_or_apply(candidate, db, apply=True, confirm="wrong", backup_db=tmp_path / "backup.sqlite")
    with pytest.raises(ValueError, match="backup"):
        review_or_apply(candidate, db, apply=True, confirm=CONFIRM_TOKEN)


def test_apply_writes_after_backup_and_is_idempotent(tmp_path) -> None:
    candidate = tmp_path / "candidate.csv"
    db = tmp_path / "target.sqlite"
    backup = tmp_path / "backup.sqlite"
    _candidate(candidate)
    _db(db)
    first = review_or_apply(candidate, db, apply=True, confirm=CONFIRM_TOKEN, backup_db=backup)
    recaptured = tmp_path / "recaptured.csv"
    recaptured.write_text(
        candidate.read_text(encoding="utf-8-sig").replace("2026-09-09T05:03:00Z", "2026-09-10T05:03:00Z"),
        encoding="utf-8-sig",
    )
    second = review_or_apply(recaptured, db, apply=True, confirm=CONFIRM_TOKEN, backup_db=tmp_path / "backup2.sqlite")
    assert first.added == 1 and second.unchanged == 1
    assert first.schema_added == ("observed_at",)
    assert backup.exists()


def test_conflicting_existing_row_is_rejected(tmp_path) -> None:
    candidate = tmp_path / "candidate.csv"
    other = tmp_path / "other.csv"
    db = tmp_path / "target.sqlite"
    _candidate(candidate)
    _candidate(other, tier_json=json.dumps([{"tier": n, "changed": True} for n in range(1, 18)]))
    _db(db)
    review_or_apply(candidate, db, apply=True, confirm=CONFIRM_TOKEN, backup_db=tmp_path / "backup.sqlite")
    with pytest.raises(ValueError, match="衝突"):
        review_or_apply(other, db)


def test_online_backup_includes_wal_visible_rows(tmp_path) -> None:
    source = tmp_path / "wal.sqlite"
    backup = tmp_path / "wal_backup.sqlite"
    conn = sqlite3.connect(source)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE custody (value TEXT)")
        conn.execute("INSERT INTO custody VALUES ('wal-visible')")
        conn.commit()
        _verified_sqlite_backup(source, backup)
    finally:
        conn.close()
    with sqlite3.connect(backup) as copied:
        assert copied.execute("SELECT value FROM custody").fetchone() == ("wal-visible",)
        assert copied.execute("PRAGMA quick_check").fetchone()[0] == "ok"
