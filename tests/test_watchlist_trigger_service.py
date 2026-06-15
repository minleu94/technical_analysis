from datetime import date

from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.watchlist_trigger_service import RankingProvider, WatchlistProvider, WatchlistTriggerService


class FakeWatchlistProvider:
    def __init__(self, stocks):
        self.stocks = stocks

    def fetch(self, as_of_date: date):
        return self.stocks


class FakeRankingProvider:
    def __init__(self, current, previous):
        self.current = current
        self.previous = previous

    def fetch(self, as_of_date: date):
        return self.current

    def fetch_previous(self, as_of_date: date):
        return self.previous


def test_watchlist_trigger_service_reports_new_candidates_up_down_data_insufficient_and_risk():
    current = {
        "2330": {"score_bp": 7100, "risk_alert": False},
        "1101": {"score_bp": 6200, "risk_alert": True},
        "3008": {"score_bp": 6400},
        "2603": {"score_bp": 5800, "risk_alert": True},
    }
    previous = {
        "2330": {"score_bp": 6900, "risk_alert": False},
        "1101": {"score_bp": 5900},
        # 2603 should fall out this time, 3008 is brand-new candidate
        "2603": {"score_bp": 6600, "risk_alert": True},
    }
    watchlist = ["2330", "1101", "3008", "2409", "2603"]
    service = WatchlistTriggerService(
        FakeWatchlistProvider(watchlist),
        FakeRankingProvider(current, previous),
        entry_threshold_bp=6000,
    )
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.ESTIMATED
    assert snapshot.trigger_count == 3
    assert snapshot.triggered_codes == ("1101", "3008", "2330")
    assert "new=1101,3008" in snapshot.top_signal
    assert "up=2330" in snapshot.top_signal
    assert any("watchlist_trigger_data_insufficient:2409" in w for w in snapshot.warnings)
    assert any("watchlist_trigger_risk_alert:1101" in w for w in snapshot.warnings)


def test_watchlist_trigger_service_missing_watchlist_is_missing_quality():
    service = WatchlistTriggerService(
        FakeWatchlistProvider([]),
        FakeRankingProvider({}, {}),
    )
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.MISSING
    assert snapshot.warnings == ("watchlist_trigger_watchlist_missing",)
    assert snapshot.triggered_codes == ()


def test_watchlist_trigger_service_degraded_when_provider_fails():
    class BrokenProvider:
        def fetch(self, as_of_date: date):
            raise RuntimeError("ranking not available")

    class FakeWatchlistForFailure:
        def fetch(self, as_of_date: date):
            return ["2330", "1101"]

    service = WatchlistTriggerService(
        FakeWatchlistForFailure(),
        BrokenProvider(),
    )
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.trigger_count == 0
    assert any("watchlist_trigger_ranking_provider_error" in item for item in snapshot.warnings)
