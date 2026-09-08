from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path
import sqlite3

import pytest

import data_module.twse_historical_daily_capture as capture_module
from data_module.ml_daily_price_overlay import build_daily_price_overlay
from data_module.ml_daily_price_overlay_consumer import (
    DailyPriceOverlayConsumerError,
    build_daily_price_overlay_impact,
    load_daily_price_overlay_impact,
)
from data_module.twse_historical_daily_capture import capture_twse_historical_daily


_DATE = "2026-05-20"
_SYMBOLS = ("3017", "3037")
_FIELDS = (
    "證券代號",
    "證券名稱",
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
    "成交股數",
)
_OFFICIAL = {
    "3017": ("95", "96", "94", "95", "2000"),
    "3037": ("85", "86", "84", "85", "3000"),
}


def _sessions(start: date, count: int) -> tuple[str, ...]:
    result: list[str] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return tuple(result)


def _official_payload() -> dict[str, object]:
    return {
        "stat": "OK",
        "tables": [
            {
                "fields": list(_FIELDS),
                "data": [
                    [symbol, f"official-{symbol}", *values]
                    for symbol, values in _OFFICIAL.items()
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

    def __init__(self) -> None:
        self.raw = io.BytesIO(
            gzip.compress(
                json.dumps(
                    _official_payload(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
                mtime=0,
            )
        )

    def close(self) -> None:
        self.raw.close()


class _FakeSession:
    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, *args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse()


def _sources(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "sqlite" / "source.sqlite"
    csv_root = tmp_path / "daily_price"
    database.parent.mkdir(parents=True)
    csv_root.mkdir(parents=True)
    decision_sessions = _sessions(date(2026, 5, 20), 20)
    with sqlite3.connect(database) as connection:
        connection.executescript(
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
            );
            CREATE TABLE market_indices (
                日期 TEXT NOT NULL,
                指數名稱 TEXT NOT NULL,
                開盤價 TEXT,
                收盤價 TEXT
            );
            """
        )
        market_rows: list[tuple[object, ...]] = []
        stock_rows: list[tuple[object, ...]] = []
        # 決策日 08:30 的盤前 feature 需要 5/19 與其前一收盤 5/18；
        # 同日 5/20 資料只可作 overlay raw diagnostic 與 supervised entry。
        all_dates = ("20260518", "20260519", *decision_sessions)
        for index, day in enumerate(all_dates):
            market_rows.append((day, "TAIEX", str(1000 + index), str(1001 + index)))
            for symbol_index, symbol in enumerate(_SYMBOLS):
                if day == "20260520":
                    entry = "5" if symbol == "3017" else "10"
                    close = entry
                else:
                    entry = str(100 + symbol_index + index)
                    close = str(101 + symbol_index + index)
                high = str(int(entry) + 2)
                low = str(int(entry) - 2)
                stock_rows.append(
                    (
                        day,
                        symbol,
                        symbol,
                        entry,
                        high,
                        low,
                        close,
                        1000 + index,
                    )
                )
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?, ?, ?)",
            market_rows,
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            stock_rows,
        )
    with (csv_root / "20260520.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        stream.write(
            "證券代號,證券名稱,開盤價,最高價,最低價,收盤價,成交股數\n"
        )
        for symbol, values in _OFFICIAL.items():
            stream.write(f"{symbol},official,{','.join(values)}\n")
    return database, csv_root


def _official_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    database, csv_root = _sources(tmp_path)
    monkeypatch.setattr(
        capture_module.requests,
        "Session",
        lambda: _FakeSession(),
    )
    capture = capture_twse_historical_daily(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        date_value=_DATE,
        symbols=_SYMBOLS,
        output_root=tmp_path / "official-capture",
    )
    overlay = build_daily_price_overlay(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        date_value=_DATE,
        symbols=_SYMBOLS,
        official_capture_comparison_path=capture.comparison_path,
        output_path=tmp_path / "overlay" / "official.json",
    )
    return database, overlay


def test_consumer_recomputes_isolated_features_and_labels_without_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, overlay = _official_overlay(tmp_path, monkeypatch)
    database_before = database.read_bytes()
    output = build_daily_price_overlay_impact(
        overlay_path=overlay,
        sqlite_path=database,
        output_path=tmp_path / "impact" / "impact.json",
    )

    payload = load_daily_price_overlay_impact(output.output_path)
    assert payload["scope"]["row_count"] == 2
    assert payload["observed_at_utc"].startswith("2026-")
    assert payload["historical_decision_time_available"] is False
    assert payload["schema_version"] == "portfolio-ml-daily-price-overlay-impact.v2"
    assert payload["research_mode"] == "post_capture_historical_research.v2"
    assert payload["overlay_selection"]["original_sqlite_retained"] is True
    assert payload["overlay_selection"]["raw_overlay_values_used_for_model_features"] is False
    assert payload["retrained"] is False
    assert payload["verification"]["official_rows_verified"] == 2
    assert payload["verification"]["changed_feature_count"] > 0
    assert payload["verification"]["raw_diagnostic_changed_feature_count"] == 12
    assert payload["verification"]["decision_time_feature_changed_count"] == 0
    assert payload["verification"]["model_feature_impact_claimed"] is False
    assert payload["verification"]["changed_label_count"] > 0
    row = next(item for item in payload["impacts"] if item["symbol"] == "3017")
    assert row["observed_at_utc"] == payload["observed_at_utc"]
    assert row["historical_decision_time_available"] is False
    assert row["raw_price_diagnostic"]["daily_prices.open"]["original"] == "5"
    assert row["raw_price_diagnostic"]["daily_prices.open"]["candidate"] == "95"
    assert row["raw_price_diagnostic"]["daily_prices.open"]["feature_role"] == (
        "post_close_raw_price_diagnostic_only"
    )
    assert row["features"] == row["decision_time_features"]
    decision_feature = row["decision_time_features"]["daily_prices.close"]
    assert decision_feature["source_date"] == "2026-05-19"
    assert decision_feature["available_before_decision"] is True
    assert decision_feature["used_for_model_features"] is True
    assert decision_feature["intraday_available_at"] is None
    assert row["source_lineage"]["future_rows_used_as_features"] is False
    assert row["labels"]["original"]["benchmark_excess_return_bp"] != row[
        "labels"
    ]["candidate"]["benchmark_excess_return_bp"]
    evidence = row["labels"]["candidate"]["return_evidence"]
    assert evidence["stock_entry_date"] == _DATE
    assert evidence["stock_exit_date"] == row["labels"]["candidate"]["horizon_end_date"]
    assert evidence["transaction_cost_bp"] == 80
    assert evidence["stock_return_bp"] - evidence["benchmark_return_bp"] - evidence[
        "transaction_cost_bp"
    ] == row["labels"]["candidate"]["benchmark_excess_return_bp"]
    assert database.read_bytes() == database_before


def test_consumer_rejects_same_day_or_late_feature_source(
) -> None:
    """同日收盤／成交量晚於 08:30 時不得被當成 model input。"""

    from data_module.ml_daily_price_overlay_consumer import (
        _PricePoint,
        _decision_time_feature_payload,
    )
    point = _PricePoint(
        date=_DATE,
        symbol="3017",
        open=Decimal("95"),
        high=Decimal("96"),
        low=Decimal("94"),
        close=Decimal("95"),
        volume_shares=2000,
    )
    with pytest.raises(DailyPriceOverlayConsumerError, match="same-day or future"):
        _decision_time_feature_payload(
            previous_session=point,
            previous_close=Decimal("94"),
            decision_date=_DATE,
        )
    prior_point = _PricePoint(
        date="2026-05-19",
        symbol="3017",
        open=Decimal("95"),
        high=Decimal("96"),
        low=Decimal("94"),
        close=Decimal("95"),
        volume_shares=2000,
    )
    with pytest.raises(DailyPriceOverlayConsumerError, match="late price source"):
        _decision_time_feature_payload(
            previous_session=prior_point,
            previous_close=Decimal("94"),
            decision_date=_DATE,
            source_available_at="2026-05-20T14:30:00+08:00",
        )


def test_loader_rejects_rehashed_same_day_v2_feature_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """即使攻擊者重算 outer hash，也不能把同日資料改成盤前 feature。"""

    from data_module.ml_daily_price_overlay_consumer import _payload_hash

    database, overlay = _official_overlay(tmp_path, monkeypatch)
    output = build_daily_price_overlay_impact(
        overlay_path=overlay,
        sqlite_path=database,
        output_path=tmp_path / "impact" / "valid.json",
    )
    payload = json.loads(output.output_path.read_text(encoding="utf-8"))
    payload["impacts"][0]["decision_time_features"]["daily_prices.close"][
        "source_date"
    ] = _DATE
    body = dict(payload)
    body.pop("impact_hash", None)
    body["impact_hash"] = _payload_hash(body)
    blocked = tmp_path / "impact" / "same-day.json"
    blocked.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(
        DailyPriceOverlayConsumerError,
        match="not proven before decision",
    ):
        load_daily_price_overlay_impact(blocked)


def test_independent_decimal_audit_recomputes_return_and_cost_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.audit_ml_daily_price_overlay_impact import audit_overlay_impact

    database, overlay = _official_overlay(tmp_path, monkeypatch)
    impact = build_daily_price_overlay_impact(
        overlay_path=overlay,
        sqlite_path=database,
        output_path=tmp_path / "impact" / "impact.json",
    )
    audit_path = audit_overlay_impact(
        impact_path=impact.output_path,
        output_path=tmp_path / "audit" / "decimal.json",
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["status"] == "verified_decimal_return_evidence"
    assert audit["rows_verified"] == 2
    assert audit["cost_policy"] == {
        "buy_cost_bp": 25,
        "sell_cost_bp": 55,
        "transaction_cost_bp": 80,
    }


def test_consumer_requires_official_receipt_and_rejects_tampered_binding(
    tmp_path: Path,
) -> None:
    database, csv_root = _sources(tmp_path)
    overlay = build_daily_price_overlay(
        sqlite_path=database,
        canonical_daily_price_dir=csv_root,
        date_value=_DATE,
        symbols=_SYMBOLS,
        output_path=tmp_path / "overlay" / "candidate.json",
    )
    with pytest.raises(
        DailyPriceOverlayConsumerError,
        match="official response receipt",
    ):
        build_daily_price_overlay_impact(
            overlay_path=overlay,
            sqlite_path=database,
            output_path=tmp_path / "impact" / "blocked.json",
        )


def test_consumer_output_is_immutable_and_rejects_incomplete_market_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, overlay = _official_overlay(tmp_path, monkeypatch)
    output = tmp_path / "impact" / "impact.json"
    first = build_daily_price_overlay_impact(
        overlay_path=overlay,
        sqlite_path=database,
        output_path=output,
    )
    output_before = output.read_bytes()
    second = build_daily_price_overlay_impact(
        overlay_path=overlay,
        sqlite_path=database,
        output_path=output,
    )
    assert first.output_hash == second.output_hash
    assert output.read_bytes() == output_before

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM market_indices WHERE 日期=?",
            ("20260616",),
        )
    with pytest.raises(DailyPriceOverlayConsumerError, match="complete"):
        build_daily_price_overlay_impact(
            overlay_path=overlay,
            sqlite_path=database,
            output_path=tmp_path / "impact" / "blocked.json",
        )
