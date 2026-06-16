from __future__ import annotations

import sqlite3

from data_module.fundamental_schema import apply_fundamental_schema
from data_module.valuation_metrics_backfill import (
    apply_valuation_metrics_backfill,
    load_industry_by_stock_from_companies,
    plan_valuation_metrics_backfill,
)


def _prepare_db(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE daily_prices (
                "證券代號" TEXT NOT NULL,
                "日期" TEXT NOT NULL,
                "本益比" REAL
            )
            """
        )
        conn.executemany(
            'INSERT INTO daily_prices("證券代號", "日期", "本益比") VALUES (?, ?, ?)',
            [
                ("2330", "20260615", 18.5),
                ("2303", "20260615", 22.0),
                ("2317", "20260615", 12.0),
                ("2330", "20260616", 19.0),
            ],
        )
        apply_fundamental_schema(conn)


def test_plan_valuation_metrics_backfill_uses_as_of_date_only(tmp_path) -> None:
    db_file = tmp_path / "twstock.db"
    _prepare_db(db_file)

    plan = plan_valuation_metrics_backfill(
        db_file=db_file,
        as_of_date="2026-06-15",
        industry_by_stock={
            "2330": "半導體業",
            "2303": "半導體業",
            "2317": "電子零組件業",
        },
        source_version="daily-prices-pe-test",
    )

    assert plan.ready_for_apply is True
    assert plan.source_row_count == 3
    assert len(plan.records) == 3
    assert {record.as_of_date.isoformat() for record in plan.records} == {"2026-06-15"}
    assert {record.available_date.isoformat() for record in plan.records} == {"2026-06-15"}
    assert {
        (record.stock_code, record.industry_percentile_bp, record.quality.value)
        for record in plan.records
    } == {
        ("2330", 5000, "observed"),
        ("2303", 10000, "observed"),
        ("2317", None, "degraded"),
    }


def test_plan_valuation_metrics_backfill_reports_missing_industry(tmp_path) -> None:
    db_file = tmp_path / "twstock.db"
    _prepare_db(db_file)

    plan = plan_valuation_metrics_backfill(
        db_file=db_file,
        as_of_date="2026-06-15",
        industry_by_stock={"2330": "半導體業", "2303": "半導體業"},
        source_version="daily-prices-pe-test",
    )

    assert len(plan.records) == 2
    assert plan.diagnostics[0].code == "valuation_backfill.missing_industry"
    assert plan.ready_for_apply is True


def test_load_industry_by_stock_from_companies_prefers_latest_row(tmp_path) -> None:
    companies_file = tmp_path / "companies.csv"
    companies_file.write_text(
        "industry_category,stock_id,stock_name,type,date,download_time\n"
        "其他,9935,慶豐富,twse,2023-06-30,2024-11-20 15:10:44\n"
        "居家生活,9935,慶豐富,twse,2024-11-20,2024-11-20 15:10:44\n"
        "電子零組件業,3207,耀勝,tpex,2024-11-20,2024-11-20 15:10:44\n",
        encoding="utf-8",
    )

    mapping = load_industry_by_stock_from_companies(companies_file)

    assert mapping["9935"] == "居家生活"
    assert mapping["3207"] == "電子零組件業"


def test_apply_valuation_metrics_backfill_inserts_records_and_backs_up_db(tmp_path) -> None:
    db_file = tmp_path / "twstock.db"
    backup_dir = tmp_path / "backup"
    _prepare_db(db_file)

    result = apply_valuation_metrics_backfill(
        db_file=db_file,
        backup_dir=backup_dir,
        as_of_date="2026-06-15",
        industry_by_stock={
            "2330": "半導體業",
            "2303": "半導體業",
            "2317": "電子零組件業",
        },
        source_version="daily-prices-pe-test",
    )

    assert result.applied is True
    assert result.inserted_count == 3
    assert result.backup_file is not None
    assert result.backup_file.exists()
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT stock_code, as_of_date, available_date, metric_name, value,
                   industry, industry_percentile_bp, source, source_version, quality
            FROM fundamental_valuation_metrics
            ORDER BY stock_code
            """
        ).fetchall()

    assert rows == [
        (
            "2303",
            "2026-06-15",
            "2026-06-15",
            "pe",
            "22.0",
            "半導體業",
            10000,
            "daily_prices.pe",
            "daily-prices-pe-test",
            "observed",
        ),
        (
            "2317",
            "2026-06-15",
            "2026-06-15",
            "pe",
            "12.0",
            "電子零組件業",
            None,
            "daily_prices.pe",
            "daily-prices-pe-test",
            "degraded",
        ),
        (
            "2330",
            "2026-06-15",
            "2026-06-15",
            "pe",
            "18.5",
            "半導體業",
            5000,
            "daily_prices.pe",
            "daily-prices-pe-test",
            "observed",
        ),
    ]


def test_apply_valuation_metrics_backfill_refuses_empty_plan(tmp_path) -> None:
    db_file = tmp_path / "twstock.db"
    _prepare_db(db_file)

    result = apply_valuation_metrics_backfill(
        db_file=db_file,
        backup_dir=tmp_path / "backup",
        as_of_date="2026-06-14",
        industry_by_stock={"2330": "半導體業"},
        source_version="daily-prices-pe-test",
    )

    assert result.applied is False
    assert result.inserted_count == 0
    assert result.backup_file is None
