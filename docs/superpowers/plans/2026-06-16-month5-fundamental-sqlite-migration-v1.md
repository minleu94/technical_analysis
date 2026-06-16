# Month 5 Fundamental SQLite Migration v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit, backed-up migration workflow for the fundamental SQLite tables that already exist as dry-run schema.

**Architecture:** Reuse `data_module/fundamental_schema.py` for table creation. Add a migration wrapper that can dry-run on a working copy, create a backup before applying, and restore that backup on failure. Do not add fundamental schema creation to `DBManager.init_database()`; formal schema migration must remain explicit.

**Tech Stack:** Python, pytest, SQLite, `pathlib.Path`, `shutil.copy2`, existing `TWStockConfig`.

---

## Entry Conditions

- Complete `2026-06-16-month5-availability-data-entrypoint.md`.
- Read `docs/agents/git_exclusions.md`; never stage `.db`, `.sqlite`, or temporary working-copy files.
- Confirm formal DB writes require explicit user approval when executed outside tests.

## Task 1: Migration Service With Backup / Rollback

**Files:**
- Create: `data_module/fundamental_migration.py`
- Test: `tests/test_fundamental_migration.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_fundamental_migration.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_migration.py -q -o addopts=
```

Expected: collection fails with `ModuleNotFoundError: No module named 'data_module.fundamental_migration'`.

- [ ] **Step 3: Implement migration service**

Create `data_module/fundamental_migration.py`:

```python
"""Fundamental SQLite schema migration with explicit backup and rollback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

from data_module.fundamental_schema import (
    FundamentalSchemaDryRunReport,
    apply_fundamental_schema,
    generate_fundamental_schema_dry_run_report,
)


@dataclass(frozen=True)
class FundamentalSchemaMigrationResult:
    applied: bool
    backup_file: Path | None
    report: FundamentalSchemaDryRunReport | None
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def apply_fundamental_schema_migration(
    db_file: Path,
    *,
    backup_dir: Path,
) -> FundamentalSchemaMigrationResult:
    db_file = Path(db_file)
    backup_dir = Path(backup_dir)
    if not db_file.exists():
        return FundamentalSchemaMigrationResult(
            applied=False,
            backup_file=None,
            report=None,
            diagnostics=("source_db_missing",),
        )

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{db_file.stem}_fundamental_schema_{_timestamp()}{db_file.suffix}"
    shutil.copy2(db_file, backup_file)

    conn = sqlite3.connect(db_file)
    try:
        report = generate_fundamental_schema_dry_run_report(conn)
        if not report.existing_tables_preserved:
            conn.rollback()
            return FundamentalSchemaMigrationResult(
                applied=False,
                backup_file=backup_file,
                report=report,
                diagnostics=("existing_tables_not_preserved",),
            )
        apply_fundamental_schema(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        restore_fundamental_schema_backup(backup_file, db_file)
        raise
    finally:
        conn.close()

    return FundamentalSchemaMigrationResult(
        applied=True,
        backup_file=backup_file,
        report=report,
    )


def restore_fundamental_schema_backup(backup_file: Path, db_file: Path) -> None:
    shutil.copy2(Path(backup_file), Path(db_file))


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
```

- [ ] **Step 4: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_migration.py tests\test_fundamental_schema.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add data_module/fundamental_migration.py tests/test_fundamental_migration.py
git commit -m "month5: add fundamental sqlite migration service"
```

## Task 2: Explicit Migration CLI

**Files:**
- Create: `scripts/migrate_fundamental_schema.py`
- Test: `tests/test_fundamental_migration_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_fundamental_migration_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_migration_cli.py -q -o addopts=
```

Expected: collection fails with import error for `scripts.migrate_fundamental_schema`.

- [ ] **Step 3: Implement CLI**

Create `scripts/migrate_fundamental_schema.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from data_module.config import TWStockConfig
from data_module.fundamental_migration import apply_fundamental_schema_migration
from data_module.fundamental_schema import generate_fundamental_schema_copy_dry_run_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run or apply fundamental SQLite schema.")
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--working-copy", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["apply-fundamental-schema"], default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    db_file = args.db_file or config.db_file
    if args.dry_run or not args.apply:
        working_copy = args.working_copy or db_file.with_name("twstock_fundamental_schema_dry_run.db")
        report = generate_fundamental_schema_copy_dry_run_report(db_file, working_copy)
        print(report.to_markdown())
        return 0 if report.existing_tables_preserved else 1

    if args.confirm != "apply-fundamental-schema":
        print("Applying formal fundamental schema requires --confirm apply-fundamental-schema")
        return 2

    result = apply_fundamental_schema_migration(db_file, backup_dir=config.backup_dir)
    if result.report is not None:
        print(result.report.to_markdown())
    print(f"backup_file: {result.backup_file}")
    return 0 if result.applied else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_migration.py tests\test_fundamental_migration_cli.py tests\test_fundamental_schema.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\fundamental_schema.py data_module\fundamental_migration.py scripts\migrate_fundamental_schema.py
```

Expected: tests pass and `py_compile` exits 0.

- [ ] **Step 5: Commit**

```powershell
git add scripts/migrate_fundamental_schema.py tests/test_fundamental_migration_cli.py
git commit -m "month5: add fundamental sqlite migration cli"
```

## Task 3: Documentation Sync

**Files:**
- Modify: `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Update docs**

Document that formal schema creation now has an explicit CLI with dry-run, backup, apply confirmation, and rollback helper. Do not claim formal DB has been migrated unless the apply command was actually run and verified.

- [ ] **Step 2: Review diff**

```powershell
git diff -- docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md docs/00_core/DOCUMENTATION_INDEX.md
```

Expected: docs preserve the distinction between available migration tooling and applied formal schema.

- [ ] **Step 3: Commit**

```powershell
git add docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md docs/00_core/DOCUMENTATION_INDEX.md
git commit -m "docs: document fundamental sqlite migration workflow"
```

## Final Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_schema.py tests\test_fundamental_migration.py tests\test_fundamental_migration_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\fundamental_schema.py data_module\fundamental_migration.py scripts\migrate_fundamental_schema.py
git status --short --branch
```
