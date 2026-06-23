from datetime import date

from app_module.decision_desk_dashboard_service import DecisionDeskDashboardComposer
from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)


def _compose(
    *,
    regime_label: str = "risk-on",
    breadth_bp: int | None = 6200,
    confidence_bp: int | None = 8200,
    market_regime_quality: DecisionDeskQuality = DecisionDeskQuality.OBSERVED,
    market_breadth_quality: DecisionDeskQuality = DecisionDeskQuality.OBSERVED,
):
    sample_date = date(2026, 6, 15)
    return DecisionDeskDashboardComposer().compose(
        market_regime=MarketRegimeSummary(
            as_of_date=sample_date,
            quality=market_regime_quality,
            warnings=(),
            regime_label=regime_label,
            regime_confidence=confidence_bp,
        ),
        market_breadth=MarketBreadthSummary(
            as_of_date=sample_date,
            quality=market_breadth_quality,
            warnings=(),
            breadth_ratio_bp=breadth_bp,
            advancing=120,
            declining=80,
            unchanged=10,
        ),
        sector_rotation=SectorRotationSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            leading_sector="半導體",
            trailing_sector="金融",
            rotation_intensity_bp=150,
        ),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            top_strength_codes=("2330", "2454"),
            weak_strength_codes=("1101",),
            low_liquidity_codes=("9999",),
        ),
        watchlist_triggers=WatchlistTriggerSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            trigger_count=1,
            triggered_codes=("2603",),
            top_signal="momentum_breakout",
        ),
        portfolio_alerts=PortfolioAlertSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            alert_count=1,
            alert_codes=("2330",),
            alert_level="high",
        ),
    )


def test_dashboard_composer_builds_answer_first_action_summary():
    dashboard = _compose()

    assert dashboard.action_summary.action_level == "積極研究"
    assert "今日主結論" in dashboard.action_summary.headline
    assert "不是交易建議" in dashboard.action_summary.research_mode_note
    assert any("廣度比率" in reason for reason in dashboard.action_summary.reasons)


def test_dashboard_composer_does_not_lower_market_action_for_stock_alerts():
    dashboard = _compose(breadth_bp=6200, confidence_bp=8200)

    assert dashboard.action_summary.action_level == "積極研究"
    assert [card.stock_code for card in dashboard.stock_focus.risk_stocks][:2] == ["2330", "2603"]


def test_dashboard_composer_degrades_action_when_market_context_missing():
    dashboard = _compose(
        breadth_bp=None,
        market_breadth_quality=DecisionDeskQuality.MISSING,
    )

    assert dashboard.action_summary.action_level == "保守觀察"
    assert "market_breadth_quality:missing" in dashboard.action_summary.warnings


def test_dashboard_composer_builds_sector_and_stock_focus_cards():
    dashboard = _compose()

    assert dashboard.sector_focus.priority_sectors[0].sector_name == "半導體"
    assert dashboard.sector_focus.priority_sectors[0].target_tab == "強勢產業"
    assert dashboard.sector_focus.risk_sectors[0].sector_name == "金融"
    assert [card.stock_code for card in dashboard.stock_focus.priority_stocks] == ["2330", "2454"]
    assert any(card.drilldown_target == "smart_money" for card in dashboard.stock_focus.priority_stocks)
