import json
import sqlite3

from scripts.backfill_tpex_daily_prices import main


def test_tpex_daily_price_cli_dry_run_does_not_write(tmp_path, capsys):
    db_file = tmp_path / "twstock.db"
    source_json = tmp_path / "tpex.json"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "證券名稱" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )
    source_json.write_text(
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
            "--source-json",
            str(source_json),
            "--date",
            "2026-06-16",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert "ready_for_apply: true" in capsys.readouterr().out
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM daily_prices").fetchone()[0] == 0


def test_tpex_daily_price_cli_apply_requires_confirm(tmp_path):
    db_file = tmp_path / "twstock.db"
    source_json = tmp_path / "tpex.json"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "證券名稱" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )
    source_json.write_text(
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

    assert (
        main(
            [
                "--db-file",
                str(db_file),
                "--source-json",
                str(source_json),
                "--date",
                "2026-06-16",
                "--apply",
            ]
        )
        == 2
    )
