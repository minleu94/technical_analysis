from datetime import date, timedelta
from decimal import Decimal

from app_module.dtos.broker_flow_dtos import BrokerFlowEvent
from app_module.smart_money_semantic_service import SmartMoneySemanticService


class FakeBrokerFlowService:
    def __init__(self, events):
        self.events = events

    def get_events(self, force_reload=False):
        return list(self.events)


class FakePriceProvider:
    def __init__(self, prices):
        self.prices = prices

    def load_recent_prices(self, stock_code, decision_date, limit):
        rows = [
            row for row in self.prices.get(stock_code, [])
            if row[0] <= decision_date
        ]
        return sorted(rows, key=lambda item: item[0], reverse=True)[:limit]


def _event(day, branch, code, net, quality="observed"):
    return BrokerFlowEvent(
        date=day.isoformat(),
        branch_system_key=branch,
        branch_display_name=branch,
        stock_code=code,
        stock_name=f"股票{code}",
        buy_qty=max(net, 0) if quality != "unavailable" else None,
        sell_qty=abs(min(net, 0)) if quality != "unavailable" else None,
        net_qty=net if quality != "unavailable" else None,
        lots_quality=quality,
        lots_available=quality != "unavailable",
        has_estimated_lots=quality == "estimated",
        lots_observed=quality == "observed",
    )


def test_semantic_service_classifies_initial_buy_without_future_events():
    decision = date(2026, 6, 20)
    events = [
        _event(decision - timedelta(days=idx), "A", "2330", 120)
        for idx in range(5)
    ]
    events += [
        _event(decision - timedelta(days=idx), "B", "2330", -80)
        for idx in range(5, 20)
    ]
    events.append(_event(decision + timedelta(days=1), "C", "2330", -9999))
    service = SmartMoneySemanticService(
        FakeBrokerFlowService(events), price_provider=FakePriceProvider({})
    )

    summary = service.build_stock_semantics("2330", decision)

    assert summary.primary_state == "初轉買"
    assert summary.dominant_side == "buy"
    assert summary.as_of_date == decision
    assert summary.window_5.net_qty == 600
    assert summary.window_20.net_qty == -600
    assert all("9999" not in evidence for evidence in summary.evidence_lines)


def test_semantic_service_classifies_initial_sell_trend():
    decision = date(2026, 6, 20)
    events = [
        _event(decision - timedelta(days=idx), "A", "2330", -150)
        for idx in range(5)
    ]
    events += [
        _event(decision - timedelta(days=idx), "B", "2330", 90)
        for idx in range(5, 20)
    ]
    service = SmartMoneySemanticService(
        FakeBrokerFlowService(events), price_provider=FakePriceProvider({})
    )

    summary = service.build_stock_semantics("2330", decision)

    assert summary.primary_state == "初轉賣"
    assert summary.dominant_side == "sell"
    assert summary.window_5.direction == "sell"
    assert summary.window_20.direction == "buy"


def test_semantic_service_uses_quantity_concentration_and_excludes_unavailable():
    decision = date(2026, 6, 20)
    events = [
        _event(decision, "A", "2330", 700),
        _event(decision, "B", "2330", 200),
        _event(decision, "C", "2330", 100, quality="estimated"),
        _event(decision, "D", "2330", 10000, quality="unavailable"),
    ]
    service = SmartMoneySemanticService(
        FakeBrokerFlowService(events), price_provider=FakePriceProvider({})
    )

    summary = service.build_stock_semantics("2330", decision)

    assert summary.window_5.top_concentration_bp == 7000
    assert summary.window_5.observed_count == 2
    assert summary.window_5.estimated_count == 1
    assert summary.window_5.unavailable_count == 1
    assert summary.source_quality_counts["unavailable"] == 1
    assert summary.window_5.usable_coverage_bp == 7500
    assert "分點集中異常" in summary.semantic_flags
    assert any("quantity" in warning for warning in summary.warnings)


def test_semantic_service_high_position_distribution_is_no_lookahead():
    decision = date(2026, 6, 20)
    prices = {
        "2330": [(decision - timedelta(days=idx), Decimal(100 + idx)) for idx in range(60)]
        + [(decision + timedelta(days=1), Decimal(999))]
    }
    events = [
        _event(decision, "A", "2330", -500),
        _event(decision - timedelta(days=1), "A", "2330", -300),
    ]
    service = SmartMoneySemanticService(
        FakeBrokerFlowService(events), price_provider=FakePriceProvider(prices)
    )

    summary = service.build_stock_semantics("2330", decision)

    assert summary.price_position_bp is not None
    assert summary.price_position_bp < 10000
    assert "高檔出貨疑慮" not in summary.semantic_flags
    assert "999" not in " ".join(summary.evidence_lines)
