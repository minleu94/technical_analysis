from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sqlite3

import scripts.scheduled.data_freshness_probe as probe
from data_module.official_trading_calendar import OfficialTradingCalendarError
from scripts.scheduled.data_freshness_probe import main


def _patch_calendar(monkeypatch, records):
    class _Calendar:
        def __init__(self, *args, **kwargs):
            pass

        def get_recent_official_trading_days(self, reference_date, count, **kwargs):
            return records[-count:]

    monkeypatch.setattr(probe, "OfficialTradingCalendar", _Calendar)


def _write_probe_db(db_path: Path, daily_rows=(), technical_rows=()):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT)')
        conn.execute('CREATE TABLE technical_indicators ("日期" TEXT, "證券代號" TEXT)')
        conn.executemany('INSERT INTO daily_prices VALUES (?, ?)', daily_rows)
        conn.executemany('INSERT INTO technical_indicators VALUES (?, ?)', technical_rows)


def _source(payload, source_id):
    return next(item for item in payload["source_statuses"] if item["source_id"] == source_id)


def test_freshness_probe_reports_artifact_write_failure_as_structured_error(
    tmp_path, monkeypatch, capsys
):
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    sqlite_dir = data_root / "sqlite"
    sqlite_dir.mkdir(parents=True)
    db_path = sqlite_dir / "twstock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE daily_prices ("日期" TEXT)')
        conn.execute('CREATE TABLE technical_indicators ("日期" TEXT)')

    status_path = tmp_path / "freshness.json"
    log_path = tmp_path / "freshness.log"
    original_write_text = Path.write_text

    def deny_artifact_writes(path, *args, **kwargs):
        if path in {status_path, log_path}:
            raise PermissionError("artifact output denied")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", deny_artifact_writes)

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
            "--log-path",
            str(log_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "failed"
    assert "status_artifact_write_failed:PermissionError" in payload["errors"]
    assert "log_artifact_write_failed:PermissionError" in payload["errors"]
    assert not status_path.exists()
    assert not log_path.exists()


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
    assert "data_update_quick_status_missing" in payload["warnings"]
    assert "tpex_daily_price_file_missing:20260706" in payload["warnings"]
    assert "source_freshness_degraded:sqlite.daily_prices" in payload["warnings"]
    assert _source(payload, "tpex.daily_prices.raw")["freshness_status"] == "stale"


def test_freshness_probe_marks_target_waiting_before_daily_cutoff(tmp_path, monkeypatch):
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    (data_root / "daily_price").mkdir(parents=True)
    (data_root / "daily_price_tpex").mkdir(parents=True)
    records = [
        {
            "date_str": value,
            "is_trading_day": True,
            "reason_code": "test_official_open",
            "evidence": {"source": "test-calendar"},
        }
        for value in ("2026-07-02", "2026-07-03", "2026-07-06")
    ]
    _patch_calendar(monkeypatch, records)
    monkeypatch.setattr(
        probe,
        "scheduled_now",
        lambda: datetime(2026, 7, 6, 4, 20, tzinfo=probe.PACIFIC),
    )
    db_path = data_root / "sqlite" / "twstock.db"
    _write_probe_db(
        db_path,
        daily_rows=[("20260703", "2330")],
        technical_rows=[("20260703", "2330")],
    )
    for directory in (data_root / "daily_price", data_root / "daily_price_tpex"):
        (directory / "20260703.csv").write_text(
            "證券代號,收盤價\n2330,1000\n",
            encoding="utf-8-sig",
        )
    status_path = tmp_path / "status.json"

    assert main([
        "--data-root", str(data_root),
        "--output-root", str(output_root),
        "--db-path", str(db_path),
        "--status-path", str(status_path),
    ]) == 0

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert _source(payload, "twse.daily_prices.raw")["freshness_status"] == "expected_wait"
    assert _source(payload, "tpex.daily_prices.raw")["freshness_status"] == "expected_wait"
    assert _source(payload, "sqlite.daily_prices")["freshness_status"] == "expected_wait"
    assert payload["checks"]["calendar_cutoff_local"] == "04:30"


def test_freshness_probe_detects_partial_stock_reconciliation(tmp_path, monkeypatch):
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    twse_dir = data_root / "daily_price"
    tpex_dir = data_root / "daily_price_tpex"
    twse_dir.mkdir(parents=True)
    tpex_dir.mkdir(parents=True)
    records = [{
        "date_str": "2026-07-06",
        "is_trading_day": True,
        "reason_code": "test_official_open",
        "evidence": {"source": "test-calendar"},
    }]
    _patch_calendar(monkeypatch, records)
    monkeypatch.setattr(
        probe,
        "scheduled_now",
        lambda: datetime(2026, 7, 6, 5, 0, tzinfo=probe.PACIFIC),
    )
    db_path = data_root / "sqlite" / "twstock.db"
    _write_probe_db(
        db_path,
        daily_rows=[("20260706", "2330")],
        technical_rows=[("20260706", "2330")],
    )
    (twse_dir / "20260706.csv").write_text(
        "證券代號,收盤價\n2330,1000\n2317,200\n",
        encoding="utf-8-sig",
    )
    (tpex_dir / "20260706.csv").write_text(
        "日期,證券代號,收盤價\n20260706,3207,42\n",
        encoding="utf-8-sig",
    )
    status_path = tmp_path / "status.json"

    assert main([
        "--data-root", str(data_root),
        "--output-root", str(output_root),
        "--db-path", str(db_path),
        "--status-path", str(status_path),
    ]) == 0

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    daily = _source(payload, "sqlite.daily_prices")
    assert daily["freshness_status"] == "partial"
    assert daily["coverage"]["reconciles_to_raw"] is False
    assert "sqlite_daily_prices_raw_reconciliation_partial" in payload["warnings"]


def test_freshness_probe_fails_closed_when_calendar_api_is_unavailable(tmp_path, monkeypatch):
    class _BrokenCalendar:
        def __init__(self, *args, **kwargs):
            pass

        def get_recent_official_trading_days(self, *args, **kwargs):
            raise OfficialTradingCalendarError("holidaySchedule unavailable")

    monkeypatch.setattr(probe, "OfficialTradingCalendar", _BrokenCalendar)
    monkeypatch.setattr(
        probe,
        "scheduled_now",
        lambda: datetime(2026, 7, 6, 5, 0, tzinfo=probe.PACIFIC),
    )
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    db_path = data_root / "sqlite" / "twstock.db"
    _write_probe_db(db_path)
    status_path = tmp_path / "status.json"

    assert main([
        "--data-root", str(data_root),
        "--output-root", str(output_root),
        "--db-path", str(db_path),
        "--status-path", str(status_path),
    ]) == 1

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "official_calendar_unavailable" in payload["errors"]
    assert payload["checks"]["official_calendar"]["freshness_status"] == "failed"


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


def test_freshness_probe_degrades_when_latest_quick_update_status_is_stale(tmp_path):
    data_root = tmp_path / "FA_Data"
    output_root = data_root / "output"
    sqlite_dir = data_root / "sqlite"
    (data_root / "daily_price").mkdir(parents=True)
    (data_root / "daily_price_tpex").mkdir(parents=True)
    sqlite_dir.mkdir(parents=True)
    db_path = sqlite_dir / "twstock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE daily_prices ("日期" TEXT)')
        conn.execute('CREATE TABLE technical_indicators ("日期" TEXT)')

    quick_status = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    quick_status.parent.mkdir(parents=True)
    quick_status.write_text(
        json.dumps({"status": "passed", "checked_at": "2000-01-01T04:20:00"}),
        encoding="utf-8",
    )
    status_path = tmp_path / "freshness.json"

    exit_code = main(
        [
            "--data-root", str(data_root),
            "--output-root", str(output_root),
            "--db-path", str(db_path),
            "--status-path", str(status_path),
        ]
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "degraded"
    assert payload["checks"]["data_update_quick_status"] == "passed"
    assert "data_update_quick_status_stale" in payload["warnings"]
