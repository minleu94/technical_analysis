from datetime import date

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
    PortfolioAlertAttribution,
)
from app_module.decision_desk_risk_prompt_service import DecisionDeskRiskPromptService


def test_risk_prompt_service_maps_liquidity_watchlist_and_portfolio_risks():
    sample_date = date(2026, 6, 15)
    service = DecisionDeskRiskPromptService()

    summary = service.build_summary(
        as_of_date=sample_date,
        market_regime=MarketRegimeSummary(sample_date, DecisionDeskQuality.OBSERVED, (), regime_label="risk-off"),
        market_breadth=MarketBreadthSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        sector_rotation=SectorRotationSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            sample_date,
            DecisionDeskQuality.OBSERVED,
            (),
            weak_strength_codes=("2409",),
            low_liquidity_codes=("1101",),
        ),
        watchlist_triggers=WatchlistTriggerSummary(
            sample_date,
            DecisionDeskQuality.DEGRADED,
            ("watchlist_trigger_risk_alert:2603",),
            triggered_codes=("2603",),
        ),
        portfolio_alerts=PortfolioAlertSummary(
            sample_date,
            DecisionDeskQuality.ESTIMATED,
            ("portfolio_alerts_chip_estimated:2330",),
            alert_codes=("2330",),
            alert_level="high",
        ),
    )

    prompts = summary.prompts
    assert summary.quality == DecisionDeskQuality.DEGRADED
    assert any(item.category == "liquidity" and item.code == "1101" for item in prompts)
    assert any(item.category == "weakness" and item.code == "2409" for item in prompts)
    assert any(item.category == "watchlist_risk" and item.code == "2603" for item in prompts)
    assert any(item.category == "portfolio_alert" and item.code == "2330" for item in prompts)
    assert any(item.category == "market_context" and item.code is None for item in prompts)
    assert "risk_prompt_source_quality:watchlist_triggers:degraded" in summary.warnings
    assert "risk_prompt_source_quality:portfolio_alerts:estimated" in summary.warnings


def test_risk_prompt_service_returns_missing_when_no_prompt_can_be_derived():
    sample_date = date(2026, 6, 15)
    service = DecisionDeskRiskPromptService()

    summary = service.build_summary(
        as_of_date=sample_date,
        market_regime=MarketRegimeSummary(sample_date, DecisionDeskQuality.MISSING, ("market_regime_missing",)),
        market_breadth=MarketBreadthSummary(sample_date, DecisionDeskQuality.MISSING, ("market_breadth_missing",)),
        sector_rotation=SectorRotationSummary(sample_date, DecisionDeskQuality.MISSING, ("sector_rotation_missing",)),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(sample_date, DecisionDeskQuality.MISSING, ("relative_strength_liquidity_missing",)),
        watchlist_triggers=WatchlistTriggerSummary(sample_date, DecisionDeskQuality.MISSING, ("watchlist_triggers_missing",)),
        portfolio_alerts=PortfolioAlertSummary(sample_date, DecisionDeskQuality.MISSING, ("portfolio_alerts_missing",)),
    )

    assert summary.quality == DecisionDeskQuality.MISSING
    assert summary.prompts == ()
    assert summary.warnings == ("risk_prompt_missing",)


def test_risk_prompt_service_uses_portfolio_attribution_reason_text():
    sample_date = date(2026, 6, 15)
    service = DecisionDeskRiskPromptService()
    portfolio = PortfolioAlertSummary(
        sample_date,
        DecisionDeskQuality.OBSERVED,
        (),
        alert_count=1,
        alert_codes=("2330",),
        alert_level="high",
        attributions=(
            PortfolioAlertAttribution(
                stock_code="2330",
                source_label="recommendation_result:rec_001",
                condition_status="warning",
                chip_risk_level="bearish",
                severity=80,
                reasons=("condition:warning", "chip:risk_level:bearish"),
                data_quality_flags=(),
            ),
        ),
    )

    summary = service.build_summary(
        as_of_date=sample_date,
        market_regime=MarketRegimeSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        market_breadth=MarketBreadthSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        sector_rotation=SectorRotationSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        watchlist_triggers=WatchlistTriggerSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        portfolio_alerts=portfolio,
    )

    prompt = next(item for item in summary.prompts if item.category == "portfolio_alert")
    assert "recommendation_result:rec_001" in prompt.reason
    assert "condition:warning" in prompt.reason
    assert "chip:risk_level:bearish" in prompt.reason

