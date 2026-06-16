from __future__ import annotations

import sqlite3
from calendar import monthrange
from datetime import date

from app_module.fundamental_factor_service import FundamentalFactorService
from data_module.fundamental_schema import apply_fundamental_schema


def _insert_revenue(conn, period: str, available_date: str, revenue: str) -> None:
    year, month = (int(part) for part in period.split("-"))
    as_of_date = f"{period}-{monthrange(year, month)[1]:02d}"
    conn.execute(
        """
        INSERT INTO fundamental_monthly_revenues(
            stock_code, period, as_of_date, announced_date, available_date,
            revenue, source, source_version, quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "2330",
            period,
            as_of_date,
            available_date,
            available_date,
            revenue,
            "financial_data.monthly_revenue_csv",
            "monthly-revenue-v1",
            "observed",
        ),
    )


def test_fundamental_factor_service_builds_revenue_pack_from_sqlite_provider(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        _insert_revenue(conn, "2025-05", "2025-06-11", "80")
        _insert_revenue(conn, "2026-04", "2026-05-11", "100")
        _insert_revenue(conn, "2026-05", "2026-06-11", "120")
        _insert_revenue(conn, "2026-06", "2026-07-11", "140")

    snapshot = FundamentalFactorService(db_file).build_snapshot(
        stock_code="2330",
        decision_date=date(2026, 6, 30),
    )

    factor_names = {record.factor_name for record in snapshot.records}
    assert "fundamental.revenue_yoy" in factor_names
    assert "fundamental.revenue_mom" in factor_names
    assert "fundamental.revenue_3m_trend" in factor_names
    assert "fundamental.revenue_new_high" in factor_names
    assert all(record.available_date <= date(2026, 6, 30) for record in snapshot.records)
    assert all(record.metadata["period"] != "2026-06" for record in snapshot.records)


def test_fundamental_factor_service_reports_missing_revenue_without_records(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)

    snapshot = FundamentalFactorService(db_file).build_snapshot(
        stock_code="2330",
        decision_date=date(2026, 6, 30),
    )

    assert snapshot.records == ()
    assert snapshot.diagnostics[0].code == "fundamental_sqlite.monthly_revenue_missing"


def test_fundamental_factor_service_builds_relative_valuation_factor(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        conn.execute(
            """
            INSERT INTO fundamental_valuation_metrics(
                stock_code, as_of_date, available_date, metric_name, value,
                industry, industry_percentile_bp, source, source_version, quality
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2330",
                "2026-06-16",
                "2026-06-16",
                "pe",
                "20",
                "semiconductor",
                2000,
                "daily_prices.pe",
                "valuation-v1",
                "observed",
            ),
        )

    snapshot = FundamentalFactorService(db_file).build_snapshot(
        stock_code="2330",
        decision_date=date(2026, 6, 16),
    )

    assert any(
        record.factor_name == "valuation.pe.relative_band" for record in snapshot.records
    )
