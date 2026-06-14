from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_servers.git_server import run_git_command
from mcp_servers.sqlite_server import (
    MAX_QUERY_ROWS,
    explain_sqlite,
    get_sqlite_schema,
    query_sqlite_readonly,
)
from scripts import auto_state_sync
from scripts.check_look_ahead_bias import (
    LookAheadCheckError,
    scan_paths,
    scan_source,
)


def test_look_ahead_checker_fails_closed_on_invalid_python():
    with pytest.raises(LookAheadCheckError):
        scan_source("value = (\n", path="broken.py")


def test_look_ahead_checker_fails_closed_on_missing_managed_file(tmp_path: Path):
    with pytest.raises(LookAheadCheckError):
        scan_paths(tmp_path, ["missing.py"])


def test_look_ahead_checker_detects_future_index_but_allows_slice_upper_bound():
    unsafe = """
for i in range(len(frame)):
    value = frame.iloc[i + 1]
"""
    safe = """
for i in range(len(frame)):
    history = frame.iloc[: i + 1]
"""

    assert len(scan_source(unsafe, path="unsafe.py")) == 1
    assert scan_source(safe, path="safe.py") == []


def test_sqlite_mcp_is_read_only_and_caps_rows(tmp_path: Path):
    db_path = tmp_path / "sample.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO items(value) VALUES (?)",
            [(str(index),) for index in range(MAX_QUERY_ROWS + 1)],
        )

    assert query_sqlite_readonly(db_path, "SELECT * FROM items WHERE id = 1") == [
        {"id": 1, "value": "0"}
    ]
    with pytest.raises(ValueError, match="回傳列數"):
        query_sqlite_readonly(db_path, "SELECT * FROM items")
    with pytest.raises(ValueError, match="唯讀"):
        query_sqlite_readonly(db_path, "DELETE FROM items")
    assert explain_sqlite(db_path, "SELECT * FROM items WHERE id = 1")
    assert "items" in get_sqlite_schema(db_path)


def test_sqlite_mcp_supports_unicode_identifiers(tmp_path: Path):
    db_path = tmp_path / "unicode.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE "資料" ("日期" TEXT PRIMARY KEY)')
        conn.execute('INSERT INTO "資料" ("日期") VALUES ("2026-06-14")')

    assert query_sqlite_readonly(db_path, 'SELECT "日期" FROM "資料"') == [
        {"日期": "2026-06-14"}
    ]
    assert explain_sqlite(db_path, 'SELECT "日期" FROM "資料"')


def test_git_mcp_raises_on_command_failure(monkeypatch):
    monkeypatch.setattr(
        "mcp_servers.git_server.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="bad revision",
        ),
    )

    with pytest.raises(RuntimeError, match="bad revision"):
        run_git_command(["log", "--bad-option"])


def test_git_mcp_rejects_unbounded_log_count():
    with pytest.raises(ValueError, match="1 到 100"):
        run_git_command(["log", "-n", "1000", "--oneline"])


def test_auto_state_sync_fails_closed_when_git_status_fails(monkeypatch):
    monkeypatch.setattr(
        auto_state_sync.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="not a repository",
        ),
    )

    with pytest.raises(RuntimeError, match="not a repository"):
        auto_state_sync.run_git_status()


def test_auto_state_sync_quotes_yaml_paths_and_preserves_following_sections():
    content = "task_id: demo\ngit_status:\n  clean: true\nhandoff:\n  owner: Codex\n"
    rendered = auto_state_sync.build_active_task_content(
        content,
        ["docs/report: final #1.md"],
        [],
    )

    assert '"docs/report: final #1.md"' in rendered
    assert "handoff:\n  owner: Codex" in rendered
