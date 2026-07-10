from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app_module.decision_market_frame import DecisionMarketFrameLoader


def _seed_daily_prices(tmp_path: Path) -> Path:
    db_path = tmp_path / "market.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE daily_prices (
                日期 TEXT NOT NULL,
                證券代號 TEXT NOT NULL,
                收盤價 TEXT,
                漲跌價差 TEXT,
                成交股數 TEXT
            )
            """
        )
        start = date(2025, 11, 1)
        rows = []
        for offset in range(70):
            trade_date = start + timedelta(days=offset)
            for stock_code, price in (("2330", 100 + offset), ("2317", 80 + offset)):
                rows.append(
                    (
                        trade_date.strftime("%Y%m%d"),
                        stock_code,
                        str(price),
                        "1",
                        str(1000 + offset),
                    )
                )
        conn.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    return db_path


def test_loader_reuses_largest_frame_within_snapshot(tmp_path, monkeypatch) -> None:
    db_path = _seed_daily_prices(tmp_path)
    loader = DecisionMarketFrameLoader(db_path)
    calls = 0
    original = loader._read_frame

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(loader, "_read_frame", counted)
    target = date(2026, 1, 9)

    loader.reset(target)
    large = loader.load(target, 61)
    small = loader.load(target, 40)
    prices = loader.load_recent_prices("2330", target, 60)

    assert calls == 1
    assert large["日期"].nunique() == 61
    assert small["日期"].nunique() == 40
    assert len(prices) == 60
    assert prices[0][0] == target
    assert prices[0][1] == Decimal("169")

    loader.reset(target)
    loader.load(target, 61)
    assert calls == 2


def test_loader_reloads_when_larger_window_is_requested(tmp_path, monkeypatch) -> None:
    loader = DecisionMarketFrameLoader(_seed_daily_prices(tmp_path))
    target = date(2026, 1, 9)
    calls = 0
    original = loader._read_frame

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(loader, "_read_frame", counted)
    loader.reset(target)
    loader.load(target, 20)
    loader.load(target, 61)

    assert calls == 2


def test_loader_never_returns_rows_after_as_of_date(tmp_path) -> None:
    loader = DecisionMarketFrameLoader(_seed_daily_prices(tmp_path))
    target = date(2025, 12, 15)

    frame = loader.load(target, 61)

    normalized_dates = frame["日期"].astype(str).str.replace("-", "", regex=False)
    assert normalized_dates.max() <= target.strftime("%Y%m%d")
