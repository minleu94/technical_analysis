from __future__ import annotations

from datetime import date, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)


def _build_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_prices (
                日期 TEXT NOT NULL,
                證券代號 TEXT NOT NULL,
                證券名稱 TEXT,
                成交股數 INTEGER,
                最高價 TEXT,
                最低價 TEXT,
                收盤價 TEXT,
                new_unreviewed_metric TEXT
            );
            CREATE TABLE technical_indicators (
                日期 TEXT NOT NULL,
                證券代號 TEXT NOT NULL,
                最高價 TEXT,
                最低價 TEXT,
                收盤價 TEXT,
                ATR TEXT,
                ADX TEXT,
                custom_future_unknown TEXT
            );
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                revenue TEXT,
                announced_date TEXT,
                available_at TEXT,
                first_observed_at TEXT,
                revision_id TEXT,
                quality TEXT,
                new_field TEXT
            );
            CREATE TABLE institutional_flows (
                stock_code TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                foreign_investor_net INTEGER,
                publication_at TEXT,
                available_at TEXT,
                revision_id TEXT,
                quality TEXT
            );
            """
        )
        start = date(2024, 1, 1)
        daily_rows: list[
            tuple[str, str, str, int, str, str, str, str]
        ] = []
        technical_rows: list[tuple[str, ... | None]] = []
        for symbol, offset in (("2330", 0), ("2317", 20)):
            for index in range(30):
                day = (start + timedelta(days=index)).strftime("%Y%m%d")
                close = 100 + offset + index
                daily_rows.append(
                    (
                        day,
                        symbol,
                        "台積電" if symbol == "2330" else "鴻海",
                        1000 + index,
                        str(close + 2),
                        str(close - 2),
                        str(close),
                        "blocked",
                    )
                )
                technical_rows.append(
                    (
                        day,
                        symbol,
                        str(close + 2),
                        str(close - 2),
                        str(close),
                        None,
                        None,
                        "fail_closed",
                    )
                )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            daily_rows,
        )
        connection.executemany(
            "INSERT INTO technical_indicators VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            technical_rows,
        )
        connection.executemany(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    "2330",
                    "2023-12",
                    "2023-12-31",
                    "123.45",
                    "2024-01-10",
                    None,
                    "2024-01-15",
                    "r1",
                    "accepted",
                    "blocked",
                ),
                (
                    "2330",
                    "2024-01",
                    "2024-01-31",
                    "125.00",
                    "2024-02-10",
                    None,
                    "2024-02-20",
                    "r2",
                    "accepted",
                    "blocked",
                ),
                (
                    "2330",
                    "2023-11",
                    "2023-11-30",
                    "120.00",
                    "2024-01-05",
                    None,
                    None,
                    "r0",
                    "accepted",
                    "blocked",
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO institutional_flows VALUES
            ('2330', '2024-01-03', 777, '2024-01-03T18:00:00+08:00',
             '2024-01-03T18:30:00+08:00', 'flow-r1', 'accepted')
            """
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _build_statement_database(
    path: Path,
    *,
    source: str,
    source_version: str,
    report_basis: str | None = None,
) -> None:
    _build_database(path)
    with sqlite3.connect(path) as connection:
        report_basis_column = ", report_basis TEXT" if report_basis is not None else ""
        connection.execute(
            f"""
            CREATE TABLE fundamental_statement_items (
                stock_code TEXT NOT NULL,
                statement_type TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                announced_date TEXT,
                available_at TEXT,
                item_code TEXT NOT NULL,
                item_name TEXT,
                value TEXT,
                source TEXT,
                source_version TEXT,
                quality TEXT{report_basis_column}
            )
            """
        )
        columns = (
            "stock_code, statement_type, period, as_of_date, announced_date, "
            "available_at, item_code, item_name, value, source, source_version, quality"
        )
        values: tuple[object, ...] = (
            "2330",
            "income_statement",
            "2024-Q1",
            "2024-03-31",
            None,
            "2024-04-05",
            "Revenue",
            "Revenue",
            "100",
            source,
            source_version,
            "accepted",
        )
        if report_basis is not None:
            columns += ", report_basis"
            values += (report_basis,)
        connection.execute(
            f"INSERT INTO fundamental_statement_items({columns}) VALUES ({', '.join('?' for _ in values)})",
            values,
        )


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _read_jsonl_gzip(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _assert_no_float(value: object) -> None:
    assert not isinstance(value, float)
    if isinstance(value, dict):
        for nested in value.values():
            _assert_no_float(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_float(nested)


def test_exporter_streams_bounded_formal_and_shadow_shards_without_db_write(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source.db"
    _build_database(database)
    before_hash = _sha256(database)
    before_stat = database.stat()
    output = tmp_path / "shards"

    publication = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=output,
            decision_at="2024-02-15",
            history_start_date="2023-01-01",
            symbols=("2330",),
            years=(2024,),
            batch_size=3,
        )
    )

    manifest = _json(publication.manifest_path)
    assert manifest["partition_basis"] == "available_at_taipei_year"
    assert manifest["execution"]["sqlite_mode"] == "ro"
    assert manifest["execution"]["query_only"] is True
    assert manifest["execution"]["streaming_fetchmany"] is True
    assert manifest["execution"]["parquet_dependency_added"] is False
    assert manifest["scope"]["all_universe"] is False
    assert manifest["scope"]["symbols"] == ["2330"]
    assert manifest["pit"]["unknown_columns_fail_closed"] is True
    assert manifest["pit"]["source_unreviewed_count"] == 2

    enriched_manifest = _json(
        publication.dataset_manifest_paths["all_field_enriched"]
    )
    shadow_manifest = _json(
        publication.dataset_manifest_paths["research_shadow_all_fields"]
    )
    assert enriched_manifest["included_statuses"] == ["formal_backfill"]
    assert shadow_manifest["included_statuses"] == ["research_shadow"]
    assert enriched_manifest["safety"]["research_shadow_isolated"] is True
    assert enriched_manifest["safety"]["unreviewed_included"] is False
    assert {
        feature["eligibility_status"]
        for feature in enriched_manifest["features"]
    } == {"formal_backfill"}
    assert {
        feature["eligibility_status"]
        for feature in shadow_manifest["features"]
    } == {"research_shadow"}

    enriched_shard = (
        publication.publication_directory
        / enriched_manifest["shards"][0]["path"]
    )
    shadow_shard = (
        publication.publication_directory
        / shadow_manifest["shards"][0]["path"]
    )
    enriched_rows = _read_jsonl_gzip(enriched_shard)
    shadow_rows = _read_jsonl_gzip(shadow_shard)
    assert all(row["entity_id"].startswith("2330") for row in enriched_rows)
    assert all(row["entity_id"].startswith("2330") for row in shadow_rows)
    assert not any(
        row["source_table"] == "fundamental_monthly_revenues"
        and row["available_at"].startswith("2024-01-15")
        for row in enriched_rows
    )
    assert not any(
        row.get("revision_id") in {"r0", "r2"} for row in enriched_rows
    )
    assert {
        row["source_table"] for row in shadow_rows
    } == {"fundamental_monthly_revenues", "institutional_flows"}
    assert not any(
        value["feature_id"].endswith("new_unreviewed_metric")
        or value["feature_id"].endswith("new_field")
        for row in enriched_rows
        for value in row["values"]
    )
    close_values = [
        value
        for row in enriched_rows
        for value in row["values"]
        if value["feature_id"] == "daily_prices.收盤價"
    ]
    assert close_values[0]["value_int"] == 1_000_000
    assert close_values[0]["scale"] == 10_000
    _assert_no_float(manifest)
    _assert_no_float(enriched_rows)
    _assert_no_float(shadow_rows)

    after_stat = database.stat()
    assert _sha256(database) == before_hash
    assert (after_stat.st_size, after_stat.st_mtime_ns) == (
        before_stat.st_size,
        before_stat.st_mtime_ns,
    )


def test_atr_adx_are_causally_recomputed_from_ordered_prefix_and_fail_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source.db"
    _build_database(database)
    publication = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=tmp_path / "shards",
            decision_at="2024-02-15T08:30:00+08:00",
            history_start_date="2024-01-01",
            symbols=("2330",),
            years=(2024,),
            batch_size=2,
        )
    )
    enriched_manifest = _json(
        publication.dataset_manifest_paths["all_field_enriched"]
    )
    shard_path = (
        publication.publication_directory
        / enriched_manifest["shards"][0]["path"]
    )
    rows = [
        row
        for row in _read_jsonl_gzip(shard_path)
        if row["source_table"] == "daily_prices"
        and row["source_id"] == "derived:daily_prices.ohlc"
    ]
    atr_values = [
        next(
            value
            for value in row["values"]
            if value["feature_id"] == "technical_indicators.ATR"
        )
        for row in rows
    ]
    adx_values = [
        next(
            value
            for value in row["values"]
            if value["feature_id"] == "technical_indicators.ADX"
        )
        for row in rows
    ]

    assert all(value["value_int"] is None for value in atr_values[:13])
    assert atr_values[13]["value_int"] == 40_000
    assert atr_values[13]["derivation"]["blocker"] is None
    assert atr_values[13]["derivation"]["causal_prefix_only"] is True
    assert atr_values[13]["derivation"]["raw_feature_value_ignored"] is True
    assert atr_values[13]["derivation"]["usable_from"].startswith("2024-01-14")
    assert all(value["value_int"] is None for value in adx_values[:26])
    assert adx_values[26]["value_int"] == 1_000_000
    assert adx_values[26]["derivation"]["blocker"] is None
    assert adx_values[26]["source_value_hash"].startswith("sha256:")
    assert adx_values[26]["derivation"]["derivation_hash"].startswith("sha256:")
    assert atr_values[0]["formal_training_eligible"] is False
    assert atr_values[0]["missing_mask"] is True
    assert (
        atr_values[0]["derivation"]["blocker"]
        == "atr_prefix_warmup_lt_14"
    )

    atr_feature = next(
        feature
        for feature in enriched_manifest["features"]
        if feature["feature_id"] == "technical_indicators.ATR"
    )
    assert atr_feature["source_id"] == "derived:daily_prices.ohlc"
    assert atr_feature["derivation_policy"]["warmup_fail_closed"] is True
    assert atr_feature["derivation_policy"]["raw_null_or_existing_value_used"] is False


