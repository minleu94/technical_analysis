import pandas as pd
from datetime import date

from app_module.market_breadth_service import MarketBreadthProvider, MarketBreadthService
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
