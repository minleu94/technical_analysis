import os
from datetime import date, datetime
from dataclasses import replace

import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskSnapshot,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
    RelativeStrengthLiquiditySummary,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    PortfolioAlertAttribution,
)
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.views.decision_desk_view import DecisionDeskView


class FakeBuilder:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    def build_snapshot(self, as_of_date: date) -> DecisionDeskSnapshot:
        self.calls.append(as_of_date)
        return self.snapshot


def _snapshot(
    *,
    overall_quality: DecisionDeskQuality = DecisionDeskQuality.OBSERVED,
    market_regime_quality=DecisionDeskQuality.OBSERVED,
    market_breadth_quality=DecisionDeskQuality.OBSERVED,
    sector_rotation_quality=DecisionDeskQuality.OBSERVED,
    relative_strength_liquidity_quality=DecisionDeskQuality.OBSERVED,
    watchlist_quality=DecisionDeskQuality.OBSERVED,
    portfolio_quality=DecisionDeskQuality.OBSERVED,
    risk_prompts_quality=DecisionDeskQuality.OBSERVED,
    market_regime_warnings=(),
    market_breadth_warnings=(),
    sector_rotation_warnings=(),
    relative_strength_liquidity_warnings=(),
    watchlist_warnings=(),
    portfolio_warnings=(),
    risk_prompts_warnings=(),
    overall_warnings=(),
) -> DecisionDeskSnapshot:
    as_of = date(2026, 6, 15)
    return DecisionDeskSnapshot(
        as_of_date=as_of,
        generated_at=datetime(2026, 6, 15, 9, 0, 0),
        schema_version=1,
        overall_quality=overall_quality,
        market_regime=MarketRegimeSummary(
            as_of_date=as_of,
            quality=market_regime_quality,
            warnings=market_regime_warnings,
            regime_label="風險中性",
            regime_score=50,
            regime_confidence=7700,
        ),
        market_breadth=MarketBreadthSummary(
            as_of_date=as_of,
            quality=market_breadth_quality,
            warnings=market_breadth_warnings,
            breadth_ratio_bp=4200,
            advancing=120,
            declining=80,
            unchanged=20,
        ),
        sector_rotation=SectorRotationSummary(
            as_of_date=as_of,
            quality=sector_rotation_quality,
            warnings=sector_rotation_warnings,
            leading_sector="半導體",
            trailing_sector="金融",
            rotation_intensity_bp=150,
        ),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=as_of,
            quality=relative_strength_liquidity_quality,
            warnings=relative_strength_liquidity_warnings,
            top_strength_codes=("2330", "2454"),
            weak_strength_codes=("1101",),
            low_liquidity_codes=(),
        ),
        watchlist_triggers=WatchlistTriggerSummary(
            as_of_date=as_of,
            quality=watchlist_quality,
            warnings=watchlist_warnings,
            trigger_count=2,
            triggered_codes=("2330", "2603"),
            top_signal="momentum_breakout",
        ),
        portfolio_alerts=PortfolioAlertSummary(
            as_of_date=as_of,
            quality=portfolio_quality,
            warnings=portfolio_warnings,
            alert_count=1,
            alert_codes=("AAPL",),
            alert_level="low",
        ),
        risk_prompts=DecisionDeskRiskPromptSummary(
            as_of_date=as_of,
            quality=risk_prompts_quality,
            warnings=risk_prompts_warnings,
            prompts=(),
        ),
        warnings=overall_warnings,
    )


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_decision_desk_view_refresh_calls_builder_and_renders_snapshot():
    app()
    s = _snapshot()
    builder = FakeBuilder(s)
    target_date = date(2026, 6, 15)
    view = DecisionDeskView(builder, as_of_date=target_date)

    assert builder.calls == [target_date]
    assert "整體品質" in view.overall_status_label.text()
    assert "觀察到" in view.overall_status_label.text()


def test_decision_desk_view_shows_degraded_status():
    app()
    s = _snapshot(
        overall_quality=DecisionDeskQuality.DEGRADED,
        market_breadth_quality=DecisionDeskQuality.DEGRADED,
        market_breadth_warnings=("market_breadth_fetch_error:timeout",),
    )
    view = DecisionDeskView(FakeBuilder(s))

    assert "降級" in view.overall_status_label.text()
    assert "降級" in view.market_breadth_status.text()
    assert "降級" in view._status_badges[view.market_breadth_status].text()


def test_decision_desk_view_shows_missing_status():
    app()
    s = _snapshot(
        overall_quality=DecisionDeskQuality.MISSING,
        market_regime_quality=DecisionDeskQuality.MISSING,
        market_regime_warnings=("no_data",),
    )
    view = DecisionDeskView(FakeBuilder(s))

    assert "缺漏" in view.overall_status_label.text()
    assert "缺漏" in view.market_regime_status.text()
    assert "缺漏" in view._status_badges[view.market_regime_status].text()


