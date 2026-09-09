"""現況快照的單位、版本冪等與歷史隔離。"""
import csv
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pytest
from types import SimpleNamespace

from app_module.stock_research_report_service import StockResearchReportReadService
from data_module.current_fundamental_snapshots import insert_observations, monthly_snapshot_rows


def test_snapshot_money_units_idempotency_and_date_only_isolation(tmp_path: Path) -> None:
    path = tmp_path / "monthly.csv"
    source = dict(stock_code="2330", period="2026-07", fetched_at="2026-09-01T01:00:00+00:00",
                  current_month_revenue="123,456", source_version="official-hash-1", market="twse", source="mops")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(source))
        writer.writeheader()
        writer.writerow(source)
    records = monthly_snapshot_rows(path)
    assert records[0]["value"] == "123456000"
    database = tmp_path / "test.db"
    connection = sqlite3.connect(database)
    assert insert_observations(connection, records) == 1
    assert insert_observations(connection, records) == 0
    # 未來觀測不可見，即使報告 period 比現在早。
    future = dict(records[0], period="2026-08", observed_at="2099-01-01T00:00:00+00:00")
    insert_observations(connection, [future])
    connection.commit()
    connection.close()
    service = StockResearchReportReadService(SimpleNamespace(db_file=database), clock=lambda: datetime.now(timezone.utc))
    current = service.read_report("2330")
    assert [(x.period, str(x.value), x.unit) for x in current.fundamentals] == [("2026-07", "123456000", "TWD")]
    historical = service.read_report("2330", as_of_date=datetime.now(timezone.utc).date())
    assert not historical.fundamentals


def test_ownership_snapshot_timestamp_does_not_grant_date_only_pit(tmp_path: Path) -> None:
    database = tmp_path / "ownership.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE tdcc_shareholding (stock_code TEXT, decision_date TEXT, available_date TEXT, observed_at TEXT, large_holder_ratio_bp INTEGER)")
    connection.execute("INSERT INTO tdcc_shareholding VALUES ('2330','2026-09-04','2026-09-10','2026-09-09T05:00:00+00:00',7000)")
    connection.commit()
    connection.close()
    config = SimpleNamespace(db_file=database)
    before = StockResearchReportReadService(config, clock=lambda: datetime(2026, 9, 9, 4, tzinfo=timezone.utc))
    after = StockResearchReportReadService(config, clock=lambda: datetime(2026, 9, 9, 6, tzinfo=timezone.utc))
    assert not before.read_report("2330").shareholding
    assert after.read_report("2330").shareholding[0].value == 7000
    assert after.read_report("2330").shareholding[0].available_at == "2026-09-09T05:00:00+00:00"
    assert not after.read_report("2330", as_of_date="2026-09-09").shareholding


def test_monthly_rejects_future_period_with_past_capture(tmp_path: Path) -> None:
    path = tmp_path / "future.csv"
    path.write_text("stock_code,period,fetched_at\n2330,2099-01,2026-09-01T01:00:00+00:00\n", encoding="utf-8")
    with pytest.raises(ValueError, match="period ends after observation"):
        monthly_snapshot_rows(path)
