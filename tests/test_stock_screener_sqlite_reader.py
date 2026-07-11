from pathlib import Path
import sqlite3
from types import SimpleNamespace

from decision_module.stock_screener_sqlite_reader import (
    load_recent_industry_indices,
    load_recent_stock_prices,
)


def _config(db_file: Path) -> SimpleNamespace:
    return SimpleNamespace(use_sqlite=True, db_file=db_file)


def _create_database(db_file: Path) -> None:
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE daily_prices (
                日期 TEXT, 證券代號 TEXT, 證券名稱 TEXT, 收盤價 INTEGER,
                開盤價 INTEGER, 最高價 INTEGER, 最低價 INTEGER,
                成交股數 INTEGER, 成交金額 INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("20260102", "2330", "台積電", 100, 99, 101, 98, 1000, 100000),
                ("20260103", "2330", "台積電", 101, 100, 102, 99, 1100, 111100),
                ("20260103", "2317", "鴻海", 90, 89, 91, 88, 900, 81000),
            ],
        )
        conn.execute(
            """
            CREATE TABLE industry_indices (
                日期 TEXT, 指數名稱 TEXT, 收盤指數 INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO industry_indices VALUES (?, ?, ?)",
            [
                ("20260102", "半導體", 1000),
                ("20260103", "半導體", 1010),
                ("20260103", "金融保險", 990),
            ],
        )


def test_stock_price_reader_preserves_schema_order_and_readonly_connection(tmp_path, monkeypatch):
    db_file = tmp_path / "reader.db"
    _create_database(db_file)
    connect_calls: list[tuple[str, bool]] = []
    executed_sql: list[str] = []
    original_connect = sqlite3.connect

    class RecordingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            executed_sql.append(sql)
            return super().execute(sql, parameters)

    def recording_connect(database, *args, **kwargs):
        connect_calls.append((database, kwargs.get("uri", False)))
        kwargs["factory"] = RecordingConnection
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(
        "decision_module.stock_screener_sqlite_reader.sqlite3.connect", recording_connect
    )

    frame = load_recent_stock_prices(_config(db_file), "day", volume_lookback=1)

    assert frame is not None
    assert list(frame.columns) == [
        "日期", "證券代號", "證券名稱", "收盤價", "開盤價", "最高價", "最低價", "成交股數", "成交金額",
    ]
    assert frame["日期"].tolist() == sorted(frame["日期"].tolist())
    assert connect_calls == [(f"{db_file.resolve().as_uri()}?mode=ro", True)]
    assert "PRAGMA query_only=ON" in executed_sql


def test_industry_reader_preserves_schema_and_missing_database_falls_back_to_none(tmp_path):
    db_file = tmp_path / "reader.db"
    _create_database(db_file)

    frame = load_recent_industry_indices(_config(db_file), "day")

    assert frame is not None
    assert frame.columns.tolist() == ["日期", "指數名稱", "收盤指數"]
    assert frame["日期"].tolist() == sorted(frame["日期"].tolist())
    assert load_recent_stock_prices(_config(tmp_path / "missing.db"), "day", 1) is None
