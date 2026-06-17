from __future__ import annotations

import sqlite3

from data_module.fundamental_schema import apply_fundamental_schema
from scripts.backfill_monthly_revenue_fundamentals import main


def _prepare_files(tmp_path):
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_monthly_revenue.csv").write_text(
        "date,stock_id,country,revenue,revenue_month,revenue_year\n"
        "2026-06-01,2330,Taiwan,1000000000,5,2026\n",
        encoding="utf-8",
    )
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    availability_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "manual.twse_monthly_revenue_announcement_log,announcement-log-2026-06-16\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
    return raw_dir, availability_file, db_file


def _write_mops_snapshot_file(tmp_path):
    snapshot_file = tmp_path / "mops_snapshot.csv"
    snapshot_file.write_text(
        "market,period,stock_code,company_name,current_month_revenue,"
        "previous_month_revenue,previous_year_month_revenue,mom_pct,yoy_pct,"
        "cumulative_revenue,previous_year_cumulative_revenue,cumulative_yoy_pct,"
        "note,fetched_at,source,source_version\n"
        "twse,2026-05,2330,台積電,1000000000,900000000,800000000,"
        "11.11,25.0,5000000000,4000000000,25.0,,"
        "2026-06-16T00:00:00Z,mops.monthly_revenue_static_snapshot,"
        "mops-static-2026-06-16\n",
        encoding="utf-8-sig",
    )
    return snapshot_file


def test_monthly_revenue_backfill_cli_dry_run_does_not_write_db(tmp_path, capsys):
    raw_dir, availability_file, db_file = _prepare_files(tmp_path)

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--raw-dir",
            str(raw_dir),
            "--availability-file",
            str(availability_file),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert "ready_for_apply: true" in capsys.readouterr().out
    with sqlite3.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fundamental_monthly_revenues").fetchone()[0]
    assert count == 0


def test_monthly_revenue_backfill_cli_dry_run_accepts_mops_snapshot_file(
    tmp_path,
    capsys,
):
    _raw_dir, availability_file, db_file = _prepare_files(tmp_path)
    snapshot_file = _write_mops_snapshot_file(tmp_path)

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--mops-snapshot-file",
            str(snapshot_file),
            "--availability-file",
            str(availability_file),
            "--source-version",
            "mops-static-snapshot-monthly-revenue-2026-06-16",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "ready_for_apply: true" in output
    assert "normalized_record_count: 1" in output
    with sqlite3.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fundamental_monthly_revenues").fetchone()[0]
    assert count == 0


def test_monthly_revenue_backfill_cli_apply_requires_confirm(tmp_path):
    raw_dir, availability_file, db_file = _prepare_files(tmp_path)

    assert (
        main(
            [
                "--db-file",
                str(db_file),
                "--raw-dir",
                str(raw_dir),
                "--availability-file",
                str(availability_file),
                "--apply",
            ]
        )
        == 2
    )


def test_monthly_revenue_backfill_cli_apply_writes_after_confirm(tmp_path):
    raw_dir, availability_file, db_file = _prepare_files(tmp_path)

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--raw-dir",
            str(raw_dir),
            "--availability-file",
            str(availability_file),
            "--apply",
            "--confirm",
            "apply-monthly-revenue-backfill",
        ]
    )

    assert exit_code == 0
    with sqlite3.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fundamental_monthly_revenues").fetchone()[0]
    assert count == 1
