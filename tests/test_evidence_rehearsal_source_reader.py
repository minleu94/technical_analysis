from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app_module.evidence_rehearsal_source_reader import EvidenceRehearsalSourceReader


def _seed_source(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE daily_prices (股票代碼 TEXT NOT NULL, 日期 TEXT NOT NULL, 收盤價 TEXT)"
        )
        connection.execute(
            "INSERT INTO daily_prices VALUES ('2330', '20260709', '100')"
        )
    return path


def test_reader_reports_schema_and_never_writes_source(tmp_path: Path) -> None:
    source = _seed_source(tmp_path / "source.sqlite3")
    before_bytes = source.read_bytes()
    before_mtime = source.stat().st_mtime_ns

    snapshot = EvidenceRehearsalSourceReader().read(
        source, decision_date="2026-07-09"
    )

    assert snapshot.opened is True
    assert snapshot.access_mode == "sqlite_uri_mode_ro_query_only"
    assert snapshot.schema_fingerprint
    assert snapshot.table_row_counts["daily_prices"] == 1
    assert "schema_missing:institutional_flows" in snapshot.diagnostics
    assert source.read_bytes() == before_bytes
    assert source.stat().st_mtime_ns == before_mtime


def test_schema_fingerprint_is_semantic_and_deterministic(tmp_path: Path) -> None:
    first = _seed_source(tmp_path / "first.sqlite3")
    second = _seed_source(tmp_path / "second.sqlite3")

    first_snapshot = EvidenceRehearsalSourceReader().read(
        first, decision_date="2026-07-09"
    )
    second_snapshot = EvidenceRehearsalSourceReader().read(
        second, decision_date="2026-07-09"
    )

    assert first_snapshot.schema_fingerprint == second_snapshot.schema_fingerprint


def test_backup_creates_isolated_working_copy_without_changing_source(
    tmp_path: Path,
) -> None:
    source = _seed_source(tmp_path / "source.sqlite3")
    target = tmp_path / "working" / "copy.sqlite3"
    before_bytes = source.read_bytes()
    before_mtime = source.stat().st_mtime_ns

    facts = EvidenceRehearsalSourceReader().backup_to_working_copy(source, target)

    assert facts.created is True
    assert facts.write_performed is True
    assert facts.source_write_performed is False
    assert target.is_file()
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_prices").fetchone() == (1,)
    assert source.read_bytes() == before_bytes
    assert source.stat().st_mtime_ns == before_mtime


def test_backup_refuses_existing_target_by_default(tmp_path: Path) -> None:
    source = _seed_source(tmp_path / "source.sqlite3")
    target = _seed_source(tmp_path / "working.sqlite3")

    with pytest.raises(FileExistsError, match="working copy already exists"):
        EvidenceRehearsalSourceReader().backup_to_working_copy(source, target)
