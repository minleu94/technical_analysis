from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from data_module.ml_all_field_snapshot_provider import MLAllFieldSnapshotProvider
from ml_module.feature_eligibility import (
    ALL_FIELD_SOURCE_TABLES,
    ELIGIBILITY_STATUSES,
)


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                證券名稱 TEXT,
                成交股數 INTEGER,
                成交筆數 INTEGER,
                成交金額 INTEGER,
                開盤價 REAL,
                最高價 REAL,
                最低價 REAL,
                收盤價 REAL,
                本益比 REAL,
                PRIMARY KEY (證券代號, 日期)
            );
            CREATE TABLE technical_indicators (
                日期 TEXT,
                證券代號 TEXT,
                RSI REAL,
                MACD REAL,
                ATR REAL,
                ADX REAL,
                mystery_feature REAL,
                future_return_20d REAL,
                PRIMARY KEY (證券代號, 日期)
            );
            CREATE TABLE market_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                漲跌百分比 REAL
            );
            CREATE TABLE industry_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                漲跌百分比 REAL
            );
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT,
                period TEXT,
                as_of_date TEXT,
                announced_date TEXT,
                available_date TEXT,
                revenue TEXT,
                source TEXT,
                source_version TEXT,
                quality TEXT,
                created_at TEXT
            );
            CREATE TABLE fundamental_statement_items (
                stock_code TEXT,
                statement_type TEXT,
                period TEXT,
                as_of_date TEXT,
                announced_date TEXT,
                available_date TEXT,
                item_code TEXT,
                item_name TEXT,
                value TEXT,
                source TEXT,
                source_version TEXT,
                quality TEXT,
                created_at TEXT
            );
            CREATE TABLE fundamental_valuation_metrics (
                stock_code TEXT,
                as_of_date TEXT,
                available_date TEXT,
                metric_name TEXT,
                value TEXT,
                industry TEXT,
                industry_percentile_bp INTEGER,
                source TEXT,
                source_version TEXT,
                quality TEXT,
                created_at TEXT
            );
            CREATE TABLE institutional_flows (
                stock_code TEXT,
                decision_date TEXT,
                available_date TEXT,
                source_version TEXT,
                quality TEXT,
                foreign_investor_buy INTEGER,
                foreign_investor_sell INTEGER,
                foreign_investor_net INTEGER,
                investment_trust_buy INTEGER,
                investment_trust_sell INTEGER,
                investment_trust_net INTEGER,
                dealer_buy INTEGER,
                dealer_sell INTEGER,
                dealer_net INTEGER
            );
            CREATE TABLE tdcc_shareholding (
                stock_code TEXT,
                decision_date TEXT,
                available_date TEXT,
                source_version TEXT,
                quality TEXT,
                shareholding_tiers TEXT,
                large_holder_ratio_bp INTEGER,
                retail_holder_ratio_bp INTEGER,
                dispersion_index_bp INTEGER
            );
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
            );
            CREATE TABLE downstream_outputs (
                stock_id TEXT,
                decision_date TEXT,
                target_weight_bp INTEGER,
                custom_metric REAL
            );
            """
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ("20240102", "2330", "台積電", 100, 10, 10_000, 99, 101, 98, 100, 20),
                ("20240103", "2330", "台積電", 120, 12, 12_120, 100, 102, 99, 101, 21),
                ("20240104", "2330", "台積電", 130, 13, 13_260, 101, 103, 100, 102, 22),
            ),
        )
        connection.executemany(
            "INSERT INTO technical_indicators VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ("20240102", "2330", 50, "0.10", None, 20, 999, 10),
                ("20240103", "2330", 55, "0.12", "1.25", 22, 998, 11),
                ("20240104", "2330", 60, "0.14", "1.30", 24, 997, 12),
            ),
        )
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?, ?, ?)",
            (
                ("20240102", "TAIEX", 17_000, "0.2"),
                ("20240103", "TAIEX", 17_100, "0.5"),
            ),
        )
        connection.executemany(
            "INSERT INTO industry_indices VALUES (?, ?, ?, ?)",
            (
                ("20240102", "半導體類指數", 500, "0.3"),
                ("20240103", "半導體類指數", 505, "1.0"),
            ),
        )
        connection.executemany(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    "2330",
                    "2023-12",
                    "2023-12-31",
                    None,
                    "2024-01-02",
                    "12345.67",
                    "official",
                    "v1",
                    "observed",
                    "2024-01-02T00:00:00+00:00",
                ),
                (
                    "2330",
                    "2024-01",
                    "2024-01-31",
                    None,
                    "2024-01-04",
                    "99999",
                    "official",
                    "v1",
                    "observed",
                    "2024-01-04T00:00:00+00:00",
                ),
                (
                    "2330",
                    "2023-11",
                    "2023-11-30",
                    None,
                    "2023-12-01",
                    "77777",
                    "official",
                    "v1",
                    "observed",
                    "2024-01-05T00:00:00+00:00",
                ),
            ),
        )
        connection.execute(
            "INSERT INTO broker_flows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "20240103",
                "測試分點",
                "2330",
                "台積電",
                10,
                2,
                8,
                100,
                20,
                80,
                "buy",
                1,
                1,
                1,
                3,
            ),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _table_state(snapshot, table_name: str):
    return next(
        table
        for family in snapshot.family_availability
        for table in family.tables
        if table.table_name == table_name
    )


def test_schema_has_one_allowed_disposition_for_every_column(tmp_path: Path) -> None:
    database = tmp_path / "all-fields.db"
    _database(database)
    provider = MLAllFieldSnapshotProvider(database)

    manifest = provider.inspect_eligibility()

    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        table_names = tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            )
        )
        expected_columns = sum(
            len(connection.execute(f'PRAGMA table_info("{table}")').fetchall())
            for table in table_names
        )
    assert len(manifest.records) == expected_columns
    assert manifest.missing_tables == ("credit_transactions",)
    assert all(
        record.eligibility_status in ELIGIBILITY_STATUSES
        for record in manifest.records
    )
    identifier = manifest.get("daily_prices", "證券代號")
    leakage = manifest.get("technical_indicators", "future_return_20d")
    unknown = manifest.get("technical_indicators", "mystery_feature")
    generic_identifier = manifest.get("downstream_outputs", "stock_id")
    generic_leakage = manifest.get("downstream_outputs", "target_weight_bp")
    generic_unknown = manifest.get("downstream_outputs", "custom_metric")
    revenue = manifest.get("fundamental_monthly_revenues", "revenue")
    assert identifier is not None
    assert leakage is not None
    assert unknown is not None
    assert generic_identifier is not None
    assert generic_leakage is not None
    assert generic_unknown is not None
    assert revenue is not None
    assert identifier.eligibility_status == "excluded_identifier"
    assert leakage.eligibility_status == "excluded_leakage"
    assert unknown.eligibility_status == "unreviewed"
    assert generic_identifier.eligibility_status == "excluded_identifier"
    assert generic_leakage.eligibility_status == "excluded_leakage"
    assert generic_unknown.eligibility_status == "unreviewed"
    assert revenue.eligibility_status == "research_shadow"
    assert revenue.scale == 10_000
    assert revenue.record_hash.startswith("sha256:")


def test_provider_uses_union_masks_and_does_not_truncate_core_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "all-fields.db"
    _database(database)

    snapshot = MLAllFieldSnapshotProvider(database).load(
        decision_at="2024-01-04",
        history_start_date="2023-11-01",
        symbols=("2330",),
        industry_index_names=("半導體類指數",),
    )

    daily_dates = {
        row.event_at[:10]
        for row in snapshot.observations
        if row.source_table == "daily_prices"
    }
    broker_dates = {
        row.event_at[:10]
        for row in snapshot.observations
        if row.source_table == "broker_flows"
    }
    assert daily_dates == {"2024-01-02", "2024-01-03"}
    assert broker_dates == {"2024-01-03"}
    assert snapshot.core_feature_as_of_date == "2024-01-03"
    assert all(
        value.formal_training_eligible is False
        for row in snapshot.observations
        if row.source_table == "broker_flows"
        for value in row.values
    )

    missing_atr = next(
        value
        for row in snapshot.observations
        if row.source_table == "technical_indicators"
        and row.event_at.startswith("2024-01-02")
        for value in row.values
        if value.feature_id == "technical_indicators.ATR"
    )
    assert missing_atr.value_int is None
    assert missing_atr.missing_mask is True
    assert not any(
        value.feature_id.endswith("mystery_feature")
        or value.feature_id.endswith("future_return_20d")
        for row in snapshot.observations
        for value in row.values
    )
    assert snapshot.query_only is True
    assert snapshot.shadow_only is True
    assert snapshot.production_action_allowed is False


def test_unaccepted_source_and_future_availability_are_fail_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "all-fields.db"
    _database(database)

    snapshot = MLAllFieldSnapshotProvider(database).load(
        decision_at="2024-01-04T08:30:00+08:00",
        history_start_date="2023-11-01",
        symbols=("2330",),
    )

    revenue_rows = [
        row
        for row in snapshot.observations
        if row.source_table == "fundamental_monthly_revenues"
    ]
    assert len(revenue_rows) == 1
    assert revenue_rows[0].entity_id == "2330|2023-12"
    revenue_value = revenue_rows[0].values[0]
    assert revenue_value.value_int == 123_456_700
    assert revenue_value.eligibility_status == "research_shadow"
    assert revenue_value.formal_training_eligible is False

    availability = _table_state(snapshot, "fundamental_monthly_revenues")
    assert availability.blocked_future_rows == 2
    assert "future_availability_blocked:2" in availability.diagnostics


def test_staleness_is_an_explicit_mask_not_a_zero_fill(tmp_path: Path) -> None:
    database = tmp_path / "all-fields.db"
    _database(database)

    snapshot = MLAllFieldSnapshotProvider(database).load(
        decision_at="2024-03-10",
        history_start_date="2023-11-01",
        symbols=("2330",),
    )

    revenue_value = next(
        value
        for row in snapshot.observations
        if row.source_table == "fundamental_monthly_revenues"
        and row.entity_id == "2330|2023-12"
        for value in row.values
    )
    assert revenue_value.value_int == 123_456_700
    assert revenue_value.missing_mask is False
    assert revenue_value.staleness_mask is True
    assert revenue_value.age_days > 62


def test_missing_and_empty_optional_tables_degrade_without_writes(tmp_path: Path) -> None:
    database = tmp_path / "all-fields.db"
    _database(database)
    before_bytes = _sha256(database)
    before_stat = database.stat()
    provider = MLAllFieldSnapshotProvider(database)

    first = provider.load(
        decision_at="2024-01-04",
        history_start_date="2023-11-01",
        symbols=("2330",),
    )
    second = provider.load(
        decision_at="2024-01-04",
        history_start_date="2023-11-01",
        symbols=("2330",),
    )

    assert _table_state(first, "credit_transactions").state == "missing"
    assert _table_state(first, "institutional_flows").state == "empty"
    assert _table_state(first, "tdcc_shareholding").state == "empty"
    assert first.snapshot_hash == second.snapshot_hash
    assert first.eligibility_manifest_hash == second.eligibility_manifest_hash
    assert first.source_fingerprint == second.source_fingerprint
    after_stat = database.stat()
    assert _sha256(database) == before_bytes
    assert (after_stat.st_size, after_stat.st_mtime_ns) == (
        before_stat.st_size,
        before_stat.st_mtime_ns,
    )
