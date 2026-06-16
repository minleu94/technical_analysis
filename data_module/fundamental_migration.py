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