def test_all_universe_and_atomic_replay_keep_old_publication_pointer_safe(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source.db"
    _build_database(database)
    request = PITYearShardBuildRequest(
        database_path=database,
        output_root=tmp_path / "shards",
        decision_at="2024-02-15",
        history_start_date="2024-01-01",
        symbols=None,
        years=(2024,),
        batch_size=7,
    )

    first = PITYearShardExporter().build(request)
    second = PITYearShardExporter().build(request)

    assert first.publication_id == second.publication_id
    assert first.manifest_hash == second.manifest_hash
    runs = [path for path in (request.output_root / "runs").iterdir()]
    assert runs == [first.publication_directory]
    pointer = _json(second.latest_manifest_path)
    assert pointer["publication_id"] == first.publication_id
    core_manifest = _json(first.dataset_manifest_paths["core_long_history"])
    core_rows = _read_jsonl_gzip(
        first.publication_directory / core_manifest["shards"][0]["path"]
    )
    assert any(row["entity_id"] == "2330" for row in core_rows)
    assert any(row["entity_id"] == "2317" for row in core_rows)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "20240104",
                "2454",
                "聯發科",
                3000,
                "905.00",
                "895.00",
                "900.00",
                "blocked",
            ),
        )
    third = PITYearShardExporter().build(request)
    assert third.publication_id != first.publication_id
    assert first.publication_directory.exists()
    assert _json(third.latest_manifest_path)["publication_id"] == third.publication_id


