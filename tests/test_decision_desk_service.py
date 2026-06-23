from datetime import date, datetime
from typing import Any

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
    RelativeStrengthLiquiditySummary,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    DecisionDeskSnapshot,
)
from app_module.decision_desk_service import DailyDecisionDeskProvider
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder


class FakeDecisionDeskProvider:
    def fetch_market_regime(self, as_of_date: date) -> MarketRegimeSummary:
        return MarketRegimeSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            regime_label="risk-on",
            regime_score=76,
            regime_confidence=8900,
        )

    def fetch_market_breadth(self, as_of_date: date) -> MarketBreadthSummary:
        return MarketBreadthSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.ESTIMATED,
            warnings=(),
            breadth_ratio_bp=4200,
            advancing=102,
            declining=90,
            unchanged=15,
        )

    def fetch_sector_rotation(self, as_of_date: date) -> SectorRotationSummary:
        return SectorRotationSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            leading_sector="半導體",
            trailing_sector="金融保險",
            rotation_intensity_bp=150,
        )

    def fetch_watchlist_triggers(self, as_of_date: date) -> WatchlistTriggerSummary:
        return WatchlistTriggerSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.ESTIMATED,
            warnings=(),
            trigger_count=2,
            triggered_codes=("2330", "2603"),
            top_signal="momentum_breakout",
        )

    def fetch_portfolio_alerts(self, as_of_date: date) -> PortfolioAlertSummary:
        return PortfolioAlertSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=("dummy warning",),
            alert_count=1,
            alert_codes=("AAPL",),
            alert_level="low",
        )


class AllObservedDecisionDeskProvider:
    def fetch_market_regime(self, as_of_date: date) -> MarketRegimeSummary:
        return MarketRegimeSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            regime_label="risk-on",
            regime_score=76,
            regime_confidence=8900,
        )

    def fetch_market_breadth(self, as_of_date: date) -> MarketBreadthSummary:
        return MarketBreadthSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            breadth_ratio_bp=4200,
            advancing=102,
            declining=90,
            unchanged=15,
        )

    def fetch_sector_rotation(self, as_of_date: date) -> SectorRotationSummary:
        return SectorRotationSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            leading_sector="半導體",
            trailing_sector="金融保險",
            rotation_intensity_bp=150,
        )

    def fetch_watchlist_triggers(self, as_of_date: date) -> WatchlistTriggerSummary:
        return WatchlistTriggerSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            trigger_count=0,
            triggered_codes=(),
            top_signal="momentum_breakout",
        )

    def fetch_portfolio_alerts(self, as_of_date: date) -> PortfolioAlertSummary:
        return PortfolioAlertSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            alert_count=1,
            alert_codes=("AAPL",),
            alert_level="low",
        )


class PartialDecisionDeskProvider:
    def fetch_market_regime(self, as_of_date: date) -> MarketRegimeSummary | None:
        return MarketRegimeSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            regime_label="risk-off",
            regime_score=52,
            regime_confidence=7200,
        )

    def fetch_market_breadth(self, as_of_date: date) -> MarketBreadthSummary | None:
        return None

    def fetch_sector_rotation(self, as_of_date: date) -> SectorRotationSummary | None:
        raise RuntimeError("sector service temporary unavailable")

    def fetch_watchlist_triggers(self, as_of_date: date) -> WatchlistTriggerSummary | None:
        return WatchlistTriggerSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=("watchlist stale",),
            trigger_count=0,
            triggered_codes=(),
            top_signal=None,
        )

    def fetch_portfolio_alerts(self, as_of_date: date) -> PortfolioAlertSummary | None:
        return PortfolioAlertSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.ESTIMATED,
            warnings=("port stale",),
            alert_count=3,
            alert_codes=("TSM",),
            alert_level="medium",
        )


def test_decision_desk_builder_uses_fake_provider_to_build_complete_snapshot():
    as_of_date = date(2026, 6, 15)
    builder = DecisionDeskSnapshotBuilder(
        FakeDecisionDeskProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.ESTIMATED,
                warnings=(),
            ),
        ),
    )
    snapshot = builder.build_snapshot(as_of_date)

    assert snapshot.schema_version == 1
    assert snapshot.as_of_date == as_of_date
    assert snapshot.overall_quality == DecisionDeskQuality.DEGRADED
    assert snapshot.market_regime.to_dict()["quality"] == DecisionDeskQuality.OBSERVED.value
    assert snapshot.market_breadth.to_dict()["quality"] == DecisionDeskQuality.ESTIMATED.value
    assert snapshot.watchlist_triggers.to_dict()["warnings"] == []
    assert snapshot.generated_at is not None
    payload = snapshot.to_dict()
    assert set(payload.keys()) == {
        "schema_version",
        "as_of_date",
        "generated_at",
        "overall_quality",
        "warnings",
        "market_regime",
        "market_breadth",
        "sector_rotation",
        "relative_strength_liquidity",
        "watchlist_triggers",
        "portfolio_alerts",
        "risk_prompts",
        "action_summary",
        "sector_focus",
        "stock_focus",
    }
    assert payload["portfolio_alerts"]["alert_level"] == "low"
    assert payload["action_summary"]["action_level"] in {"積極研究", "正常研究", "保守觀察", "暫停新進場"}


