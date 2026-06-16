import sqlite3

from scripts.migrate_fundamental_schema import main


def test_fundamental_migration_cli_dry_run_does_not_modify_source(tmp_path, capsys):
    db_file = tmp_path / "twstock.db"
    working_copy = tmp_path / "working.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE daily_prices (id TEXT PRIMARY KEY)")

    assert main(["--db-file", str(db_file), "--working-copy", str(working_copy), "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "existing_tables_preserved: true" in out
    with sqlite3.connect(db_file) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"daily_prices"}


def test_fundamental_migration_cli_apply_requires_confirm(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE daily_prices (id TEXT PRIMARY KEY)")

    assert main(["--db-file", str(db_file), "--apply"]) == 2