def test_requested_empty_year_has_explicit_zero_row_shard(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    _build_database(database)
    publication = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=tmp_path / "shards",
            decision_at="2025-02-15",
            history_start_date="2023-01-01",
            symbols=("2330",),
            years=(2025,),
        )
    )

    for path in publication.dataset_manifest_paths.values():
        manifest = _json(path)
        assert manifest["shard_count"] == 1
        assert manifest["shards"][0]["year"] == 2025
        assert manifest["shards"][0]["row_count"] == 0
        shard = publication.publication_directory / manifest["shards"][0]["path"]
        assert _read_jsonl_gzip(shard) == []


def test_request_rejects_implicit_empty_universe_and_invalid_batch(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="symbols"):
        PITYearShardBuildRequest(
            database_path=tmp_path / "source.db",
            output_root=tmp_path,
            decision_at="2024-01-01",
            symbols=(),
        )
    with pytest.raises(ValueError, match="batch_size"):
        PITYearShardBuildRequest(
            database_path=tmp_path / "source.db",
            output_root=tmp_path,
            decision_at="2024-01-01",
            symbols=None,
            batch_size=0,
        )


def test_statement_report_basis_survives_into_shadow_shard_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "statement-basis.db"
    _build_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE fundamental_statement_items (
                stock_code TEXT NOT NULL,
                statement_type TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                announced_date TEXT,
                available_at TEXT,
                item_code TEXT NOT NULL,
                item_name TEXT,
                value TEXT,
                source TEXT,
                source_version TEXT,
                quality TEXT,
                report_basis TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO fundamental_statement_items(
                stock_code, statement_type, period, as_of_date,
                announced_date, available_at, item_code, item_name,
                value, source, source_version, quality, report_basis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "2330",
                    "income_statement",
                    "2023-Q4",
                    "2023-12-31",
                    None,
                    "2024-01-05",
                    "Revenue",
                    "Revenue",
                    "100",
                    "official",
                    "basis-c",
                    "accepted",
                    "consolidated",
                ),
                (
                    "2330",
                    "income_statement",
                    "2024-Q1",
                    "2024-03-31",
                    None,
                    "2024-04-05",
                    "Revenue",
                    "Revenue",
                    "110",
                    "official",
                    "basis-i",
                    "accepted",
                    "individual",
                ),
            ),
        )

    publication = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=tmp_path / "shards",
            decision_at="2024-05-01T08:30:00+08:00",
            history_start_date="2023-01-01",
            symbols=("2330",),
            years=(2024,),
            batch_size=2,
        )
    )
    shadow_manifest = _json(
        publication.dataset_manifest_paths["research_shadow_all_fields"]
    )
    shadow_rows = [
        row
        for shard in shadow_manifest["shards"]
        for row in _read_jsonl_gzip(
            publication.publication_directory / shard["path"]
        )
        if row["source_table"] == "fundamental_statement_items"
    ]
    assert {row["entity_id"] for row in shadow_rows} == {
        "2330|income_statement|2023-Q4|Revenue|consolidated",
        "2330|income_statement|2024-Q1|Revenue|individual",
    }
    assert {row["report_basis"] for row in shadow_rows} == {
        "consolidated",
        "individual",
    }


