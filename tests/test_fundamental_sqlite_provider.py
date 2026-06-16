from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from data_module.fundamental_schema import apply_fundamental_schema
from data_module.fundamental_sqlite_provider import FundamentalSQLiteProvider
from decision_module.factors.factor_dtos import FactorQuality


def test_sqlite_provider_loads_monthly_revenue_records_available_by_decision_date(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        conn.executemany(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2330",
                    "2026-05",
                    "2026-05-31",
                    "2026-06-10",
                    "2026-06-11",
                    "1000000000",
                    "financial_data.monthly_revenue_csv",
                    "monthly-revenue-v1",
                    "observed",
                ),
                (
                    "2330",
                    "2026-06",
                    "2026-06-30",
                    "2026-07-10",
                    "2026-07-11",
                    "1100000000",
                    "financial_data.monthly_revenue_csv",
                    "monthly-revenue-v1",
                    "observed",
                ),
            ],
        )

    records = FundamentalSQLiteProvider(db_file).load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 6, 30),
    )

    assert len(records) == 1
    record = records[0]
    assert record.stock_code == "2330"
    assert record.period == "2026-05"
    assert record.available_date == date(2026, 6, 11)
    assert record.revenue == Decimal("1000000000")
    assert record.quality == FactorQuality.OBSERVED


def test_sqlite_provider_loads_valuation_observations_available_by_decision_date(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        conn.executemany(
            """
            INSERT INTO fundamental_valuation_metrics(
                stock_code, as_of_date, available_date, metric_name, value,
                industry, industry_percentile_bp, source, source_version, quality
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2330",
                    "2026-06-16",
                    "2026-06-16",
                    "pe",
                    "20.5",
                    "semiconductor",
                    7500,
                    "daily_prices.pe",
                    "valuation-v1",
                    "observed",
                ),
                (
                    "2330",
                    "2026-06-17",
                    "2026-06-17",
                    "pe",
                    "21.5",
                    "semiconductor",
                    8000,
                    "daily_prices.pe",
                    "valuation-v1",
                    "observed",
                ),
            ],
        )

    result = FundamentalSQLiteProvider(db_file).load_valuation_observations(
        stock_code="2330",
        decision_date=date(2026, 6, 16),
    )

    assert result.diagnostics == ()
    assert len(result.records) == 1
    observation = result.records[0]
    assert observation.stock_code == "2330"
    assert observation.metric_name == "pe"
    assert observation.metric_value == Decimal("20.5")
    assert observation.available_date == date(2026, 6, 16)
    assert observation.industry_percentile_bp == 7500
    assert observation.quality == FactorQuality.OBSERVED
