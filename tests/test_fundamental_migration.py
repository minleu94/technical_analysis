import sqlite3

from data_module.fundamental_migration import (
    apply_fundamental_schema_migration,
    restore_fundamental_schema_backup,
)


def test_apply_fundamental_schema_migration_creates_backup_and_tables(tmp_path):
    db_file = tmp_path / "twstock.db"
    backup_dir = tmp_path / "backup"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE daily_prices (id TEXT PRIMARY KEY)")

    result = apply_fundamental_schema_migration(db_file, backup_dir=backup_dir)

    assert result.applied is True
    assert result.backup_file is not None
    assert result.backup_file.exists()
    assert result.report.existing_tables_preserved is True
    with sqlite3.connect(db_file) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "fundamental_monthly_revenues" in tables
    assert "daily_prices" in tables


def test_restore_fundamental_schema_backup_restores_original_db(tmp_path):
    db_file = tmp_path / "twstock.db"
    backup_dir = tmp_path / "backup"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE daily_prices (id TEXT PRIMARY KEY)")

    result = apply_fundamental_schema_migration(db_file, backup_dir=backup_dir)
    assert result.backup_file is not None

    restore_fundamental_schema_backup(result.backup_file, db_file)

    with sqlite3.connect(db_file) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"daily_prices"}


def test_apply_fundamental_schema_migration_rejects_missing_db(tmp_path):
    result = apply_fundamental_schema_migration(
        tmp_path / "missing.db",
        backup_dir=tmp_path / "backup",
    )

    assert result.applied is False
    assert result.backup_file is None
    assert result.diagnostics[0] == "source_db_missing"
