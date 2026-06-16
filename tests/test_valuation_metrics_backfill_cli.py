from __future__ import annotations

import sqlite3

from data_module.fundamental_schema import apply_fundamental_schema
from scripts.backfill_valuation_metrics import main


def _prepare_files(tmp_path):
    meta_dir = tmp_path / "meta_data"
    meta_dir.mkdir()
    companies_file = meta_dir / "companies.csv"
    companies_file.write_text(
        "stock_id,stock_name,industry_category,type\n"
        "2330,台積電,半導體業,上市\n"
        "2303,聯電,半導體業,上市\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "twstock.db"
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
            [("2330", "20260615", 18.5), ("2303", "20260615", 22.0)],
        )
        apply_fundamental_schema(conn)
    return db_file, companies_file


def test_valuation_metrics_backfill_cli_dry_run_does_not_write_db(tmp_path, capsys):
    db_file, companies_file = _prepare_files(tmp_path)

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--companies-file",
            str(companies_file),
            "--as-of-date",
            "2026-06-15",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert "ready_for_apply: true" in capsys.readouterr().out
    with sqlite3.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fundamental_valuation_metrics").fetchone()[0]
    assert count == 0


def test_valuation_metrics_backfill_cli_apply_requires_confirm(tmp_path):
    db_file, companies_file = _prepare_files(tmp_path)

    assert (
        main(
            [
                "--db-file",
                str(db_file),
                "--companies-file",
                str(companies_file),
                "--as-of-date",
                "2026-06-15",
                "--apply",
            ]
        )
        == 2
    )


def test_valuation_metrics_backfill_cli_apply_writes_after_confirm(tmp_path):
    db_file, companies_file = _prepare_files(tmp_path)

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--companies-file",
            str(companies_file),
            "--as-of-date",
            "2026-06-15",
            "--apply",
            "--confirm",
            "apply-valuation-metrics-backfill",
        ]
    )

    assert exit_code == 0
    with sqlite3.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fundamental_valuation_metrics").fetchone()[0]
    assert count == 2
