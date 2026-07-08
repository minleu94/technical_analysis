from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
import contextlib


class TradingRestrictionProvider:
    """Provides trading restriction events from local database."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._table_exists_cache: bool | None = None

    def _check_table_exists(self, conn: sqlite3.Connection) -> bool:
        if self._table_exists_cache is not None:
            return self._table_exists_cache

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='microstructure_restriction_events'"
        ).fetchone()

        self._table_exists_cache = row is not None
        return self._table_exists_cache

    def get_restrictions(self, symbol: str, start_date: str, end_date: str) -> tuple[list[str], list[str]]:
        """
        Query restriction events within (start_date, end_date].
        Returns:
            (restriction_types, diagnostics)
        """
        if not self.db_path.exists():
            return [], ["source_not_ingested"]

        try:
            with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
                if not self._check_table_exists(conn):
                    return [], ["source_not_ingested"]

                rows = conn.execute(
                    """
                    SELECT restriction_type 
                    FROM microstructure_restriction_events 
                    WHERE stock_code = ? 
                      AND REPLACE(REPLACE(effective_date, '-', ''), '/', '') > ?
                      AND REPLACE(REPLACE(effective_date, '-', ''), '/', '') <= ?
                    """,
                    (symbol, self._date_key(start_date), self._date_key(end_date)),
                ).fetchall()
                # Return unique restriction types found in the period
                return list(set(str(row[0]) for row in rows)), []
        except sqlite3.OperationalError:
            return [], ["source_not_ingested"]
            
    def get_restrictions_on_date(self, symbol: str, target_date: str) -> tuple[list[str], list[str]]:
        """
        Query restriction events exactly on target_date.
        Returns:
            (restriction_types, diagnostics)
        """
        if not self.db_path.exists():
            return [], ["source_not_ingested"]

        try:
            with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
                if not self._check_table_exists(conn):
                    return [], ["source_not_ingested"]

                rows = conn.execute(
                    """
                    SELECT restriction_type 
                    FROM microstructure_restriction_events 
                    WHERE stock_code = ? 
                      AND REPLACE(REPLACE(effective_date, '-', ''), '/', '') = ?
                    """,
                    (symbol, self._date_key(target_date)),
                ).fetchall()
                return list(set(str(row[0]) for row in rows)), []
        except sqlite3.OperationalError:
            return [], ["source_not_ingested"]

    @staticmethod
    def _date_key(value: Any) -> str:
        return str(value).strip().replace("-", "").replace("/", "")


class TradingRestrictionPolicy:
    """Policy for determining trading restrictions on a candidate."""

    def __init__(self, provider: TradingRestrictionProvider):
        self.provider = provider

    def check_restriction_gap(self, symbol: str, start_date: str, end_date: str) -> list[str]:
        """
        Check if any trading restriction happened between start_date (exclusive) and end_date (inclusive).
        Returns a list of warnings (e.g. trading_restriction_gap_detected).
        """
        restrictions, diagnostics = self.provider.get_restrictions(symbol, start_date, end_date)
        warnings = list(diagnostics)
        if restrictions:
            warnings.append("trading_restriction_gap_detected")
        return warnings

    def check_restrictions(self, symbol: str, trade_date: str) -> list[str]:
        """
        Check restrictions on a specific trade date and map to rejected reason codes.
        Returns a list of rejected reasons, e.g., 'rejected_price_limit_locked' or 'rejected_trading_restricted'.
        """
        restrictions, diagnostics = self.provider.get_restrictions_on_date(symbol, trade_date)
        
        # We don't propagate diagnostics like 'source_not_ingested' as rejection reasons.
        # If it's not ingested, we don't reject.
        
        reasons = []
        if "limit_lock" in restrictions or "limit_up_lock" in restrictions or "limit_down_lock" in restrictions:
            reasons.append("rejected_price_limit_locked")
            
        other_restrictions = {"disposition", "periodic_call_auction", "full_delivery", "suspended"}
        if any(r in other_restrictions for r in restrictions):
            reasons.append("rejected_trading_restricted")
            
        return reasons
