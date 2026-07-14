from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from data_module.ml_historical_snapshot_provider import MLHistoricalSnapshotProvider


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE daily_prices (
            日期 TEXT, 證券代號 TEXT, 成交股數 INTEGER, 成交金額 INTEGER,
            開盤價 REAL, 最高價 REAL, 最低價 REAL, 收盤價 REAL
        );
        CREATE TABLE technical_indicators (
            日期 TEXT, 證券代號 TEXT, RSI REAL, MACD REAL, ADX REAL
        );
        CREATE TABLE market_indices (日期 TEXT, 收盤指數 REAL, 收盤價 REAL);
        CREATE TABLE industry_indices (日期 TEXT, 指數名稱 TEXT, 收盤指數 REAL);
        """
    )
    prices = [
        ("20240102", "2330", 100, 1000, 10, 11, 9, 10),
        ("20240103", "2330", 110, 1210, 10, 12, 10, 11),
        ("20240104", "2330", 120, 1440, 11, 13, 11, 12),
    ]
    connection.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", prices)
    connection.executemany(
        "INSERT INTO technical_indicators VALUES (?, ?, ?, ?, ?)",
        [(date, "2330", 55, 0.1, 20) for date, *_ in prices],
    )
    connection.executemany(
        "INSERT INTO market_indices VALUES (?, ?, ?)",
        [("20240102", None, 100), ("20240103", None, 102), ("20240104", None, 104)],
    )
    connection.executemany(
        "INSERT INTO industry_indices VALUES (?, ?, ?)",
        [("20240102", "半導體類指數", 200), ("20240103", "半導體類指數", 204), ("20240104", "半導體類指數", 208)],
    )
    connection.commit()
    connection.close()


def test_provider_loads_only_whitelisted_sources_with_t_minus_one_cutoff(tmp_path: Path) -> None:
    database = tmp_path / "history.db"
    _database(database)

    snapshot = MLHistoricalSnapshotProvider(database).load(
        decision_date="2024-01-04",
        history_start_date="2024-01-01",
        symbols=("2330",),
        industry_index_names=("半導體類指數",),
    )

    assert snapshot.feature_as_of_date == "2024-01-03"
    assert {row.trading_date for row in snapshot.prices} == {"2024-01-02", "2024-01-03"}
    assert snapshot.source_tables == (
        "daily_prices", "technical_indicators", "market_indices", "industry_indices"
    )
    assert snapshot.query_only is True
    assert snapshot.shadow_only is True
    assert snapshot.source_fingerprint.startswith("sha256:")


def test_appending_future_rows_does_not_change_same_decision_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "history.db"
    _database(database)
    provider = MLHistoricalSnapshotProvider(database)
    arguments = dict(
        decision_date="2024-01-04",
        history_start_date="2024-01-01",
        symbols=("2330",),
        industry_index_names=("半導體類指數",),
    )
    before = provider.load(**arguments)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("20250102", "2330", 999, 999999, 99, 100, 98, 99),
    )
    connection.commit()
    connection.close()

    after = provider.load(**arguments)

    assert after.prices == before.prices
    assert after.feature_as_of_date == before.feature_as_of_date


def test_provider_fails_closed_for_missing_database_or_schema(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        MLHistoricalSnapshotProvider(missing)
    assert not missing.exists()

    broken = tmp_path / "broken.db"
    sqlite3.connect(broken).close()
    with pytest.raises(ValueError, match="required table"):
        MLHistoricalSnapshotProvider(broken).load(
            decision_date="2024-01-04",
            history_start_date="2024-01-01",
            symbols=("2330",),
            industry_index_names=(),
        )