def test_decision_desk_view_aggregates_warning_lines_and_refresh_button():
    app()
    s = _snapshot(
        overall_quality=DecisionDeskQuality.DEGRADED,
        watchlist_quality=DecisionDeskQuality.DEGRADED,
        watchlist_warnings=("watchlist_stale",),
        overall_warnings=("global_warning",),
        sector_rotation_quality=DecisionDeskQuality.MISSING,
        sector_rotation_warnings=("sector_missing",),
    )
    builder = FakeBuilder(s)
    view = DecisionDeskView(builder)
    view.refresh_btn.click()

    assert builder.calls
    combined_text = view.overall_warn_label.toPlainText()
    assert "global_warning" in combined_text
    assert "Watchlist:watchlist_stale" in combined_text
    assert "產業輪動:sector_missing" in combined_text


class FailingBuilder:
    def build_snapshot(self, as_of_date: date):
        raise RuntimeError("service not ready")


def test_decision_desk_view_fallback_to_degraded_if_builder_exception():
    app()
    view = DecisionDeskView(FailingBuilder())

    assert "降級" in view.overall_status_label.text()
    assert "snapshot_error" in view.overall_warn_label.toPlainText()


def test_decision_desk_view_renders_risk_prompts():
    app()
    s = _snapshot()
    prompt = DecisionDeskRiskPrompt(
        category="liquidity",
        severity="warning",
        source="relative_strength_liquidity",
        code="1101",
        title="低流動性",
        reason="1101 低於平均成交金額門檻",
        action_hint="檢查可成交金額",
    )
    s = replace(
        s,
        risk_prompts=DecisionDeskRiskPromptSummary(
            as_of_date=s.as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            prompts=(prompt,),
        ),
    )
    view = DecisionDeskView(FakeBuilder(s))

    assert "低流動性" in view.risk_prompts_value.text()
    assert "1101" in view.risk_prompts_value.text()


def test_decision_desk_view_renders_portfolio_alert_attributions():
    app()
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        portfolio_alerts=PortfolioAlertSummary(
            as_of_date=snapshot.as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
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
        ),
    )

    view = DecisionDeskView(FakeBuilder(snapshot))

    assert "recommendation_result:rec_001" in view.portfolio_alerts_value.text()
    assert "condition=warning" in view.portfolio_alerts_value.text()
    assert "chip=bearish" in view.portfolio_alerts_value.text()


def test_decision_desk_view_compacts_long_relative_strength_lists():
    app()
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=snapshot.as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            top_strength_codes=tuple(f"T{i:03d}" for i in range(20)),
            weak_strength_codes=tuple(f"W{i:03d}" for i in range(18)),
            low_liquidity_codes=tuple(f"L{i:03d}" for i in range(22)),
        ),
    )

    view = DecisionDeskView(FakeBuilder(snapshot))
    rendered = view.relative_strength_codes.text()

    assert view.relative_strength_liquidity_value.isHidden()
    assert view.relative_strength_liquidity_value.text() == ""
    assert view.relative_strength_codes.wordWrap()
    assert "\n" in rendered
    assert "另 12 檔" in rendered
    assert "T019" not in rendered


def test_decision_desk_uses_single_relative_strength_presentation():
    app()
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=snapshot.as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            top_strength_codes=("2330", "2454"),
            weak_strength_codes=("1101",),
            low_liquidity_codes=("9999",),
        ),
    )

    view = DecisionDeskView(FakeBuilder(snapshot))

    assert view.relative_strength_liquidity_value.isHidden()
    assert view.relative_strength_liquidity_value.text() == ""
    assert "強勢：2330, 2454" in view.relative_strength_codes.text()
    assert "弱勢：1101" in view.relative_strength_codes.text()
    assert "低流動性：9999" in view.relative_strength_codes.text()


def test_decision_desk_sections_use_quality_badges_in_headers():
    app()
    view = DecisionDeskView(FakeBuilder(_snapshot(market_breadth_quality=DecisionDeskQuality.DEGRADED)))

    assert view.market_breadth_status.isHidden()
    badge = view._status_badges[view.market_breadth_status]
    assert "降級" in badge.text()
    assert MIDNIGHT_ANALYST.warning in badge.styleSheet()


def test_decision_desk_view_uses_readable_overview_typography():
    app()
    view = DecisionDeskView(FakeBuilder(_snapshot()))

    assert view.overall_status_label.font().pointSize() >= 12
    assert view.generated_at_label.font().pointSize() >= 10
    assert "background" in view.overall_status_label.styleSheet()


def test_decision_desk_view_uses_midnight_reference_widgets():
    app()
    view = DecisionDeskView(FakeBuilder(_snapshot()))

    assert hasattr(view, "overall_quality_badge")
    assert hasattr(view, "relative_strength_codes")
    assert hasattr(view, "warning_list")
    assert view.relative_strength_codes.wordWrap()
    assert "#08111f" not in view.styleSheet()


def test_decision_desk_view_renders_compact_code_widget_from_snapshot():
    app()
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=snapshot.as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            top_strength_codes=tuple(f"T{i:03d}" for i in range(10)),
            weak_strength_codes=("W001",),
            low_liquidity_codes=("L001", "L002"),
        ),
    )

    view = DecisionDeskView(FakeBuilder(snapshot))
    text = view.relative_strength_codes.text()

    assert "強勢：T000, T001, T002, T003, T004, T005, T006, T007（另 2 檔）" in text
    assert "弱勢：W001" in text
    assert "低流動性：L001, L002" in text
