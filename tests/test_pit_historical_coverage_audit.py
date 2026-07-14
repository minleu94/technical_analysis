import hashlib
import importlib
import json
import sqlite3
from datetime import date
from pathlib import Path


def _module():
    try:
        return importlib.import_module("data_module.pit_historical_coverage_audit")
    except ModuleNotFoundError:
        return None


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT,
                period TEXT,
                as_of_date TEXT,
                available_date TEXT,
                source TEXT,
                quality TEXT,
                revision INTEGER
            )
            """
        )
        connection.executemany(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ("2330", "2024-04", "2024-04-30", "2024-05-10", "mops", "official", 1),
                ("2317", "2024-04", "2024-04-30", "2025-01-10", "archive", "observed", 2),
                ("1101", "2024-04", "2024-04-30", "2026-06-17", "retro", "degraded", 1),
            ),
        )


def test_formal_audit_is_read_only_and_preserves_typed_counts(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "PIT coverage audit contract is missing"
    db_path = tmp_path / "formal.db"
    _build_db(db_path)
    before_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    before_mtime = db_path.stat().st_mtime_ns

    report = module.audit_pit_historical_coverage(
        db_path=db_path,
        audit_cutoff=date(2024, 12, 31),
    )

    monthly = report.family_by_id["monthly_revenue"]
    assert monthly.status == "audited"
    assert monthly.total == 3
    assert monthly.matched_official == 1
    assert monthly.matched_observed_only == 1
    assert monthly.unmatched == 1
    assert monthly.future_blocked == 2
    assert monthly.revision == 1
    assert monthly.eligible == 1
    assert {(row.source_id, row.year) for row in monthly.source_year_rows} == {
        ("archive", "2024"),
        ("mops", "2024"),
        ("retro", "2024"),
    }
    assert report.family_by_id["quarterly_statement"].status == "coverage_deferred"
    assert report.family_by_id["corporate_action"].status == "coverage_deferred"
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before_hash
    assert db_path.stat().st_mtime_ns == before_mtime
    assert report.source_acceptance_changed is False
    assert report.production_apply_performed is False


def test_missing_database_fails_without_creating_file(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "PIT coverage audit contract is missing"
    missing = tmp_path / "missing.db"

    try:
        module.audit_pit_historical_coverage(
            db_path=missing,
            audit_cutoff=date(2024, 12, 31),
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing formal DB must fail closed")

    assert not missing.exists()


def test_large_database_fingerprint_is_streamed(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    assert module is not None, "PIT coverage audit contract is missing"
    db_path = tmp_path / "formal.db"
    _build_db(db_path)

    def reject_read_bytes(_path: Path) -> bytes:
        raise AssertionError("audit must not load an entire formal DB into memory")

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)
    report = module.audit_pit_historical_coverage(
        db_path=db_path,
        audit_cutoff=date(2024, 12, 31),
    )

    assert len(report.database_sha256) == 64


def test_cli_writes_report_only_to_explicit_output(tmp_path: Path) -> None:
    db_path = tmp_path / "formal.db"
    output = tmp_path / "staging" / "coverage.json"
    _build_db(db_path)
    try:
        cli = importlib.import_module("scripts.audit_pit_historical_coverage")
    except ModuleNotFoundError:
        cli = None
    assert cli is not None, "PIT coverage audit CLI is missing"

    exit_code = cli.main(
        [
            "--db-path",
            str(db_path),
            "--audit-cutoff",
            "2024-12-31",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "pit-historical-coverage-audit.v1"
    assert payload["database_open_mode"] == "read_only"
    assert payload["source_acceptance_changed"] is False
