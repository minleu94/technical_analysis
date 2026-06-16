"""Fundamental Layer 候選 SQLite schema。

本模組只提供可重入的 schema 建立函式；不自行連接正式資料庫。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3


FUNDAMENTAL_TABLES = (
    "fundamental_monthly_revenues",
    "fundamental_statement_items",
    "fundamental_valuation_metrics",
)


@dataclass(frozen=True)
class FundamentalSchemaDryRunReport:
    existing_tables_before: tuple[str, ...]
    existing_tables_after: tuple[str, ...]
    created_tables: tuple[str, ...]
    modified_existing_tables: tuple[str, ...]

    @property
    def existing_tables_preserved(self) -> bool:
        return not self.modified_existing_tables and set(self.existing_tables_before).issubset(
            set(self.existing_tables_after)
        )

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Fundamental Schema Dry Run Report",
                "",
                f"- existing_tables_preserved: {str(self.existing_tables_preserved).lower()}",
                f"- existing_tables_before: {', '.join(self.existing_tables_before) or 'none'}",
                f"- created_tables: {', '.join(self.created_tables) or 'none'}",
                f"- modified_existing_tables: {', '.join(self.modified_existing_tables) or 'none'}",
            ]
        )


def apply_fundamental_schema(conn: sqlite3.Connection) -> None:
    """在呼叫端提供的 SQLite connection 上建立 fundamental 候選表。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS fundamental_monthly_revenues (
            stock_code TEXT NOT NULL,
            period TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            announced_date TEXT,
            available_date TEXT NOT NULL,
            revenue TEXT NOT NULL,
            source TEXT NOT NULL,
            source_version TEXT NOT NULL,
            quality TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_code, period, source_version)
        );

        CREATE INDEX IF NOT EXISTS idx_fundamental_monthly_revenues_available_date
            ON fundamental_monthly_revenues (available_date);
        CREATE INDEX IF NOT EXISTS idx_fundamental_monthly_revenues_stock_available
            ON fundamental_monthly_revenues (stock_code, available_date);

        CREATE TABLE IF NOT EXISTS fundamental_statement_items (
            stock_code TEXT NOT NULL,
            statement_type TEXT NOT NULL,
            period TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            announced_date TEXT,
            available_date TEXT NOT NULL,
            item_code TEXT NOT NULL,
            item_name TEXT NOT NULL,
            value TEXT NOT NULL,
            source TEXT NOT NULL,
            source_version TEXT NOT NULL,
            quality TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (
                stock_code,
                statement_type,
                period,
                item_code,
                source_version
            )
        );

        CREATE INDEX IF NOT EXISTS idx_fundamental_statement_items_available_date
            ON fundamental_statement_items (available_date);
        CREATE INDEX IF NOT EXISTS idx_fundamental_statement_items_stock_available
            ON fundamental_statement_items (stock_code, available_date);

        CREATE TABLE IF NOT EXISTS fundamental_valuation_metrics (
            stock_code TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            available_date TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            value TEXT NOT NULL,
            industry TEXT,
            industry_percentile_bp INTEGER,
            source TEXT NOT NULL,
            source_version TEXT NOT NULL,
            quality TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_code, as_of_date, metric_name, source_version)
        );

        CREATE INDEX IF NOT EXISTS idx_fundamental_valuation_metrics_available_date
            ON fundamental_valuation_metrics (available_date);
        CREATE INDEX IF NOT EXISTS idx_fundamental_valuation_metrics_stock_available
            ON fundamental_valuation_metrics (stock_code, available_date);
        """
    )


def generate_fundamental_schema_dry_run_report(
    conn: sqlite3.Connection,
) -> FundamentalSchemaDryRunReport:
    columns_before = _table_columns_snapshot(conn)
    existing_before = tuple(sorted(columns_before.keys()))

    apply_fundamental_schema(conn)

    columns_after = _table_columns_snapshot(conn)
    existing_after = tuple(sorted(name for name in columns_after if name not in FUNDAMENTAL_TABLES))
    created_tables = tuple(sorted(name for name in FUNDAMENTAL_TABLES if name in columns_after))
    modified_existing_tables = tuple(
        sorted(
            table_name
            for table_name, before_columns in columns_before.items()
            if columns_after.get(table_name) != before_columns
        )
    )

    return FundamentalSchemaDryRunReport(
        existing_tables_before=existing_before,
        existing_tables_after=existing_after,
        created_tables=created_tables,
        modified_existing_tables=modified_existing_tables,
    )


def generate_fundamental_schema_copy_dry_run_report(
    source_db: Path,
    working_copy: Path,
) -> FundamentalSchemaDryRunReport:
    """複製 SQLite DB 後只在 working copy 上執行 fundamental schema dry-run。"""
    source_db = Path(source_db)
    working_copy = Path(working_copy)
    if source_db.resolve() == working_copy.resolve():
        raise ValueError("Fundamental schema dry-run requires a separate working copy.")
    if not source_db.exists():
        raise FileNotFoundError(source_db)

    working_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, working_copy)
    conn = sqlite3.connect(working_copy)
    try:
        report = generate_fundamental_schema_dry_run_report(conn)
        conn.commit()
    finally:
        conn.close()
    return report


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
