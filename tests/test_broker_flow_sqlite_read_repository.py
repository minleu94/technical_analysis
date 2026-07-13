from __future__ import annotations

import hashlib
import sqlite3
from datetime import date

from app_module.broker_flow_dashboard_dtos import BrokerFlowDashboardQuery
from app_module.broker_flow_sqlite_read_repository import (
    BrokerFlowSQLiteReadRepository,
)


def _create_broker_db(path):
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE broker_flows (
                日期 TEXT,
                分點名稱 TEXT,
                證券代號 TEXT,
                證券名稱 TEXT,
                買進股數 INTEGER,
                賣出股數 INTEGER,
                買賣超股數 INTEGER,
                買進金額千元 INTEGER,
                賣出金額千元 INTEGER,
                買賣超金額千元 INTEGER,
                trade_type TEXT,
                lots_observed INTEGER,
                amount_observed INTEGER,
                lots_rank INTEGER,
                amount_rank INTEGER
            )
            """
        )
        rows = []
        for day_index, day in enumerate(
            ("20260626", "20260627", "20260630", "20260701", "20260702", "20260703", "20260706")
        ):
            rows.extend(
                (
                    (
                        day,
                        "branch_a",
                        "2330",
                        "台積電",
                        160_000 + day_index * 1_000,
                        20_000,
                        140_000 + day_index * 1_000,
                        1000,
                        100,
                        900,
                        "買超",
                        1,
                        1,
                        1,
                        1,
                    ),
                    (
                        day,
                        "branch_b",
                        "2317",
                        "鴻海",
                        10_500,
                        40_000,
                        -29_500,
                        100,
                        400,
                        -300,
                        "賣超",
                        1,
                        1,
                        2,
                        2,
                    ),
                )
            )
        connection.executemany(
            "INSERT INTO broker_flows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def _query(period="week"):
    return BrokerFlowDashboardQuery(
        period=period,
        scope="top_bottom",
        requested_as_of_date=date(2026, 7, 5),
        limit_per_side=50,
    )


def test_repository_missing_db_is_typed_missing_and_does_not_create_file(tmp_path):
    db_path = tmp_path / "missing.db"

    source = BrokerFlowSQLiteReadRepository(db_path).load_dashboard_source(_query())

    assert source.quality == "missing"
    assert source.events == ()
    assert source.warnings == ("broker_flow_sqlite_missing",)
    assert not db_path.exists()


def test_repository_reads_last_five_broker_dates_and_preserves_db_bytes(tmp_path):
    db_path = tmp_path / "broker.db"
    _create_broker_db(db_path)
    before_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    before_mtime = db_path.stat().st_mtime_ns

    source = BrokerFlowSQLiteReadRepository(db_path).load_dashboard_source(_query())

    assert source.selected_trading_dates == (
        date(2026, 6, 27),
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    )
    assert {event.date for event in source.events} == {
        "2026-06-27",
        "2026-06-30",
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
    }
    observed = next(event for event in source.events if event.stock_code == "2330")
    degraded = next(event for event in source.events if event.stock_code == "2317")
    assert observed.buy_qty is not None
    assert observed.lots_quality == "observed"
    assert degraded.buy_qty == 10
    assert degraded.lots_quality == "degraded"
    assert "non_board_lot_remainder_shares" in " ".join(source.warnings)
    assert source.query_count == 2
    assert source.materialized_row_count == 10
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before_hash
    assert db_path.stat().st_mtime_ns == before_mtime


def test_repository_stock_and_branch_reads_push_scope_and_limit(tmp_path):
    db_path = tmp_path / "broker.db"
    _create_broker_db(db_path)
    repository = BrokerFlowSQLiteReadRepository(db_path)

    stock_source = repository.load_stock_source("2330", _query())
    branch_source = repository.load_branch_source("branch_a", _query(), limit=2)

    assert stock_source.events
    assert {event.stock_code for event in stock_source.events} == {"2330"}
    assert stock_source.materialized_row_count == 5
    assert len(branch_source.events) == 2
    assert {event.branch_system_key for event in branch_source.events} == {"branch_a"}
    assert [event.date for event in branch_source.events] == ["2026-07-03", "2026-07-02"]


def test_repository_missing_table_is_typed_missing_without_csv_fallback(tmp_path):
    db_path = tmp_path / "empty.db"
    with sqlite3.connect(db_path):
        pass

    source = BrokerFlowSQLiteReadRepository(db_path).load_dashboard_source(_query())

    assert source.quality == "missing"
    assert source.events == ()
    assert source.warnings == ("broker_flows_table_missing",)
