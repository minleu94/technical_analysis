import json
import sqlite3

from scripts.plan_tpex_daily_price_history_backfill import main


def test_tpex_history_plan_cli_reports_candidates_without_writing(tmp_path, capsys):
    db_file = tmp_path / "twstock.db"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )
    (source_dir / "20260616.json").write_text(
        json.dumps(
            [
                {
                    "Date": "1150616",
                    "SecuritiesCompanyCode": "3207",
                    "CompanyName": "耀勝",
                    "Close": "42.50",
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--db-file",
            str(db_file),
            "--start-date",
            "2026-06-16",
            "--end-date",
            "2026-06-16",
            "--source-json-dir",
            str(source_dir),
        ]
    )

    assert exit_code == 0
    assert "candidate_insert_count: 1" in capsys.readouterr().out
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM daily_prices").fetchone()[0] == 0

