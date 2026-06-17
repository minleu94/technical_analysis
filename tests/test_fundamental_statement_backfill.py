from __future__ import annotations

import sqlite3

from data_module.fundamental_schema import apply_fundamental_schema
from data_module.fundamental_statement_backfill import (
    apply_statement_items_backfill,
    plan_statement_items_backfill,
)


def _write_income_statement(raw_dir) -> None:
    raw_dir.mkdir()
    (raw_dir / "2330_income_statement.csv").write_text(
        "date,stock_id,type,value,origin_name\n"
        "2024-03-31,2330,EPS,2.30,基本每股盈餘（元）\n",
        encoding="utf-8-sig",
    )


def _write_availability(path) -> None:
    path.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,,2026-06-17,"
        "manual.retroactive_statement_baseline_mapping,statement-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )


def test_plan_statement_items_backfill_requires_governed_mapping(tmp_path):
    raw_dir = tmp_path / "financial_data"
    _write_income_statement(raw_dir)

    plan = plan_statement_items_backfill(
        raw_dir=raw_dir,
        availability_file=tmp_path / "missing.csv",
        source_version="financial-data-statements-v1",
        statement_types=("income_statement",),
    )

    assert plan.records == ()
    assert plan.ready_for_apply is False
    assert plan.diagnostics[0].code == "fundamental_statement_availability.mapping_file_missing"


def test_plan_statement_items_backfill_builds_records(tmp_path):
    raw_dir = tmp_path / "financial_data"
    _write_income_statement(raw_dir)
    availability_file = tmp_path / "statement_availability.csv"
    _write_availability(availability_file)

    plan = plan_statement_items_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version="financial-data-statements-v1",
        statement_types=("income_statement",),
    )

    assert plan.ready_for_apply is True
    assert plan.raw_row_count == 1
    assert len(plan.records) == 1
    assert plan.records[0].item_code == "EPS"
    assert plan.records[0].quality.value == "degraded"


def test_apply_statement_items_backfill_inserts_records_and_backs_up_db(tmp_path):
    raw_dir = tmp_path / "financial_data"
    _write_income_statement(raw_dir)
    availability_file = tmp_path / "statement_availability.csv"
    _write_availability(availability_file)
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)

    result = apply_statement_items_backfill(
        db_file=db_file,
        backup_dir=tmp_path / "backup",
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version="financial-data-statements-v1",
        statement_types=("income_statement",),
    )

    assert result.applied is True
    assert result.inserted_count == 1
    assert result.backup_file is not None
    assert result.backup_file.exists()
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT stock_code, statement_type, period, item_code, value, quality
            FROM fundamental_statement_items
            """
        ).fetchall()
    assert rows == [("2330", "income_statement", "2024-Q1", "EPS", "2.30", "degraded")]
