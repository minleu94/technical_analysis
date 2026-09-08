from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path
import sqlite3

import pytest

import data_module.twse_historical_daily_capture as capture_module
from data_module.ml_daily_price_overlay import (
    DailyPriceOverlayError,
    build_daily_price_overlay,
    load_daily_price_overlay,
    overlay_rows,
)
from data_module.twse_historical_daily_capture import (
    capture_twse_historical_daily,
)


_COLUMNS = (
    "證券代號",
    "證券名稱",
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
    "成交股數",
)


def _fixture_sources(tmp_path: Path) -> tuple[Path, Path, tuple[str, ...]]:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    symbols = ("3017", "3037")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE daily_prices ("
            "日期 TEXT NOT NULL, 證券代號 TEXT NOT NULL, 證券名稱 TEXT, "
            "開盤價 TEXT, 最高價 TEXT, 最低價 TEXT, 收盤價 TEXT, 成交股數 INTEGER)"
        )
        for symbol in symbols:
            connection.executemany(
                "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ("20260519", symbol, "fixture", "100", "105", "95", "100", 1000),
                    ("20260520", symbol, "fixture", "5", "5", "5", "5", 1000),
                ),
            )
    csv_root.mkdir(parents=True, exist_ok=True)
    with (csv_root / "20260520.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
        writer.writeheader()
        for symbol in symbols:
            writer.writerow(
                {
                    "證券代號": symbol,
                    "證券名稱": "canonical",
                    "開盤價": "95",
                    "最高價": "95",
                    "最低價": "95",
                    "收盤價": "95",
                    "成交股數": "2000",
                }
            )
    return database, csv_root, symbols


def _official_fixture_payload(symbols: tuple[str, ...]) -> dict[str, object]:
    return {
        "stat": "OK",
        "tables": [
            {
                "fields": list(_COLUMNS),
                "data": [
                    [symbol, "official", "95", "95", "95", "95", "2000"]
                    for symbol in symbols
                ],
            }
        ],
    }


class _FakeResponse:
    status_code = 200
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?fixture"
    headers = {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
    }

    def __init__(self, payload: dict[str, object]) -> None:
        self.raw = io.BytesIO(
            gzip.compress(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                mtime=0,
            )
        )

    def close(self) -> None:
        self.raw.close()


class _FakeSession:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, *args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(self.payload)


def test_overlay_covers_every_candidate_and_preserves_sources(tmp_path: Path) -> None:
    database, csv_root, symbols = _fixture_sources(tmp_path)
    database_before = database.read_bytes()
    csv_before = (csv_root / "20260520.csv").read_bytes()
    output = build_daily_price_overlay(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        date_value="20260520",
        symbols=symbols,
        output_path=tmp_path / "output" / "overlay.json",
    )

    payload = load_daily_price_overlay(output)
    assert payload["scope"] == {
        "date": "2026-05-20",
        "symbols": list(symbols),
        "row_count": 2,
    }
    assert payload["source_lineage"]["official_raw_response_receipt_present"] is False
    assert payload["source_lineage"]["lineage_status"].startswith("candidate_only")
    rows = overlay_rows(output, date_value="2026-05-20")
    assert tuple(row["symbol"] for row in rows) == symbols
    assert all(row["overlay_row"]["open"] == "95" for row in rows)
    assert database.read_bytes() == database_before
    assert (csv_root / "20260520.csv").read_bytes() == csv_before


def test_overlay_rejects_partial_candidate_scope(tmp_path: Path) -> None:
    database, csv_root, symbols = _fixture_sources(tmp_path)
    with pytest.raises(DailyPriceOverlayError, match="every requested symbol"):
        build_daily_price_overlay(
            sqlite_path=database,
            canonical_daily_price_dir=csv_root,
            date_value="20260520",
            symbols=(*symbols, "9999"),
            output_path=tmp_path / "output" / "overlay.json",
        )


def test_overlay_binds_official_historical_capture_without_enabling_training(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, csv_root, symbols = _fixture_sources(tmp_path)
    monkeypatch.setattr(
        capture_module.requests,
        "Session",
        lambda: _FakeSession(_official_fixture_payload(symbols)),
    )
    capture = capture_twse_historical_daily(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        date_value="20260520",
        symbols=symbols,
        output_root=tmp_path / "official-capture",
    )

    output = build_daily_price_overlay(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        date_value="20260520",
        symbols=symbols,
        official_capture_comparison_path=capture.comparison_path,
        output_path=tmp_path / "output" / "official-overlay.json",
    )

    payload = load_daily_price_overlay(output)
    assert payload["source_lineage"]["official_raw_response_receipt_present"] is True
    assert payload["source_lineage"]["lineage_status"] == (
        "official_historical_response_receipt_bound_candidate_only"
    )
    assert payload["official_capture"]["historical_decision_time_available"] is False
    assert payload["formal_training_allowed"] is False
    assert payload["promotion_eligible"] is False
    rows = overlay_rows(output)
    assert all(row["official_row"]["close"] == "95" for row in rows)