def test_decision_desk_snapshot_overall_quality_is_observed_when_all_sections_observed():
    as_of_date = date(2026, 6, 15)
    builder = DecisionDeskSnapshotBuilder(
        AllObservedDecisionDeskProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
            ),
        ),
    )
    snapshot = builder.build_snapshot(as_of_date)

    assert snapshot.overall_quality == DecisionDeskQuality.OBSERVED


def test_decision_desk_builder_keeps_snapshot_when_data_missing():
    builder = DecisionDeskSnapshotBuilder(
        PartialDecisionDeskProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=date(2026, 6, 15),
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
            ),
        ),
    )
    snapshot = builder.build_snapshot(date(2026, 6, 15))

    assert snapshot.market_breadth.quality == DecisionDeskQuality.MISSING
    assert snapshot.market_breadth.warnings == ("market_breadth_missing",)
    assert snapshot.sector_rotation.quality == DecisionDeskQuality.DEGRADED
    assert any("sector service temporary unavailable" in warning for warning in snapshot.sector_rotation.warnings)
    assert snapshot.market_regime.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.watchlist_triggers.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.portfolio_alerts.quality == DecisionDeskQuality.ESTIMATED
    assert snapshot.overall_quality == DecisionDeskQuality.DEGRADED
    payload = snapshot.to_dict()
    assert payload["market_breadth"]["as_of_date"] == "2026-06-15"
    assert payload["sector_rotation"]["warnings"] != []


class FakeSectionService:
    def __init__(self, section_name: str, payload: Any, fail: Exception | None = None):
        self.section_name = section_name
        self.payload = payload
        self.fail = fail

    def build_snapshot(self, as_of_date: date):
        if self.fail is not None:
            raise self.fail
        return self.payload


class FakeSmartMoneyDashboardService:
    def __init__(self):
        self.calls = []

    def build_dashboard_summary(self, decision_date: date, stock_codes: tuple[str, ...] = ()):
        from app_module.dtos.smart_money_semantic_dtos import SmartMoneyDashboardSummary, SmartMoneySemanticSummary

        self.calls.append((decision_date, stock_codes))
        return SmartMoneyDashboardSummary(
            decision_date=decision_date,
            as_of_date=decision_date,
            priority_summaries=(
                SmartMoneySemanticSummary(
                    stock_code="9999",
                    stock_name="Smart Priority",
                    decision_date=decision_date,
                    primary_state="初轉買",
                    quality="observed",
                ),
            ),
            risk_summaries=(
                SmartMoneySemanticSummary(
                    stock_code="8888",
                    stock_name="Smart Risk",
                    decision_date=decision_date,
                    primary_state="賣超延續",
                    semantic_flags=("高檔出貨疑慮",),
                    quality="degraded",
                ),
            ),
            quality="degraded",
            warnings=("smart_money_warning",),
        )


def test_decision_desk_builder_uses_injected_section_services():
    as_of_date = date(2026, 6, 15)
    builder = DecisionDeskSnapshotBuilder(
        AllObservedDecisionDeskProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
            ),
        ),
        market_breadth_service=FakeSectionService(
            "market_breadth",
            MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=("mb",),
                breadth_ratio_bp=3000,
            ),
        ),
        sector_rotation_service=FakeSectionService(
            "sector_rotation",
            SectorRotationSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.ESTIMATED,
                warnings=("sr",),
                leading_sector="Semiconductor",
                trailing_sector="Financials",
                rotation_intensity_bp=120,
            ),
        ),
        watchlist_trigger_service=FakeSectionService(
            "watchlist",
            WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                trigger_count=1,
                triggered_codes=("2330",),
                top_signal="momentum_breakout",
            ),
        ),
        portfolio_alert_service=FakeSectionService(
            "portfolio_alert",
            PortfolioAlertSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                alert_count=0,
                alert_codes=("AAPL",),
                alert_level="medium",
            ),
        ),
    )
    snapshot = builder.build_snapshot(as_of_date)

    assert snapshot.market_breadth.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.market_breadth.breadth_ratio_bp == 3000
    assert snapshot.sector_rotation.quality == DecisionDeskQuality.ESTIMATED
    assert snapshot.watchlist_triggers.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.portfolio_alerts.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.overall_quality == DecisionDeskQuality.DEGRADED


