"""V1.6 cross-sectional factor snapshot SQLite schema。"""

from __future__ import annotations

import sqlite3


def apply_cross_sectional_factor_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cross_sectional_factor_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            snapshot_hash TEXT NOT NULL UNIQUE,
            decision_date TEXT NOT NULL,
            factor_set_version TEXT NOT NULL,
            universe_id TEXT NOT NULL,
            source_version TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            diagnostics_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_cross_sectional_factor_snapshots_date
            ON cross_sectional_factor_snapshots(decision_date);

        CREATE TABLE IF NOT EXISTS cross_sectional_factor_rows (
            row_id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            factor_name TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            available_date TEXT NOT NULL,
            value TEXT,
            score_bp INTEGER,
            rank INTEGER,
            quantile_bp INTEGER,
            universe_size INTEGER NOT NULL,
            quality TEXT NOT NULL,
            missing_policy TEXT NOT NULL,
            source_version TEXT NOT NULL,
            sector TEXT,
            concept_basket TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(snapshot_id) REFERENCES cross_sectional_factor_snapshots(snapshot_id)
        );

        CREATE INDEX IF NOT EXISTS idx_cross_sectional_factor_rows_snapshot
            ON cross_sectional_factor_rows(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_cross_sectional_factor_rows_factor
            ON cross_sectional_factor_rows(factor_name);
        CREATE INDEX IF NOT EXISTS idx_cross_sectional_factor_rows_stock
            ON cross_sectional_factor_rows(stock_code);
        CREATE INDEX IF NOT EXISTS idx_cross_sectional_factor_rows_sector
            ON cross_sectional_factor_rows(sector);
        CREATE INDEX IF NOT EXISTS idx_cross_sectional_factor_rows_concept
            ON cross_sectional_factor_rows(concept_basket);
        """
    )