def test_statement_report_basis_legacy_default_requires_known_source_contract(
    tmp_path: Path,
) -> None:
    database = tmp_path / "statement-legacy-basis.db"
    _build_statement_database(
        database,
        source="mops.financial_statement.raw",
        source_version=(
            "mops-t164-consolidated-statements-with-t57sb01-"
            "xbrl-row-codes.v3:content:legacy"
        ),
    )

    publication = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=tmp_path / "shards",
            decision_at="2024-05-01T08:30:00+08:00",
            history_start_date="2024-01-01",
            symbols=("2330",),
            years=(2024,),
            batch_size=2,
        )
    )
    shadow_manifest = _json(
        publication.dataset_manifest_paths["research_shadow_all_fields"]
    )
    shadow_rows = [
        row
        for shard in shadow_manifest["shards"]
        for row in _read_jsonl_gzip(
            publication.publication_directory / shard["path"]
        )
        if row["source_table"] == "fundamental_statement_items"
    ]
    assert len(shadow_rows) == 1
    assert shadow_rows[0]["report_basis"] == "consolidated"
    assert shadow_rows[0]["entity_id"] == "2330|income_statement|2024-Q1|Revenue"


def test_statement_report_basis_unknown_source_cannot_use_implicit_default(
    tmp_path: Path,
) -> None:
    database = tmp_path / "statement-unknown-basis.db"
    _build_statement_database(
        database,
        source="official",
        source_version="basis-without-contract",
    )

    with pytest.raises(ValueError, match="report_basis"):
        PITYearShardExporter().build(
            PITYearShardBuildRequest(
                database_path=database,
                output_root=tmp_path / "shards",
                decision_at="2024-05-01T08:30:00+08:00",
                history_start_date="2024-01-01",
                symbols=("2330",),
                years=(2024,),
                batch_size=2,
            )
        )


def test_statement_report_basis_empty_explicit_value_is_rejected(
    tmp_path: Path,
) -> None:
    database = tmp_path / "statement-empty-basis.db"
    _build_statement_database(
        database,
        source="official",
        source_version="basis-explicit-empty",
        report_basis="",
    )

    with pytest.raises(ValueError, match="report_basis"):
        PITYearShardExporter().build(
            PITYearShardBuildRequest(
                database_path=database,
                output_root=tmp_path / "shards",
                decision_at="2024-05-01T08:30:00+08:00",
                history_start_date="2024-01-01",
                symbols=("2330",),
                years=(2024,),
                batch_size=2,
            )
        )
