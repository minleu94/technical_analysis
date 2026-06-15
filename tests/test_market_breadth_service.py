from datetime import date
import sqlite3

import pandas as pd

from app_module.market_breadth_service import (
    MarketBreadthProvider,
    MarketBreadthService,
    SQLiteDailyPriceMarketBreadthProvider,
)
from app_module.decision_desk_dtos import DecisionDeskQuality


class FakeMarketBreadthProvider:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def fetch(self, as_of_date: date) -> pd.DataFrame:
        return self.frame.copy()


class BrokenMarketBreadthProvider:
    def fetch(self, as_of_date: date) -> pd.DataFrame:
        raise RuntimeError("provider temporary unavailable")


def test_market_breadth_service_builds_summary_from_df_with_injected_provider():
    frame = pd.DataFrame(
        {
            "as_of_date": ["2026-06-14", "20260615", "2026-06-16"],
            "advancing": [48, 63, 70],
            "declining": [52, 37, 30],
            "unchanged": [10, 0, 5],
        }
    )
    service = MarketBreadthService(FakeMarketBreadthProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.as_of_date == date(2026, 6, 15)
    assert snapshot.advancing == 63
    assert snapshot.declining == 37
    assert snapshot.breadth_ratio_bp == 6300
    assert snapshot.warnings == ()


def test_market_breadth_service_returns_missing_when_no_match():
    frame = pd.DataFrame(
        {
            "date": ["2026-06-01", "20260614"],
            "advancing": [50, 60],
            "declining": [50, 40],
        }
    )
    service = MarketBreadthService(FakeMarketBreadthProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.MISSING
    assert snapshot.warnings == ("market_breadth_missing",)
    assert snapshot.breadth_ratio_bp is None


def test_market_breadth_service_can_match_target_with_partial_invalid_dates():
    frame = pd.DataFrame(
        {
            "as_of_date": ["bad-date", "20260615", None],
            "advancing": [40, 60, 80],
            "declining": [60, 40, 20],
        }
    )
    service = MarketBreadthService(FakeMarketBreadthProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.as_of_date == date(2026, 6, 15)
    assert snapshot.advancing == 60
    assert snapshot.declining == 40
    assert snapshot.breadth_ratio_bp == 6000
    assert snapshot.warnings == ()


def test_market_breadth_service_returns_degraded_on_invalid_date_format():
    frame = pd.DataFrame(
        {
            "trade_date": ["202606", "20260613"],
            "advancing_count": [10, 20],
            "declining_count": [10, 25],
        }
    )
    service = MarketBreadthService(FakeMarketBreadthProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.MISSING
    assert snapshot.warnings == ("market_breadth_missing",)


def test_market_breadth_service_returns_degraded_on_provider_error():
    service = MarketBreadthService(BrokenMarketBreadthProvider())
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.advancing is None
    assert any("provider temporary unavailable" in w for w in snapshot.warnings)


def test_market_breadth_service_handles_non_contiguous_index_and_matches_target_date():
    frame = pd.DataFrame(
        {
            "as_of_date": ["2026-06-14", "20260615", "2026-06-16"],
            "advancing": [48, 63, 70],
            "declining": [52, 37, 30],
            "unchanged": [10, 0, 5],
        }
    )
    frame.index = [10, 20, 30]

    service = MarketBreadthService(FakeMarketBreadthProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.as_of_date == date(2026, 6, 15)
    assert snapshot.advancing == 63
    assert snapshot.declining == 37
    assert snapshot.breadth_ratio_bp == 6300
    assert snapshot.warnings == ()


def test_sqlite_daily_price_provider_builds_market_breadth_from_daily_prices(tmp_path):
    db_path = tmp_path / "twstock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                收盤價 REAL,
                漲跌價差 REAL,
                成交股數 INTEGER,
                PRIMARY KEY (證券代號, 日期)
            )
            """
        )
        conn.executemany(
            "INSERT INTO daily_prices (日期, 證券代號, 收盤價, 漲跌價差, 成交股數) VALUES (?, ?, ?, ?, ?)",
            [
                ("20260612", "2330", 100, 1, 1_000),
                ("20260612", "2317", 50, -1, 2_000),
                ("20260612", "2454", 75, 0, 1_000),
                ("20260615", "2330", 110, 10, 3_000),
                ("20260615", "2317", 49, -1, 1_000),
                ("20260615", "2454", 75, 0, 2_000),
            ],
        )

    service = MarketBreadthService(SQLiteDailyPriceMarketBreadthProvider(db_path))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.advancing == 1
    assert snapshot.declining == 1
    assert snapshot.unchanged == 1
    assert snapshot.breadth_ratio_bp == 5000
    assert snapshot.meta["source"] == "sqlite_daily_prices"
    assert snapshot.meta["volume_expansion_bp"] == 15000
    assert snapshot.meta["limit_up_count"] == 1


def test_sqlite_daily_price_provider_uses_latest_available_date_with_warning(tmp_path):
    db_path = tmp_path / "twstock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                收盤價 REAL,
                漲跌價差 REAL,
                成交股數 INTEGER,
                PRIMARY KEY (證券代號, 日期)
            )
            """
        )
        conn.executemany(
            "INSERT INTO daily_prices (日期, 證券代號, 收盤價, 漲跌價差, 成交股數) VALUES (?, ?, ?, ?, ?)",
            [
                ("20260612", "2330", 100, 1, 1_000),
                ("20260612", "2317", 50, -1, 2_000),
            ],
        )

    service = MarketBreadthService(SQLiteDailyPriceMarketBreadthProvider(db_path))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.as_of_date == date(2026, 6, 12)
    assert snapshot.advancing == 1
    assert snapshot.declining == 1
    assert "market_breadth_as_of_fallback:2026-06-12" in snapshot.warnings
