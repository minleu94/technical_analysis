from __future__ import annotations

import json
import sqlite3

from scripts.scheduled.data_freshness_probe import main


def test_freshness_probe_degrades_when_tpex_file_missing_for_latest_daily_date(tmp_path):
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    daily_price_dir = data_root / "daily_price"
    tpex_daily_price_dir = data_root / "daily_price_tpex"
    sqlite_dir = data_root / "sqlite"
    daily_price_dir.mkdir(parents=True)
    tpex_daily_price_dir.mkdir(parents=True)
    sqlite_dir.mkdir(parents=True)

    db_path = sqlite_dir / "twstock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT)')
        conn.execute('CREATE TABLE technical_indicators ("日期" TEXT, "證券代號" TEXT)')
        conn.execute('INSERT INTO daily_prices VALUES ("20260706", "2330")')
        conn.execute('INSERT INTO technical_indicators VALUES ("20260706", "2330")')

    (daily_price_dir / "20260706.csv").write_text(
        "日期,證券代號,證券名稱,收盤價\n20260706,2330,台積電,1000\n",
        encoding="utf-8-sig",
    )
    status_path = tmp_path / "status.json"

    exit_code = main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
            "--status-path",
            str(status_path),
            "--stale-days",
            "999",
        ]
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "degraded"
    assert payload["checks"]["twse_daily_price_file_exists_for_latest_date"] is True
    assert payload["checks"]["tpex_daily_price_file_exists_for_latest_date"] is False
    assert payload["warnings"] == ["tpex_daily_price_file_missing:20260706"]


def test_freshness_probe_degrades_when_latest_quick_update_failed(tmp_path):
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    daily_price_dir = data_root / "daily_price"
    tpex_daily_price_dir = data_root / "daily_price_tpex"
    sqlite_dir = data_root / "sqlite"
    daily_price_dir.mkdir(parents=True)
    tpex_daily_price_dir.mkdir(parents=True)
    sqlite_dir.mkdir(parents=True)

    db_path = sqlite_dir / "twstock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT)')
        conn.execute('CREATE TABLE technical_indicators ("日期" TEXT, "證券代號" TEXT)')
        conn.execute('INSERT INTO daily_prices VALUES ("20260706", "2330")')
        conn.execute('INSERT INTO technical_indicators VALUES ("20260706", "2330")')

    for directory in (daily_price_dir, tpex_daily_price_dir):
        (directory / "20260706.csv").write_text("日期,證券代號\n20260706,2330\n", encoding="utf-8-sig")

    quick_status = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    quick_status.parent.mkdir(parents=True)
    quick_status.write_text(json.dumps({"status": "failed", "errors": ["TWSE download failed"]}), encoding="utf-8")
    status_path = tmp_path / "freshness.json"

    exit_code = main(
        [
            "--data-root", str(data_root),
            "--output-root", str(output_root),
            "--db-path", str(db_path),
            "--status-path", str(status_path),
            "--stale-days", "999",
        ]
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "degraded"
    assert payload["checks"]["data_update_quick_status"] == "failed"
    assert "data_update_quick_failed" in payload["warnings"]
