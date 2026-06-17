from __future__ import annotations

import sqlite3

from data_module.fundamental_schema import apply_fundamental_schema
from scripts.inspect_fundamental_factors import main


def _insert_revenue(
    conn: sqlite3.Connection,
    *,
    stock_code: str,
    period: str,
    as_of_date: str,
    revenue: str,
    available_date: str,
) -> None:
    conn.execute(
        """
        INSERT INTO fundamental_monthly_revenues(
            stock_code, period, as_of_date, announced_date, available_date,
            revenue, source, source_version, quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stock_code,
            period,
            as_of_date,
            available_date,
            available_date,
            revenue,
            "mops.monthly_revenue_static_snapshot",
            "mops-static-snapshot-monthly-revenue-2026-06-16",
            "observed",
        ),
    )


def test_inspect_fundamental_factors_cli_reports_revenue_factor_summary(tmp_path, capsys):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        _insert_revenue(conn, stock_code="2330", period="2025-05", as_of_date="2025-05-31", revenue="100", available_date="2025-06-11")
        _insert_revenue(conn, stock_code="2330", period="2026-03", as_of_date="2026-03-31", revenue="110", available_date="2026-04-11")
        _insert_revenue(conn, stock_code="2330", period="2026-04", as_of_date="2026-04-30", revenue="120", available_date="2026-05-11")
        _insert_revenue(conn, stock_code="2330", period="2026-05", as_of_date="2026-05-31", revenue="150", available_date="2026-06-17")

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--stock-code",
            "2330",
            "--decision-date",
            "2026-06-30",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "- stock_count: 1" in output
    assert "- factor_record_count: 4" in output
    assert "fundamental.revenue_yoy: 1" in output
    assert "fundamental.revenue_mom: 1" in output
    assert "fundamental.revenue_3m_trend: 1" in output
    assert "fundamental.revenue_new_high: 1" in output
    assert "ScoringEngine" not in output


def test_inspect_fundamental_factors_cli_can_scan_all_monthly_revenue_stocks(tmp_path, capsys):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        _insert_revenue(conn, stock_code="2330", period="2026-05", as_of_date="2026-05-31", revenue="150", available_date="2026-06-17")
        _insert_revenue(conn, stock_code="3207", period="2026-05", as_of_date="2026-05-31", revenue="80", available_date="2026-06-17")

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--all-monthly-revenue-stocks",
            "--decision-date",
            "2026-06-30",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "- stock_count: 2" in output
    assert "2330: records=2 diagnostics=3" in output
    assert "3207: records=2 diagnostics=3" in output


def test_inspect_fundamental_factors_cli_limits_stock_summary_rows(tmp_path, capsys):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        _insert_revenue(conn, stock_code="2330", period="2026-05", as_of_date="2026-05-31", revenue="150", available_date="2026-06-17")
        _insert_revenue(conn, stock_code="3207", period="2026-05", as_of_date="2026-05-31", revenue="80", available_date="2026-06-17")

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--all-monthly-revenue-stocks",
            "--decision-date",
            "2026-06-30",
            "--stock-summary-limit",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "2330: records=2 diagnostics=3" in output
    assert "3207: records=2 diagnostics=3" not in output
    assert "... 1 more stocks omitted" in output
