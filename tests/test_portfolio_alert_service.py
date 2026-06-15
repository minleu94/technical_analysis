from datetime import date

from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.portfolio_alert_service import PortfolioAlertService


class FakePortfolioService:
    def __init__(self, positions):
        self.positions = positions

    def list_positions(self, portfolio_id: str = "default"):
        del portfolio_id
        return self.positions


class FakeConditionMonitor:
    def __init__(self, status_by_code):
        self.status_by_code = status_by_code
        self.calls = []

    def evaluate(self, position):
        self.calls.append(position.stock_code)
        status = self.status_by_code[position.stock_code]
        if isinstance(status, Exception):
            raise status
        return type("AlertResult", (), {"status": status})


class FakeChipSummaryProvider:
    def __init__(self, summaries):
        self.summaries = summaries
        self.calls = []

    def get_stock_chip_summary(self, stock_code: str, period_days: int = 5):
        del period_days
        self.calls.append(stock_code)
        if stock_code in self.summaries:
            return self.summaries[stock_code]
        return {"risk_level": "neutral"}


def make_position(stock_code: str, source_type: str, source_id: str, stock_name: str = "台積電") -> PositionDTO:
    return PositionDTO(
        position_id=f"pos_{stock_code}",
        portfolio_id="default",
        stock_code=stock_code,
        stock_name=stock_name,
        quantity=100,
        average_cost=100,
        invested_amount=10000,
        source_type=source_type,
        source_id=source_id,
        source_summary={},
        trade_ids=[],
    )


def test_portfolio_alert_service_returns_observed_summary_with_ordered_alerts_and_source_trace():
    positions = [
        make_position("2330", "manual", ""),
        make_position("1101", "recommendation_result", "rec_watch"),
        make_position("2603", "backtest_run", "bt_007"),
    ]
    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor(
            {
                "2330": "valid",
                "1101": "warning",
                "2603": "invalid",
            }
        ),
        FakeChipSummaryProvider({"2603": {"risk_level": "bearish"}}),
    )
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.alert_count == 2
    assert snapshot.alert_codes == ("2603", "1101")
    assert snapshot.alert_level == "high"
    assert snapshot.alert_codes[0] == "2603"
    assert any(item.startswith("portfolio_alert_top_source:") for item in snapshot.warnings)


def test_portfolio_alert_service_returns_low_quality_when_no_alert():
    positions = [
        make_position("2330", "manual", ""),
        make_position("1101", "recommendation_result", "rec_watch"),
    ]
    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor(
            {
                "2330": "valid",
                "1101": "valid",
            }
        ),
        FakeChipSummaryProvider(
            {
                "2330": {"risk_level": "neutral"},
                "1101": {"risk_level": "bullish"},
            }
        ),
    )
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.alert_count == 0
    assert snapshot.alert_codes == ()
    assert snapshot.alert_level == "low"
    assert snapshot.warnings == ()


def test_portfolio_alert_service_marks_estimated_when_chip_summary_missing_for_positions():
    positions = [
        make_position("1101", "recommendation_result", "rec_watch"),
    ]

    class BrokenChipProvider:
        def get_stock_chip_summary(self, stock_code: str, period_days: int = 5):
            del period_days
            raise RuntimeError(f"chip service down for {stock_code}")

    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor({"1101": "valid"}),
        BrokenChipProvider(),
    )
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.ESTIMATED
    assert snapshot.alert_count == 1
    assert snapshot.alert_codes == ("1101",)
    assert snapshot.alert_level == "low"
    assert any("chip_provider_error" in warning for warning in snapshot.warnings)


def test_portfolio_alert_service_returns_degraded_on_condition_monitor_error():
    positions = [
        make_position("1101", "recommendation_result", "rec_watch"),
        make_position("2603", "backtest_run", "bt_007"),
    ]
    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor(
            {
                "1101": RuntimeError("condition monitor unavailable"),
                "2603": "valid",
            }
        ),
        FakeChipSummaryProvider({}),
    )
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.alert_count == 0
    assert snapshot.alert_level == "low"
    assert any("condition_monitor_error" in warning for warning in snapshot.warnings)


def test_portfolio_alert_service_marks_estimated_when_chip_summary_has_estimated_lots():
    positions = [
        make_position("2330", "manual", ""),
    ]
    chip_provider = FakeChipSummaryProvider(
        {
            "2330": {
                "risk_level": "bearish",
                "lots_available": True,
                "has_estimated_lots": True,
                "observed_event_count": 1,
                "estimated_event_count": 2,
                "unavailable_event_count": 0,
                "risk_reasons": ["估計股數資料"],
            }
        }
    )
    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor({"2330": "valid"}),
        chip_provider,
    )

    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.ESTIMATED
    assert snapshot.alert_count == 1
    assert snapshot.alert_codes == ("2330",)
    assert snapshot.alert_level == "high"
    assert "portfolio_alerts_chip_estimated:2330" in snapshot.warnings


def test_portfolio_alert_service_warns_when_chip_lots_are_missing():
    positions = [
        make_position("1101", "manual", ""),
    ]
    chip_provider = FakeChipSummaryProvider(
        {
            "1101": {
                "risk_level": "neutral",
                "lots_available": False,
                "has_estimated_lots": False,
                "observed_event_count": 0,
                "estimated_event_count": 0,
                "unavailable_event_count": 3,
                "risk_reasons": ["無主力分點交易數據"],
            }
        }
    )
    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor({"1101": "valid"}),
        chip_provider,
    )

    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.ESTIMATED
    assert snapshot.alert_count == 0
    assert snapshot.alert_codes == ()
    assert snapshot.alert_level == "low"
    assert "portfolio_alerts_chip_data_missing:1101" in snapshot.warnings

