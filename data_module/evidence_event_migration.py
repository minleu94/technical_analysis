from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3


EVIDENCE_TABLES = ("evidence_events", "evidence_outcomes")


@dataclass(frozen=True)
class EvidenceEventSchemaDryRunReport:
    existing_tables_before: tuple[str, ...]
    existing_tables_after: tuple[str, ...]
    created_tables: tuple[str, ...]
    modified_existing_tables: tuple[str, ...]

    @property
    def existing_tables_preserved(self) -> bool:
        return not self.modified_existing_tables and set(self.existing_tables_before).issubset(
            set(self.existing_tables_after)
        )


@dataclass(frozen=True)
class EvidenceEventSchemaMigrationResult:
    applied: bool
    backup_file: Path | None
    report: EvidenceEventSchemaDryRunReport | None
    diagnostics: tuple[str, ...] = ()


def apply_evidence_event_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS evidence_events (
            event_id TEXT PRIMARY KEY,
            event_hash TEXT NOT NULL UNIQUE,
            event_date TEXT NOT NULL,
            decision_date TEXT NOT NULL,
            symbol TEXT,
            event_type TEXT NOT NULL,
            event_family TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '',
            source_snapshot_id TEXT NOT NULL DEFAULT '',
            strategy_version_id TEXT NOT NULL DEFAULT '',
            profile_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            reason_codes_json TEXT NOT NULL DEFAULT '[]',
            why_not_codes_json TEXT NOT NULL DEFAULT '[]',
            risk_codes_json TEXT NOT NULL DEFAULT '[]',
            score_bp INTEGER,
            score_percentile_bp INTEGER,
            regime TEXT,
            sector TEXT,
            concept_basket TEXT,
            liquidity_state TEXT,
            data_quality TEXT NOT NULL,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            as_of_date TEXT NOT NULL,
            available_date TEXT NOT NULL,
            source_version TEXT NOT NULL DEFAULT '',
            cost_model_id TEXT NOT NULL DEFAULT '',
            benchmark_id TEXT,
            industry_benchmark_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_evidence_events_date_type
            ON evidence_events(decision_date, event_type);
        CREATE INDEX IF NOT EXISTS idx_evidence_events_symbol
            ON evidence_events(symbol, event_date);

        CREATE TABLE IF NOT EXISTS evidence_outcomes (
            outcome_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            window_days INTEGER NOT NULL,
            window_type TEXT NOT NULL DEFAULT 'trading_days',
            return_basis TEXT NOT NULL DEFAULT 'close_to_close_event_date',
            event_price_date TEXT,
            event_close TEXT,
            outcome_price_date TEXT,
            outcome_close TEXT,
            forward_return_bp INTEGER,
            benchmark_return_bp INTEGER,
            benchmark_excess_bp INTEGER,
            industry_return_bp INTEGER,
            industry_excess_bp INTEGER,
            max_adverse_excursion_bp INTEGER,
            max_favorable_excursion_bp INTEGER,
            tradable_flag INTEGER,
            limit_up_down_flag INTEGER,
            suspended_flag INTEGER,
            liquidity_cost_bp INTEGER,
            outcome_status TEXT NOT NULL,
            data_quality TEXT NOT NULL,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            data_as_of_date TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(event_id, window_days, return_basis),
            FOREIGN KEY(event_id) REFERENCES evidence_events(event_id)
        );

        CREATE INDEX IF NOT EXISTS idx_evidence_outcomes_event
            ON evidence_outcomes(event_id, window_days);
        """
    )


def generate_evidence_event_schema_dry_run_report(
    conn: sqlite3.Connection,
) -> EvidenceEventSchemaDryRunReport:
    columns_before = _table_columns_snapshot(conn)
    existing_before = tuple(sorted(columns_before.keys()))

    apply_evidence_event_schema(conn)

    columns_after = _table_columns_snapshot(conn)
    existing_after = tuple(sorted(columns_after.keys()))
    created_tables = tuple(sorted(table for table in EVIDENCE_TABLES if table in columns_after))
    modified_existing_tables = tuple(
        sorted(
            table_name
            for table_name, before_columns in columns_before.items()
            if columns_after.get(table_name) != before_columns
        )
    )
    return EvidenceEventSchemaDryRunReport(
        existing_tables_before=existing_before,
        existing_tables_after=existing_after,
        created_tables=created_tables,
        modified_existing_tables=modified_existing_tables,
    )


def generate_evidence_event_schema_copy_dry_run_report(
    source_db: Path,
    working_copy: Path,
) -> EvidenceEventSchemaDryRunReport:
    source_db = Path(source_db)
    working_copy = Path(working_copy)
    if source_db.resolve() == working_copy.resolve():
        raise ValueError("Evidence event schema dry-run requires a separate working copy.")
    if not source_db.exists():
        raise FileNotFoundError(source_db)

    working_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, working_copy)
    conn = sqlite3.connect(working_copy)
    try:
        report = generate_evidence_event_schema_dry_run_report(conn)
        conn.commit()
        return report
    finally:
        conn.close()


def apply_evidence_event_schema_migration(
    db_file: Path,
    *,
    backup_dir: Path,
) -> EvidenceEventSchemaMigrationResult:
    db_file = Path(db_file)
    backup_dir = Path(backup_dir)
    if not db_file.exists():
        return EvidenceEventSchemaMigrationResult(
            applied=False,
            backup_file=None,
            report=None,
            diagnostics=("source_db_missing",),
        )

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{db_file.stem}_evidence_event_schema_{_timestamp()}{db_file.suffix}"
    shutil.copy2(db_file, backup_file)

    conn = sqlite3.connect(db_file)
    try:
        report = generate_evidence_event_schema_dry_run_report(conn)
        if not report.existing_tables_preserved:
            conn.rollback()
            return EvidenceEventSchemaMigrationResult(
                applied=False,
                backup_file=backup_file,
                report=report,
                diagnostics=("existing_tables_not_preserved",),
            )
        apply_evidence_event_schema(conn)
        conn.commit()
        return EvidenceEventSchemaMigrationResult(applied=True, backup_file=backup_file, report=report)
    except Exception:
        conn.rollback()
        shutil.copy2(backup_file, db_file)
        raise
    finally:
        conn.close()


def _table_columns_snapshot(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    table_names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    return {
        table_name: tuple(
            row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        )
        for table_name in table_names
    }


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
