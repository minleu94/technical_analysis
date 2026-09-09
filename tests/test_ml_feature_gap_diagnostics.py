from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

import pytest

from ml_module.feature_gap_diagnostics import (
    FeatureGapDiagnosticError,
    diagnose_sqlite_feature_gaps,
)
from scripts.inspect_ml_feature_gap import main as inspect_feature_gap_main


def _fixture_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE market_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                收盤價 REAL,
                漲跌點數 REAL,
                漲跌百分比 REAL
            );
            CREATE TABLE technical_indicators (
                日期 TEXT,
                證券代號 TEXT,
                [涨跌] REAL,
                [漲跌(+/-)] REAL,
                漲跌價差 REAL
            );
            CREATE TABLE daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                [漲跌(+/-)] TEXT,
                漲跌價差 REAL,
                收盤價 REAL
            );
            """
        )
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?, ?, ?, ?, ?)",
            (
                ("20260903", "TAIEX", 45857.66, 45857.66, None, None),
                ("20260904", "TAIEX", 46551.13, 46551.13, None, None),
            ),
        )
        symbols = ("1101", "2330")
        connection.executemany(
            "INSERT INTO technical_indicators VALUES (?, ?, ?, ?, ?)",
            tuple(
                ("20260904", symbol, None, None, 0.15)
                for symbol in symbols
            ),
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?)",
            tuple(
                ("20260904", symbol, "+", 0.15, 100.0)
                for symbol in symbols
            ),
        )


def test_gap_diagnostic_derives_market_and_keeps_technical_legacy_missing(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source.sqlite"
    _fixture_database(database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    report = diagnose_sqlite_feature_gaps(
        database,
        expected_price_date="2026-09-04",
        previous_price_date="2026-09-03",
        symbols=("2330", "1101"),
    )

    assert report["source_read_only"] is True
    assert report["bounded_query"] is True
    market = report["market_source_evidence"]
    assert market["close_pair_available"] is True
    assert market["derived_values"]["point_delta_value_int_scale_10000"] == 6_934_700
    assert market["derived_values"]["percent_delta_value_int_scale_10000"] == 15_122
    assert report["features"]["market_indices.漲跌點數"][
        "resolution"
    ] == "derive_from_official_close_pair"
    assert report["features"]["market_indices.漲跌點數"][
        "source_non_null_count"
    ] == 0

    technical = report["technical_source_evidence"]
    assert technical["technical_change_non_null"]["simplified"] == 0
    assert technical["technical_change_non_null"]["direction"] == 0
    assert technical["technical_change_non_null"]["price_delta"] == 2
    assert technical["daily_price_source_non_null"]["direction"] == 2
    assert report["features"]["technical_indicators.涨跌"][
        "resolution"
    ] == "exclude_from_numeric_contract"
    assert report["repair_decision"]["zero_fill"] is False
    assert report["repair_decision"]["sqlite_source_write"] is False
    scope = report["evidence_scope"]
    assert scope["cross_scope_join_allowed"] is False
    assert scope["current_bounded_sqlite_probe"]["expected_price_date"] == "2026-09-04"  # type: ignore[index]
    assert scope["current_bounded_sqlite_probe"]["previous_price_date"] == "2026-09-03"  # type: ignore[index]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_gap_diagnostic_rejects_non_monotonic_dates(tmp_path: Path) -> None:
    database = tmp_path / "source.sqlite"
    _fixture_database(database)
    with pytest.raises(
        FeatureGapDiagnosticError,
        match="previous_price_date must precede expected_price_date",
    ):
        diagnose_sqlite_feature_gaps(
            database,
            expected_price_date="2026-09-03",
            previous_price_date="2026-09-04",
            symbols=("2330",),
        )


def test_gap_diagnostic_rejects_impossible_compact_date(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source.sqlite"
    _fixture_database(database)
    with pytest.raises(
        FeatureGapDiagnosticError,
        match="real YYYY-MM-DD or YYYYMMDD dates",
    ):
        diagnose_sqlite_feature_gaps(
            database,
            expected_price_date="20261399",
            previous_price_date="20260903",
            symbols=("2330",),
        )


def test_gap_diagnostic_cli_writes_machine_evidence(tmp_path: Path) -> None:
    database = tmp_path / "source.sqlite"
    output = tmp_path / "gap.json"
    _fixture_database(database)

    assert inspect_feature_gap_main(
        [
            "--database",
            str(database),
            "--expected-price-date",
            "20260904",
            "--previous-price-date",
            "20260903",
            "--symbols",
            "2330",
            "1101",
            "--output",
            str(output),
        ]
    ) == 0
    payload = output.read_text(encoding="utf-8")
    assert '"schema_version": "v4-ml-feature-gap-diagnostic.v1"' in payload
    assert '"bounded_query": true' in payload
