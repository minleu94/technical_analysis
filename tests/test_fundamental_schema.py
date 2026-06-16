import sqlite3

from data_module.fundamental_schema import (
    FUNDAMENTAL_TABLES,
    apply_fundamental_schema,
    generate_fundamental_schema_copy_dry_run_report,
    generate_fundamental_schema_dry_run_report,
)


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _indexes(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA index_list({table_name})")}


def test_apply_fundamental_schema_creates_monthly_revenue_contract():
    conn = sqlite3.connect(":memory:")

    apply_fundamental_schema(conn)
    apply_fundamental_schema(conn)

    columns = _columns(conn, "fundamental_monthly_revenues")
    assert {
        "stock_code",
        "period",
        "as_of_date",
        "announced_date",
        "available_date",
        "revenue",
        "source",
        "source_version",
        "quality",
        "created_at",
    }.issubset(columns)

    indexes = _indexes(conn, "fundamental_monthly_revenues")
    assert "idx_fundamental_monthly_revenues_available_date" in indexes
    assert "idx_fundamental_monthly_revenues_stock_available" in indexes


def test_apply_fundamental_schema_enforces_available_date_on_revenue_rows():
    conn = sqlite3.connect(":memory:")
    apply_fundamental_schema(conn)

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
            "2026-05",
            "2026-05-31",
            None,
            "2026-06-10",
            "1000000000",
            "financial_data.monthly_revenue_csv",
            "fundamental-source-inventory-2026-06-16",
            "degraded",
        ),
    )

    try:
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, revenue, source, source_version, quality
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2330",
                "2026-06",
                "2026-06-30",
                "1100000000",
                "financial_data.monthly_revenue_csv",
                "fundamental-source-inventory-2026-06-16",
                "degraded",
            ),
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("available_date must be NOT NULL")


def test_apply_fundamental_schema_creates_statement_and_valuation_contracts():
    conn = sqlite3.connect(":memory:")

    apply_fundamental_schema(conn)

    statement_columns = _columns(conn, "fundamental_statement_items")
    assert {
        "stock_code",
        "statement_type",
        "period",
        "as_of_date",
        "announced_date",
        "available_date",
        "item_code",
        "item_name",
        "value",
        "source",
        "source_version",
        "quality",
    }.issubset(statement_columns)

    valuation_columns = _columns(conn, "fundamental_valuation_metrics")
    assert {
        "stock_code",
        "as_of_date",
        "available_date",
        "metric_name",
        "value",
        "industry",
        "industry_percentile_bp",
        "source",
        "source_version",
        "quality",
    }.issubset(valuation_columns)

    assert "idx_fundamental_statement_items_available_date" in _indexes(
        conn, "fundamental_statement_items"
    )
    assert "idx_fundamental_valuation_metrics_available_date" in _indexes(
        conn, "fundamental_valuation_metrics"
    )


def test_dry_run_report_preserves_existing_core_tables():
    conn = sqlite3.connect(":memory:")
    for table_name in (
        "daily_prices",
        "technical_indicators",
        "broker_flows",
        "market_indices",
        "industry_indices",
    ):
        conn.execute(f"CREATE TABLE {table_name} (id TEXT PRIMARY KEY, value TEXT)")

    report = generate_fundamental_schema_dry_run_report(conn)

    assert report.existing_tables_preserved is True
    assert set(report.existing_tables_before) == {
        "daily_prices",
        "technical_indicators",
        "broker_flows",
        "market_indices",
        "industry_indices",
    }
    assert set(report.created_tables) == set(FUNDAMENTAL_TABLES)
    assert report.modified_existing_tables == ()
    assert "fundamental_monthly_revenues" in report.to_markdown()
    assert "existing_tables_preserved: true" in report.to_markdown()


def test_copy_dry_run_report_applies_schema_only_to_working_copy(tmp_path):
    source_db = tmp_path / "twstock.db"
    working_copy = tmp_path / "twstock_fundamental_dry_run.db"

    with sqlite3.connect(source_db) as conn:
        conn.execute("CREATE TABLE daily_prices (id TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE technical_indicators (id TEXT PRIMARY KEY, value TEXT)")

    report = generate_fundamental_schema_copy_dry_run_report(source_db, working_copy)

    with sqlite3.connect(source_db) as conn:
        source_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    with sqlite3.connect(working_copy) as conn:
        copy_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "fundamental_monthly_revenues" not in source_tables
    assert set(FUNDAMENTAL_TABLES).issubset(copy_tables)
    assert report.existing_tables_preserved is True
    assert set(report.created_tables) == set(FUNDAMENTAL_TABLES)


def test_copy_dry_run_report_rejects_source_as_working_copy(tmp_path):
    source_db = tmp_path / "twstock.db"
    with sqlite3.connect(source_db) as conn:
        conn.execute("CREATE TABLE daily_prices (id TEXT PRIMARY KEY, value TEXT)")

    try:
        generate_fundamental_schema_copy_dry_run_report(source_db, source_db)
    except ValueError as exc:
        assert "working copy" in str(exc)
    else:
        raise AssertionError("source database must not be used as its own dry-run copy")


def test_copy_dry_run_report_releases_working_copy_file_handle(tmp_path):
    source_db = tmp_path / "twstock.db"
    working_copy = tmp_path / "twstock_fundamental_dry_run.db"
    with sqlite3.connect(source_db) as conn:
        conn.execute("CREATE TABLE daily_prices (id TEXT PRIMARY KEY, value TEXT)")

    generate_fundamental_schema_copy_dry_run_report(source_db, working_copy)

    working_copy.unlink()
    assert not working_copy.exists()
