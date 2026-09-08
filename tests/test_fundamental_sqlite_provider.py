from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import data_module.fundamental_sqlite_provider as fundamental_sqlite_provider_module
from data_module.fundamental_schema import apply_fundamental_schema
from data_module.fundamental_sqlite_provider import FundamentalSQLiteProvider
from decision_module.factors.factor_dtos import FactorQuality


_MAPPING_HEADER = (
    "stock_code,period,as_of_date,announced_date,available_date,source,source_version,"
    "availability_contract_version,evidence_class,source_hash,revision,parent_revision"
)


def _write_formal_mapping(
    path: Path,
    rows: list[tuple[str, ...]],
) -> None:
    path.write_text(
        "\n".join((_MAPPING_HEADER, *(",".join(row) for row in rows))) + "\n",
        encoding="utf-8",
    )


def test_sqlite_provider_loads_monthly_revenue_records_available_by_decision_date(tmp_path):
    db_file = tmp_path / "twstock.db"
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
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

    _write_formal_mapping(
        mapping_file,
        [
            (
                "2330",
                "2026-05",
                "2026-05-31",
                "2026-06-10",
                "2026-06-11",
                "twse.monthly_revenue_announcement",
                "test-formal-v2",
                "formal-availability.v2",
                "official_announcement",
                "a" * 64,
                "1",
                "",
            ),
        ],
    )

    records = FundamentalSQLiteProvider(
        db_file,
        monthly_revenue_availability_file=mapping_file,
    ).load_monthly_revenues(
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


def test_sqlite_provider_blocks_ambiguous_same_day_versions_regardless_of_insert_order(
    tmp_path,
):
    rows = [
        (
            "2330",
            "2026-05",
            "2026-05-31",
            "2026-06-10",
            "2026-06-11",
            "100",
            "mops.monthly_revenue_static_snapshot",
            "capture-2026-06-11-v1",
            "observed",
        ),
        (
            "2330",
            "2026-05",
            "2026-05-31",
            "2026-06-10",
            "2026-06-11",
            "200",
            "mops.monthly_revenue_static_snapshot",
            "capture-2026-06-11-v2",
            "observed",
        ),
    ]
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    _write_formal_mapping(
        mapping_file,
        [
            (
                "2330",
                "2026-05",
                "2026-05-31",
                "2026-06-10",
                "2026-06-11",
                "twse.monthly_revenue_announcement",
                "test-formal-v2",
                "formal-availability.v2",
                "official_announcement",
                "a" * 64,
                "1",
                "",
            ),
        ],
    )

    results = []
    for name, insert_rows in (("forward", rows), ("reverse", list(reversed(rows)))):
        db_file = tmp_path / f"{name}.db"
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
                insert_rows,
            )
        results.append(
            FundamentalSQLiteProvider(
                db_file,
                monthly_revenue_availability_file=mapping_file,
            ).load_monthly_revenues(
                stock_code="2330",
                decision_date=date(2026, 6, 30),
            )
        )

    assert results == [(), ()]


def test_sqlite_provider_deduplicates_same_day_identical_content_versions(
    tmp_path,
):
    db_file = tmp_path / "twstock.db"
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    rows = [
        (
            "2330",
            "2026-05",
            "2026-05-31",
            "2026-06-10",
            "2026-06-11",
            "100",
            "mops.monthly_revenue_static_snapshot",
            "capture-z",
            "observed",
        ),
        (
            "2330",
            "2026-05",
            "2026-05-31",
            "2026-06-10",
            "2026-06-11",
            "100",
            "mops.monthly_revenue_static_snapshot",
            "capture-a",
            "observed",
        ),
    ]
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
            list(reversed(rows)),
        )

    _write_formal_mapping(
        mapping_file,
        [
            (
                "2330",
                "2026-05",
                "2026-05-31",
                "2026-06-10",
                "2026-06-11",
                "twse.monthly_revenue_announcement",
                "test-formal-v2",
                "formal-availability.v2",
                "official_announcement",
                "a" * 64,
                "1",
                "",
            ),
        ],
    )

    records = FundamentalSQLiteProvider(
        db_file,
        monthly_revenue_availability_file=mapping_file,
    ).load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 6, 30),
    )

    assert len(records) == 1
    assert records[0].revenue == Decimal("100")
    assert records[0].source_version == "capture-a"


def test_sqlite_provider_preserves_historical_decision_after_mapping_revision_append(
    tmp_path,
):
    db_file = tmp_path / "twstock.db"
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    old_row = (
        "2330",
        "2026-05",
        "2026-05-31",
        "2026-06-10",
        "2026-06-11",
        "100",
        "mops.monthly_revenue_static_snapshot",
        "snapshot-old",
        "observed",
    )
    revised_row = (
        "2330",
        "2026-05",
        "2026-05-31",
        "2026-08-01",
        "2026-08-02",
        "120",
        "mops.monthly_revenue_static_snapshot",
        "snapshot-revised",
        "observed",
    )
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
            [old_row, revised_row],
        )

    revision_one = (
        "2330",
        "2026-05",
        "2026-05-31",
        "2026-06-10",
        "2026-06-11",
        "twse.monthly_revenue_announcement",
        "announcement-v1",
        "formal-availability.v2",
        "official_announcement",
        "a" * 64,
        "1",
        "",
    )
    revision_two = (
        "2330",
        "2026-05",
        "2026-05-31",
        "2026-08-01",
        "2026-08-02",
        "twse.monthly_revenue_announcement",
        "announcement-v2",
        "formal-availability.v2",
        "official_announcement",
        "b" * 64,
        "2",
        "1",
    )
    _write_formal_mapping(mapping_file, [revision_one])
    provider = FundamentalSQLiteProvider(
        db_file,
        monthly_revenue_availability_file=mapping_file,
    )

    before_append = provider.load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 7, 31),
    )
    assert len(before_append) == 1
    assert before_append[0].revenue == Decimal("100")
    assert before_append[0].available_date == date(2026, 6, 11)

    _write_formal_mapping(mapping_file, [revision_one, revision_two])

    after_append_same_decision = provider.load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 7, 31),
    )
    assert after_append_same_decision == before_append

    after_revision_available = provider.load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 8, 2),
    )
    assert len(after_revision_available) == 1
    assert after_revision_available[0].revenue == Decimal("120")
    assert after_revision_available[0].available_date == date(2026, 8, 2)


