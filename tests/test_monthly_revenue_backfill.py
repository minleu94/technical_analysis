from __future__ import annotations

import sqlite3
from datetime import date

from data_module.fundamental_schema import apply_fundamental_schema
from data_module.monthly_revenue_backfill import (
    apply_monthly_revenue_backfill,
    plan_mops_snapshot_monthly_revenue_backfill,
    plan_monthly_revenue_backfill,
)


def _write_revenue_csv(raw_dir, stock_code: str = "2330") -> None:
    raw_dir.mkdir()
    (raw_dir / f"{stock_code}_monthly_revenue.csv").write_text(
        "date,stock_id,country,revenue,revenue_month,revenue_year\n"
        f"2026-06-01,{stock_code},Taiwan,1000000000,5,2026\n",
        encoding="utf-8",
    )


def _write_availability_csv(path) -> None:
    path.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "manual.twse_monthly_revenue_announcement_log,announcement-log-2026-06-16\n",
        encoding="utf-8",
    )


def _write_mops_snapshot_csv(path) -> None:
    path.write_text(
        "market,period,stock_code,company_name,current_month_revenue,"
        "previous_month_revenue,previous_year_month_revenue,mom_pct,yoy_pct,"
        "cumulative_revenue,previous_year_cumulative_revenue,cumulative_yoy_pct,"
        "note,fetched_at,source,source_version\n"
        "twse,2026-05,2330,台積電,320000000000,300000000000,250000000000,"
        "6.67,28.0,1500000000000,1200000000000,25.0,,"
        "2026-06-16T00:00:00Z,mops.monthly_revenue_static_snapshot,"
        "mops-static-2026-06-16\n",
        encoding="utf-8-sig",
    )


def test_plan_monthly_revenue_backfill_requires_governed_mapping(tmp_path) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    availability_file = tmp_path / "missing_monthly_revenue_availability.csv"

    plan = plan_monthly_revenue_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version="financial-data-csv-monthly-revenue-v1",
    )

    assert plan.records == ()
    assert plan.ready_for_apply is False
    assert plan.diagnostics[0].code == "fundamental_availability.mapping_file_missing"


def test_plan_monthly_revenue_backfill_builds_records_from_mapping(tmp_path) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)

    plan = plan_monthly_revenue_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version="financial-data-csv-monthly-revenue-v1",
    )

    assert plan.ready_for_apply is True
    assert plan.raw_row_count == 1
    assert len(plan.records) == 1
    record = plan.records[0]
    assert record.stock_code == "2330"
    assert record.period == "2026-05"
    assert record.available_date == date(2026, 6, 11)
    assert record.source_version == "financial-data-csv-monthly-revenue-v1"
    assert plan.diagnostics == ()


def test_plan_mops_snapshot_monthly_revenue_backfill_preserves_mops_source(
    tmp_path,
) -> None:
    snapshot_file = tmp_path / "mops_snapshot.csv"
    _write_mops_snapshot_csv(snapshot_file)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)

    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="mops-static-snapshot-monthly-revenue-2026-06-16",
    )

    assert plan.ready_for_apply is True
    assert plan.raw_row_count == 1
    assert len(plan.records) == 1
    record = plan.records[0]
    assert record.stock_code == "2330"
    assert record.period == "2026-05"
    assert record.revenue == 320000000000
    assert record.source == "mops.monthly_revenue_static_snapshot"
    assert record.source_version == "mops-static-snapshot-monthly-revenue-2026-06-16"
    assert plan.diagnostics == ()


def test_apply_monthly_revenue_backfill_inserts_records_and_backs_up_db(tmp_path) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)
    db_file = tmp_path / "twstock.db"
    backup_dir = tmp_path / "backup"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)

    result = apply_monthly_revenue_backfill(
        db_file=db_file,
        backup_dir=backup_dir,
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version="financial-data-csv-monthly-revenue-v1",
    )

    assert result.applied is True
    assert result.inserted_count == 1
    assert result.backup_file is not None
    assert result.backup_file.exists()
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT stock_code, period, as_of_date, announced_date, available_date,
                   revenue, source, source_version, quality
            FROM fundamental_monthly_revenues
            """
        ).fetchall()
    assert rows == [
        (
            "2330",
            "2026-05",
            "2026-05-31",
            "2026-06-10",
            "2026-06-11",
            "1000000000",
            "financial_data.monthly_revenue_csv",
            "financial-data-csv-monthly-revenue-v1",
            "observed",
        )
    ]


def test_apply_monthly_revenue_backfill_refuses_diagnostics(tmp_path) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)

    result = apply_monthly_revenue_backfill(
        db_file=db_file,
        backup_dir=tmp_path / "backup",
        raw_dir=raw_dir,
        availability_file=tmp_path / "missing.csv",
        source_version="financial-data-csv-monthly-revenue-v1",
    )

    assert result.applied is False
    assert result.inserted_count == 0
    assert result.backup_file is None
    with sqlite3.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fundamental_monthly_revenues").fetchone()[0]
    assert count == 0
