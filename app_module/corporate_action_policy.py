from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class CorporateActionProvider:
    """Provides corporate action events from local database."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._table_exists_cache: bool | None = None

    def _check_table_exists(self, conn: sqlite3.Connection) -> bool:
        if self._table_exists_cache is not None:
            return self._table_exists_cache

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='corporate_action_events'"
        ).fetchone()

        self._table_exists_cache = row is not None
        return self._table_exists_cache

    def get_ex_dividend_dates(self, symbol: str, start_date: str, end_date: str) -> tuple[list[str], list[str]]:
        """
        Query ex-dividend or ex-right events within (start_date, end_date].
        Returns:
            (dates, diagnostics)
        """
        if not self.db_path.exists():
            return [], ["source_not_ingested"]

        import contextlib
        try:
            with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
                if not self._check_table_exists(conn):
                    return [], ["source_not_ingested"]

                rows = conn.execute(
                    """
                    SELECT event_date 
                    FROM corporate_action_events 
                    WHERE stock_code = ? 
                      AND event_type IN ('ex_dividend', 'ex_right', 'capital_reduction')
                      AND REPLACE(REPLACE(event_date, '-', ''), '/', '') > ?
                      AND REPLACE(REPLACE(event_date, '-', ''), '/', '') <= ?
                    """,
                    (symbol, self._date_key(start_date), self._date_key(end_date)),
                ).fetchall()
                return [str(row[0]) for row in rows], []
        except sqlite3.OperationalError:
            return [], ["source_not_ingested"]

    @staticmethod
    def _date_key(value: Any) -> str:
        return str(value).strip().replace("-", "").replace("/", "")


class CorporateActionPolicy:
    """Policy for determining if forward performance is affected by corporate actions."""

    def __init__(self, provider: CorporateActionProvider):
        self.provider = provider

    def check_corporate_action_gap(self, symbol: str, start_date: str, end_date: str) -> list[str]:
        """
        Check if any corporate action gap happened between start_date (exclusive) and end_date (inclusive).
        Returns a list of warnings.
        """
        dates, diagnostics = self.provider.get_ex_dividend_dates(symbol, start_date, end_date)
        warnings = list(diagnostics)
        if dates:
            warnings.append("corporate_action_gap_detected")
        return warnings