def test_decision_desk_builder_injects_smart_money_dashboard_summary_into_focus_cards():
    sample_date = date(2026, 6, 15)
    smart_money_service = FakeSmartMoneyDashboardService()
    builder = DecisionDeskSnapshotBuilder(
        AllObservedDecisionDeskProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                top_strength_codes=("2330",),
                weak_strength_codes=("1101",),
            ),
        ),
        smart_money_service=smart_money_service,
    )

    snapshot = builder.build_snapshot(sample_date)

    assert smart_money_service.calls == [(sample_date, ("2330", "1101", "AAPL"))]
    assert snapshot.stock_focus is not None
    assert any(card.stock_code == "9999" and card.source == "smart_money" for card in snapshot.stock_focus.priority_stocks)
    assert any(card.stock_code == "8888" and card.source == "smart_money" for card in snapshot.stock_focus.risk_stocks)


def test_decision_desk_builder_degrades_only_failed_section():
    as_of_date = date(2026, 6, 15)

    class FailingMarketRegimeProvider(FakeDecisionDeskProvider):
        def fetch_market_regime(self, as_of_date: date):
            return MarketRegimeSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=("provider ok",),
                regime_label="risk-on",
                regime_score=70,
                regime_confidence=9000,
            )

    builder = DecisionDeskSnapshotBuilder(
        FailingMarketRegimeProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
            ),
        ),
        market_breadth_service=FakeSectionService(
            "market_breadth",
            MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                breadth_ratio_bp=2800,
            ),
        ),
        sector_rotation_service=FakeSectionService(
            "sector_rotation",
            None,
            fail=RuntimeError("sector rotation temp error"),
        ),
        watchlist_trigger_service=FakeSectionService(
            "watchlist",
            WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                trigger_count=2,
                triggered_codes=("2603",),
                top_signal="breakout",
            ),
        ),
        portfolio_alert_service=FakeSectionService(
            "portfolio_alert",
            PortfolioAlertSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.ESTIMATED,
                warnings=(),
                alert_count=3,
                alert_codes=("AAPL", "TSLA"),
                alert_level="low",
            ),
        ),
    )
    snapshot = builder.build_snapshot(as_of_date)

    assert snapshot.market_regime.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.market_breadth.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.market_regime.warnings == ("provider ok",)
    assert snapshot.sector_rotation.quality == DecisionDeskQuality.DEGRADED
    assert any("sector rotation temp error" in warning for warning in snapshot.sector_rotation.warnings)
    assert snapshot.overall_quality == DecisionDeskQuality.DEGRADED
    assert snapshot.watchlist_triggers.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.portfolio_alerts.quality == DecisionDeskQuality.ESTIMATED


def test_decision_desk_snapshot_warnings_are_aggregated_with_section_prefix():
    as_of_date = date(2026, 6, 15)
    provider = AllObservedDecisionDeskProvider()
    builder = DecisionDeskSnapshotBuilder(
        provider,
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=("strength unstable",),
            ),
        ),
        market_breadth_service=FakeSectionService(
            "market_breadth",
            MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=("breadth unstable",),
            ),
        ),
        sector_rotation_service=FakeSectionService(
            "sector_rotation",
            SectorRotationSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                leading_sector="Semiconductor",
            ),
        ),
        watchlist_trigger_service=FakeSectionService(
            "watchlist",
            WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=("watchlist lagging",),
                trigger_count=1,
                triggered_codes=("2330",),
            ),
        ),
        portfolio_alert_service=FakeSectionService(
            "portfolio_alert",
            PortfolioAlertSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=("price missing",),
                alert_count=2,
                alert_codes=("AAPL",),
            ),
        ),
    )
    snapshot = builder.build_snapshot(as_of_date)

    assert "market_breadth:breadth unstable" in snapshot.warnings
    assert "watchlist_triggers:watchlist lagging" in snapshot.warnings
    assert "portfolio_alerts:price missing" in snapshot.warnings
    assert "relative_strength_liquidity:strength unstable" in snapshot.warnings
    assert "market_regime" not in "".join(snapshot.warnings)


def test_decision_desk_snapshot_generated_at_can_be_injected_for_test_stability():
    as_of_date = date(2026, 6, 15)
    fixed_now = datetime(2026, 6, 15, 9, 30, 0)
    builder = DecisionDeskSnapshotBuilder(
        AllObservedDecisionDeskProvider(),
        clock=lambda: fixed_now,
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
            ),
        ),
    )
    snapshot = builder.build_snapshot(as_of_date)

    assert snapshot.generated_at == fixed_now
    assert snapshot.to_dict()["generated_at"] == "2026-06-15T09:30:00"


