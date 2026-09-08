from __future__ import annotations

import csv
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

import pytest

import data_module.ml_daily_price_source_quality as quality_module
from data_module.ml_daily_price_source_quality import (
    DailyPriceSourceQualityError,
    assert_daily_price_source_quality,
    audit_daily_price_source,
    write_quarantine_report,
)
from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)


_CSV_COLUMNS = (
    "證券代號",
    "證券名稱",
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
    "成交股數",
)


def _build_database(
    path: Path,
    *,
    current_open: str,
    current_close: str,
    current_high: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE daily_prices (
                日期 TEXT NOT NULL,
                證券代號 TEXT NOT NULL,
                證券名稱 TEXT,
                開盤價 TEXT,
                最高價 TEXT,
                最低價 TEXT,
                收盤價 TEXT,
                成交股數 INTEGER
            )
            """
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ("20260519", "3017", "奇鋐", "100", "105", "95", "100", 1000),
                (
                    "20260520",
                    "3017",
                    "奇鋐",
                    current_open,
                    current_open if current_high is None else current_high,
                    current_open,
                    current_close,
                    1000,
                ),
                ("20260521", "3017", "奇鋐", "120", "125", "115", "120", 1000),
            ),
        )


def _write_csv(
    directory: Path,
    *,
    current_open: str,
    current_close: str,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "20260520.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        high = max(Decimal(current_open), Decimal(current_close))
        low = min(Decimal(current_open), Decimal(current_close))
        writer.writerow(
            {
                "證券代號": "3017",
                "證券名稱": "奇鋐",
                "開盤價": current_open,
                "最高價": format(high, "f"),
                "最低價": format(low, "f"),
                "收盤價": current_close,
                "成交股數": "1,000",
            }
        )
    return path


def test_source_mismatch_is_quarantined_without_source_write(tmp_path: Path) -> None:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    _build_database(database, current_open="5", current_close="5")
    canonical = _write_csv(
        csv_root,
        current_open="95",
        current_close="96",
    )
    before = database.read_bytes()

    report = audit_daily_price_source(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        start_date="2026-05-20",
        end_date="2026-05-20",
    )

    assert report["status"] == "quarantine_required"
    assert report["candidate_count"] == 1
    candidate = report["candidates"][0]
    assert candidate["classification"] == (
        "sqlite_row_mismatch_against_canonical_daily_csv"
    )
    assert set(candidate["differing_fields"]) >= {"open", "close"}
    assert candidate["canonical_file"]["file_sha256"].startswith("sha256:")
    assert candidate["canonical_file"]["path"] == str(canonical.resolve())
    assert report["labels_mutated"] is False
    assert report["quality_timing"]["quality_mode"] == "retrospective_audit"
    assert report["quality_timing"]["uses_future_source_rows"] is True
    assert database.read_bytes() == before

    with pytest.raises(DailyPriceSourceQualityError):
        assert_daily_price_source_quality(
            sqlite_path=database,
            canonical_daily_price_dir=csv_root,
            start_date="2026-05-20",
            end_date="2026-05-20",
        )


def test_canonical_raw_anomaly_is_quarantined_even_when_sqlite_matches(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    _build_database(database, current_open="5", current_close="5")
    _write_csv(csv_root, current_open="5", current_close="5")

    report = audit_daily_price_source(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        start_date="2026-05-20",
        end_date="2026-05-20",
    )

    candidate = report["candidates"][0]
    assert candidate["classification"] == (
        "canonical_daily_row_has_scale_discontinuity"
    )
    assert candidate["differing_fields"] == []
    assert report["formal_training_allowed"] is False


def test_ingest_guard_never_reads_late_next_source_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    _build_database(database, current_open="5", current_close="5")
    _write_csv(csv_root, current_open="95", current_close="96")
    original_reader = quality_module._canonical_csv_rows
    observed_paths: list[str] = []

    def recording_reader(path: Path):
        observed_paths.append(path.name)
        return original_reader(path)

    monkeypatch.setattr(quality_module, "_canonical_csv_rows", recording_reader)
    report = audit_daily_price_source(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        start_date="2026-05-20",
        end_date="2026-05-20",
        quality_mode="ingest_guard",
    )

    assert report["status"] == "quarantine_required"
    assert report["quality_timing"] == {
        "quality_mode": "ingest_guard",
        "uses_future_source_rows": False,
        "future_source_row_used": False,
        "quality_known_at": None,
        "quality_known_at_status": "source_receipt_time_not_supplied",
        "historical_retroactive_filtering_allowed": False,
    }
    assert "20260521.csv" not in observed_paths
    candidate = report["candidates"][0]
    assert candidate["detector"]["next_open"] is None
    assert candidate["detector"]["future_source_row_used"] is False
    assert candidate["canonical_context"]["next"] is None
    assert candidate["canonical_context"]["next_file"] is None


def test_ingest_guard_quarantines_null_sqlite_row_without_silent_drop(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    _build_database(database, current_open="95", current_close="96")
    _write_csv(csv_root, current_open="95", current_close="96")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE daily_prices SET 開盤價 = NULL WHERE 日期 = ?",
            ("20260520",),
        )

    report = audit_daily_price_source(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        start_date="2026-05-20",
        end_date="2026-05-20",
        quality_mode="ingest_guard",
    )

    assert report["status"] == "quarantine_required"
    assert report["candidate_count"] == 1
    candidate = report["candidates"][0]
    assert candidate["classification"] == (
        "sqlite_row_invalid_requires_quarantine"
    )
    assert candidate["sqlite_row"]["open"] is None
    assert candidate["canonical_row"]["open"] == "95"
    assert candidate["detector"]["future_source_row_used"] is False


def test_quality_known_at_requires_aware_receipt_time(tmp_path: Path) -> None:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    _build_database(
        database,
        current_open="95",
        current_close="96",
        current_high="96",
    )
    _write_csv(csv_root, current_open="95", current_close="96")

    with pytest.raises(ValueError, match="timezone-aware"):
        audit_daily_price_source(
            sqlite_path=database,
            canonical_daily_price_dir=csv_root,
            start_date="2026-05-20",
            end_date="2026-05-20",
            quality_mode="ingest_guard",
            quality_known_at="2026-05-20T08:30:00",
        )

    report = audit_daily_price_source(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        start_date="2026-05-20",
        end_date="2026-05-20",
        quality_mode="ingest_guard",
        quality_known_at="2026-05-20T08:30:00+08:00",
    )
    assert report["quality_timing"]["quality_known_at"] == (
        "2026-05-20T08:30:00+08:00"
    )


def test_clean_source_passes_and_quarantine_output_is_atomic(tmp_path: Path) -> None:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    _build_database(
        database,
        current_open="95",
        current_close="96",
        current_high="96",
    )
    _write_csv(csv_root, current_open="95", current_close="96")

    report = assert_daily_price_source_quality(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        start_date="2026-05-20",
        end_date="2026-05-20",
    )
    assert report["status"] == "source_quality_pass"
    output = tmp_path / "qa" / "source_quality.json"
    written = write_quarantine_report(
        output,
        report,
        source_roots=(database.parent, csv_root),
    )
    assert written == output.resolve()
    assert output.is_file()
    assert output.read_text(encoding="utf-8").endswith("\n")
    assert write_quarantine_report(
        output,
        report,
        source_roots=(database.parent, csv_root),
    ) == output.resolve()


def test_quarantine_report_cannot_overwrite_source_root(tmp_path: Path) -> None:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    _build_database(database, current_open="95", current_close="96")
    _write_csv(csv_root, current_open="95", current_close="96")
    report = audit_daily_price_source(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        start_date="2026-05-20",
        end_date="2026-05-20",
    )

    with pytest.raises(ValueError, match="outside source roots"):
        write_quarantine_report(
            csv_root / "forbidden.json",
            report,
            source_roots=(database.parent, csv_root),
        )


def test_pit_builder_runs_source_guard_before_creating_publication(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    _build_database(database, current_open="5", current_close="5")
    _write_csv(csv_root, current_open="95", current_close="96")
    output = tmp_path / "publication"

    with pytest.raises(DailyPriceSourceQualityError, match="quarantine required"):
        PITYearShardExporter().build(
            PITYearShardBuildRequest(
                database_path=database,
                output_root=output,
                decision_at="2026-05-21T08:30:00+08:00",
                history_start_date="2026-05-20",
                symbols=("3017",),
                years=(2026,),
                daily_price_source_dir=csv_root,
                source_quality_report_path=tmp_path / "qa" / "source.json",
            )
        )
    assert not output.exists()
    report_path = tmp_path / "qa" / "source.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["quality_timing"]["quality_mode"] == "ingest_guard"
    assert report["quality_timing"]["uses_future_source_rows"] is False
