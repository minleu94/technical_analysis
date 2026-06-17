"""SQLite read providers for governed fundamental records."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from data_module.fundamental_data import MonthlyRevenueRecord
from data_module.fundamental_statement_data import StatementItemRecord
from data_module.valuation_data import (
    ValuationObservationBuildResult,
    build_valuation_observations,
)
from decision_module.factors.factor_dtos import FactorQuality


class FundamentalSQLiteProvider:
    def __init__(self, db_file: Path):
        self.db_file = Path(db_file)

    def load_monthly_revenues(
        self,
        *,
        stock_code: str,
        decision_date: date,
    ) -> tuple[MonthlyRevenueRecord, ...]:
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT stock_code, period, as_of_date, announced_date, available_date,
                       revenue, source, source_version, quality
                FROM fundamental_monthly_revenues
                WHERE stock_code = ? AND available_date <= ?
                ORDER BY period ASC, source_version ASC
                """,
                (stock_code, decision_date.isoformat()),
            ).fetchall()
        return tuple(_monthly_revenue_record(row) for row in rows)

    def load_valuation_observations(
        self,
        *,
        stock_code: str,
        decision_date: date,
    ) -> ValuationObservationBuildResult:
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT stock_code, as_of_date, available_date, metric_name,
                       value AS metric_value, industry, industry_percentile_bp,
                       source, source_version, quality
                FROM fundamental_valuation_metrics
                WHERE stock_code = ? AND available_date <= ?
                ORDER BY as_of_date ASC, metric_name ASC, source_version ASC
                """,
                (stock_code, decision_date.isoformat()),
            ).fetchall()
        return build_valuation_observations([dict(row) for row in rows])

    def load_statement_items(
        self,
        *,
        stock_code: str,
        decision_date: date,
    ) -> tuple[StatementItemRecord, ...]:
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT stock_code, statement_type, period, as_of_date, announced_date,
                       available_date, item_code, item_name, value, source,
                       source_version, quality
                FROM fundamental_statement_items
                WHERE stock_code = ? AND available_date <= ?
                ORDER BY period ASC, statement_type ASC, item_code ASC, source_version ASC
                """,
                (stock_code, decision_date.isoformat()),
            ).fetchall()
        return tuple(_statement_item_record(row) for row in rows)


def _monthly_revenue_record(row: sqlite3.Row) -> MonthlyRevenueRecord:
    return MonthlyRevenueRecord(
        stock_code=row["stock_code"],
        period=row["period"],
        as_of_date=_parse_date(row["as_of_date"]),
        raw_date=_parse_date(row["as_of_date"]),
        announced_date=_parse_optional_date(row["announced_date"]),
        available_date=_parse_date(row["available_date"]),
        revenue=Decimal(row["revenue"]),
        source=row["source"],
        source_version=row["source_version"],
        quality=FactorQuality(row["quality"]),
    )


def _statement_item_record(row: sqlite3.Row) -> StatementItemRecord:
    return StatementItemRecord(
        stock_code=row["stock_code"],
        statement_type=row["statement_type"],
        period=row["period"],
        as_of_date=_parse_date(row["as_of_date"]),
        announced_date=_parse_optional_date(row["announced_date"]),
        available_date=_parse_date(row["available_date"]),
        item_code=row["item_code"],
        item_name=row["item_name"],
        value=Decimal(row["value"]),
        source=row["source"],
        source_version=row["source_version"],
        quality=FactorQuality(row["quality"]),
    )


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_optional_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    return _parse_date(value)