def test_decision_desk_snapshot_serializes_relative_strength_liquidity_section():
    class FakeProvider:
        def fetch_market_regime(self, as_of_date: date): return None
        def fetch_market_breadth(self, as_of_date: date): return None
        def fetch_sector_rotation(self, as_of_date: date): return None
        def fetch_watchlist_triggers(self, as_of_date: date): return None
        def fetch_portfolio_alerts(self, as_of_date: date): return None

    sample_date = date(2026, 6, 15)
    builder = DecisionDeskSnapshotBuilder(
        provider=FakeProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                top_strength_codes=("2330", "2454"),
                low_liquidity_codes=("1101",),
                meta={
                    "ranking": [
                        {"stock_code": "2330", "strength_20d_bp": 1200, "avg_turnover": 900000000},
                        {"stock_code": "2454", "strength_20d_bp": 900, "avg_turnover": 700000000},
                    ]
                },
            ),
        ),
    )

    snapshot = builder.build_snapshot(sample_date)
    payload = snapshot.to_dict()

    assert snapshot.relative_strength_liquidity.quality == DecisionDeskQuality.OBSERVED
    assert payload["relative_strength_liquidity"]["top_strength_codes"] == ["2330", "2454"]
    assert payload["relative_strength_liquidity"]["low_liquidity_codes"] == ["1101"]
    assert payload["relative_strength_liquidity"]["meta"]["ranking"][0]["stock_code"] == "2330"


def test_decision_desk_builder_adds_answer_first_dashboard_fields():
    sample_date = date(2026, 6, 15)
    builder = DecisionDeskSnapshotBuilder(
        AllObservedDecisionDeskProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                top_strength_codes=("2330", "2454"),
                weak_strength_codes=("1101",),
            ),
        ),
    )

    snapshot = builder.build_snapshot(sample_date)

    assert snapshot.action_summary is not None
    assert "今日主結論" in snapshot.action_summary.headline
    assert snapshot.sector_focus is not None
    assert snapshot.stock_focus is not None
    assert [card.stock_code for card in snapshot.stock_focus.priority_stocks] == ["2330", "2454"]


def test_decision_desk_builder_derives_risk_prompts_from_existing_sections():
    sample_date = date(2026, 6, 15)
    provider = AllObservedDecisionDeskProvider()
    builder = DecisionDeskSnapshotBuilder(
        provider=provider,
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                low_liquidity_codes=("1101",),
            ),
        ),
        watchlist_trigger_service=FakeSectionService(
            "watchlist",
            WatchlistTriggerSummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=("watchlist_trigger_risk_alert:2603",),
                trigger_count=1,
                triggered_codes=("2603",),
            ),
        ),
        portfolio_alert_service=FakeSectionService(
            "portfolio_alert",
            PortfolioAlertSummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                alert_count=1,
                alert_codes=("2330",),
                alert_level="high",
            ),
        ),
    )

    snapshot = builder.build_snapshot(sample_date)

    assert snapshot.risk_prompts.quality == DecisionDeskQuality.DEGRADED
    assert any(prompt.category == "liquidity" and prompt.code == "1101" for prompt in snapshot.risk_prompts.prompts)
    assert any(prompt.category == "watchlist_risk" and prompt.code == "2603" for prompt in snapshot.risk_prompts.prompts)
    assert any(prompt.category == "portfolio_alert" and prompt.code == "2330" for prompt in snapshot.risk_prompts.prompts)
    assert "risk_prompts:risk_prompt_source_quality:watchlist_triggers:degraded" in snapshot.warnings



def test_decision_desk_snapshot_serializes_risk_prompts_section():
    sample_date = date(2026, 6, 15)
    prompt = DecisionDeskRiskPrompt(
        category="liquidity",
        severity="warning",
        source="relative_strength_liquidity",
        code="1101",
        title="低流動性",
        reason="1101 低於平均成交金額門檻",
        action_hint="下單或加入研究前檢查可成交金額與部位大小",
    )
    summary = DecisionDeskRiskPromptSummary(
        as_of_date=sample_date,
        quality=DecisionDeskQuality.OBSERVED,
        warnings=(),
        prompts=(prompt,),
    )
    snapshot = DecisionDeskSnapshot(
        as_of_date=sample_date,
        generated_at=datetime(2026, 6, 15, 9, 0, 0),
        schema_version=1,
        overall_quality=DecisionDeskQuality.OBSERVED,
        warnings=(),
        market_regime=MarketRegimeSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        market_breadth=MarketBreadthSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        sector_rotation=SectorRotationSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        watchlist_triggers=WatchlistTriggerSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        portfolio_alerts=PortfolioAlertSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        risk_prompts=summary,
    )

    payload = snapshot.to_dict()

    assert payload["risk_prompts"]["quality"] == "observed"
    assert payload["risk_prompts"]["prompts"][0]["category"] == "liquidity"
    assert payload["risk_prompts"]["prompts"][0]["code"] == "1101"