def test_sqlite_provider_blocks_unmapped_snapshot_and_keeps_legacy_official_mapping(
    tmp_path,
):
    db_file = tmp_path / "twstock.db"
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
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
                    "2026-06-16",
                    "2026-06-17",
                    "100",
                    "mops.monthly_revenue_static_snapshot",
                    "mops-static-snapshot-monthly-revenue-2026-07-14",
                    "observed",
                ),
                (
                    "2330",
                    "2026-06",
                    "2026-06-30",
                    "2026-07-14",
                    "2026-07-15",
                    "110",
                    "mops.monthly_revenue_static_snapshot",
                    "mops-static-snapshot-monthly-revenue-2026-07-14",
                    "observed",
                ),
            ],
        )

    mapping_file.write_text(
        "\n".join(
            [
                "stock_code,period,as_of_date,announced_date,available_date,source,source_version",
                (
                    "2330,2026-06,2026-06-30,2026-07-14,2026-07-15,"
                    "twse.monthly_revenue_announcement,"
                    "twse-openapi-t187ap05-l-2026-07-14"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = FundamentalSQLiteProvider(
        db_file,
        monthly_revenue_availability_file=mapping_file,
    ).load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 7, 16),
    )

    assert [record.period for record in records] == ["2026-06"]


def test_sqlite_provider_rejects_retroactive_baseline_mapping_for_live_read(tmp_path):
    db_file = tmp_path / "twstock.db"
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    with sqlite3.connect(db_file) as conn:
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
                "2026-06-17",
                "100",
                "mops.monthly_revenue_static_snapshot",
                "mops-static-snapshot-monthly-revenue-2026-07-14",
                "degraded",
            ),
        )

    mapping_file.write_text(
        "\n".join(
            [
                "stock_code,period,as_of_date,announced_date,available_date,source,source_version",
                (
                    "2330,2026-05,2026-05-31,,2026-06-17,"
                    "manual.retroactive_baseline_mapping,baseline-v1"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = FundamentalSQLiteProvider(
        db_file,
        monthly_revenue_availability_file=mapping_file,
    ).load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 7, 16),
    )

    assert records == ()


def test_sqlite_provider_fails_closed_when_monthly_revenue_mapping_is_missing(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
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
                "2026-06",
                "2026-06-30",
                "2026-07-14",
                "2026-07-15",
                "110",
                "mops.monthly_revenue_static_snapshot",
                "mops-static-snapshot-monthly-revenue-2026-07-14",
                "observed",
            ),
        )

    records = FundamentalSQLiteProvider(
        db_file,
        monthly_revenue_availability_file=tmp_path / "missing.csv",
    ).load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 7, 16),
    )

    assert records == ()


def test_sqlite_provider_fails_closed_when_monthly_revenue_mapping_load_errors(
    tmp_path,
    monkeypatch,
):
    db_file = tmp_path / "twstock.db"
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    with sqlite3.connect(db_file) as conn:
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
                "2026-06",
                "2026-06-30",
                "2026-07-14",
                "2026-07-15",
                "110",
                "mops.monthly_revenue_static_snapshot",
                "mops-static-snapshot-monthly-revenue-2026-07-14",
                "observed",
            ),
        )
    mapping_file.write_text("placeholder\n", encoding="utf-8")

    def _raise_mapping_load_error(_path: Path):
        raise ValueError("fixture mapping load failure")

    monkeypatch.setattr(
        fundamental_sqlite_provider_module,
        "load_monthly_revenue_availability_overrides_csv",
        _raise_mapping_load_error,
    )

    records = FundamentalSQLiteProvider(
        db_file,
        monthly_revenue_availability_file=mapping_file,
    ).load_monthly_revenues(
        stock_code="2330",
        decision_date=date(2026, 7, 16),
    )

    assert records == ()


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


def test_sqlite_provider_loads_statement_items_available_by_decision_date(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        conn.executemany(
            """
            INSERT INTO fundamental_statement_items(
                stock_code, statement_type, period, as_of_date, announced_date,
                available_date, item_code, item_name, value, source, source_version, quality
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2330",
                    "income_statement",
                    "2023-Q4",
                    "2023-12-31",
                    None,
                    "2026-06-17",
                    "EPS",
                    "基本每股盈餘（元）",
                    "9.21",
                    "financial_data.income_statement_csv",
                    "statements-v1",
                    "degraded",
                ),
                (
                    "2330",
                    "income_statement",
                    "2024-Q1",
                    "2024-03-31",
                    None,
                    "2026-07-01",
                    "EPS",
                    "基本每股盈餘（元）",
                    "8.70",
                    "financial_data.income_statement_csv",
                    "statements-v1",
                    "degraded",
                ),
            ],
        )

    records = FundamentalSQLiteProvider(db_file).load_statement_items(
        stock_code="2330",
        decision_date=date(2026, 6, 30),
    )

    assert len(records) == 1
    assert records[0].period == "2023-Q4"
    assert records[0].item_code == "EPS"
    assert records[0].value == Decimal("9.21")
    assert records[0].quality == FactorQuality.DEGRADED
