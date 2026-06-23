from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Protocol

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskSnapshot,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
    RelativeStrengthLiquiditySummary,
    DecisionDeskRiskPromptSummary,
)
from app_module.decision_desk_dashboard_service import DecisionDeskDashboardComposer
from app_module.decision_desk_risk_prompt_service import DecisionDeskRiskPromptService


class DailyDecisionDeskProvider(Protocol):
    def fetch_market_regime(self, as_of_date: date) -> MarketRegimeSummary | None: ...

    def fetch_market_breadth(self, as_of_date: date) -> MarketBreadthSummary | None: ...

    def fetch_sector_rotation(self, as_of_date: date) -> SectorRotationSummary | None: ...

    def fetch_watchlist_triggers(self, as_of_date: date) -> WatchlistTriggerSummary | None: ...

    def fetch_portfolio_alerts(self, as_of_date: date) -> PortfolioAlertSummary | None: ...


class MarketBreadthSectionService(Protocol):
    def build_snapshot(self, as_of_date: date) -> MarketBreadthSummary: ...


class SectorRotationSectionService(Protocol):
    def build_snapshot(self, as_of_date: date) -> SectorRotationSummary: ...


class WatchlistTriggerSectionService(Protocol):
    def build_snapshot(self, as_of_date: date) -> WatchlistTriggerSummary: ...


class PortfolioAlertSectionService(Protocol):
    def build_snapshot(self, as_of_date: date) -> PortfolioAlertSummary: ...


class RelativeStrengthLiquiditySectionService(Protocol):
    def build_snapshot(self, as_of_date: date) -> RelativeStrengthLiquiditySummary: ...


class SmartMoneyDashboardService(Protocol):
    def build_dashboard_summary(self, decision_date: date, stock_codes: tuple[str, ...] = ()): ...



class DecisionDeskSnapshotBuilder:
    """Builder for Daily Decision Desk snapshot."""

    def __init__(
        self,
        provider: DailyDecisionDeskProvider | None = None,
        *,
        schema_version: int = 1,
        clock: Callable[[], datetime] | None = None,
        market_breadth_service: MarketBreadthSectionService | None = None,
        sector_rotation_service: SectorRotationSectionService | None = None,
        relative_strength_liquidity_service: RelativeStrengthLiquiditySectionService | None = None,
        watchlist_trigger_service: WatchlistTriggerSectionService | None = None,
        portfolio_alert_service: PortfolioAlertSectionService | None = None,
        risk_prompt_service: DecisionDeskRiskPromptService | None = None,
        dashboard_composer: DecisionDeskDashboardComposer | None = None,
        smart_money_service: SmartMoneyDashboardService | None = None,
    ):
        self.provider = provider
        self.schema_version = schema_version
        self.clock = clock or datetime.now
        self.market_breadth_service = market_breadth_service
        self.sector_rotation_service = sector_rotation_service
        self.relative_strength_liquidity_service = relative_strength_liquidity_service
        self.watchlist_trigger_service = watchlist_trigger_service
        self.portfolio_alert_service = portfolio_alert_service
        self.risk_prompt_service = risk_prompt_service or DecisionDeskRiskPromptService()
        self.dashboard_composer = dashboard_composer or DecisionDeskDashboardComposer()
        self.smart_money_service = smart_money_service

    def build_snapshot(self, as_of_date: date) -> DecisionDeskSnapshot:
        market_regime = self._build_market_regime(as_of_date)
        market_breadth = self._build_market_breadth(as_of_date)
        sector_rotation = self._build_sector_rotation(as_of_date)
        relative_strength_liquidity = self._build_relative_strength_liquidity(as_of_date)
        watchlist_triggers = self._build_watchlist_triggers(as_of_date)
        portfolio_alerts = self._build_portfolio_alerts(as_of_date)
        risk_prompts = self.risk_prompt_service.build_summary(
            as_of_date=as_of_date,
            market_regime=market_regime,
            market_breadth=market_breadth,
            sector_rotation=sector_rotation,
            relative_strength_liquidity=relative_strength_liquidity,
            watchlist_triggers=watchlist_triggers,
            portfolio_alerts=portfolio_alerts,
        )
        sections = (
            market_regime,
            market_breadth,
            sector_rotation,
            relative_strength_liquidity,
            watchlist_triggers,
            portfolio_alerts,
            risk_prompts,
        )
        generated_at = self.clock()
        overall_quality = self._compute_overall_quality(sections)
        warnings = self._collect_snapshot_warnings(sections)
        smart_money_summary = None
        if self.smart_money_service is not None:
            try:
                smart_money_summary = self.smart_money_service.build_dashboard_summary(
                    as_of_date,
                    stock_codes=self._collect_smart_money_candidate_codes(
                        relative_strength_liquidity,
                        watchlist_triggers,
                        portfolio_alerts,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                warnings = tuple(warnings) + (f"smart_money_dashboard_error:{exc}",)
                overall_quality = DecisionDeskQuality.DEGRADED
        action_summary = None
        sector_focus = None
        stock_focus = None
        try:
            dashboard = self.dashboard_composer.compose(
                market_regime=market_regime,
                market_breadth=market_breadth,
                sector_rotation=sector_rotation,
                relative_strength_liquidity=relative_strength_liquidity,
                watchlist_triggers=watchlist_triggers,
                portfolio_alerts=portfolio_alerts,
                smart_money_summary=smart_money_summary,
            )
            action_summary = dashboard.action_summary
            sector_focus = dashboard.sector_focus
            stock_focus = dashboard.stock_focus
        except Exception as exc:  # noqa: BLE001
            warnings = tuple(warnings) + (f"dashboard_composer_error:{exc}",)
            overall_quality = DecisionDeskQuality.DEGRADED

        return DecisionDeskSnapshot(
            as_of_date=as_of_date,
            generated_at=generated_at,
            schema_version=self.schema_version,
            overall_quality=overall_quality,
            warnings=warnings,
            market_regime=market_regime,
            market_breadth=market_breadth,
            sector_rotation=sector_rotation,
            relative_strength_liquidity=relative_strength_liquidity,
            watchlist_triggers=watchlist_triggers,
            portfolio_alerts=portfolio_alerts,
            risk_prompts=risk_prompts,
            action_summary=action_summary,
            sector_focus=sector_focus,
            stock_focus=stock_focus,
        )

    def _build_market_regime(self, as_of_date: date) -> MarketRegimeSummary:
        if self.provider is None:
            return MarketRegimeSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("market_regime_missing",),
                regime_label=None,
            )
        try:
            snapshot = self.provider.fetch_market_regime(as_of_date)
        except Exception as exc:  # noqa: BLE001
            return MarketRegimeSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"market_regime_fetch_error:{exc}",),
                regime_label=None,
            )
        if snapshot is None:
            return MarketRegimeSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("market_regime_missing",),
                regime_label=None,
            )
        return snapshot

    def _build_market_breadth(self, as_of_date: date) -> MarketBreadthSummary:
        snapshot: MarketBreadthSummary | None
        if self.market_breadth_service is not None:
            try:
                snapshot = self.market_breadth_service.build_snapshot(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return MarketBreadthSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"market_breadth_fetch_error:{exc}",),
                )
        elif self.provider is not None:
            try:
                snapshot = self.provider.fetch_market_breadth(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return MarketBreadthSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"market_breadth_fetch_error:{exc}",),
                )
        else:
            return MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("market_breadth_missing",),
            )

        if snapshot is None:
            return MarketBreadthSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("market_breadth_missing",),
            )
        return snapshot

    def _build_sector_rotation(self, as_of_date: date) -> SectorRotationSummary:
        snapshot: SectorRotationSummary | None
        if self.sector_rotation_service is not None:
            try:
                snapshot = self.sector_rotation_service.build_snapshot(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return SectorRotationSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"sector_rotation_fetch_error:{exc}",),
                )
        elif self.provider is not None:
            try:
                snapshot = self.provider.fetch_sector_rotation(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return SectorRotationSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"sector_rotation_fetch_error:{exc}",),
                )
        else:
            return SectorRotationSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("sector_rotation_missing",),
            )

        if snapshot is None:
            return SectorRotationSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("sector_rotation_missing",),
            )
        return snapshot

    def _build_relative_strength_liquidity(self, as_of_date: date) -> RelativeStrengthLiquiditySummary:
        if self.relative_strength_liquidity_service is not None:
            try:
                snapshot = self.relative_strength_liquidity_service.build_snapshot(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return RelativeStrengthLiquiditySummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"relative_strength_liquidity_fetch_error:{exc}",),
                )
            if snapshot is not None:
                return snapshot

        return RelativeStrengthLiquiditySummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.MISSING,
            warnings=("relative_strength_liquidity_missing",),
        )

    def _build_watchlist_triggers(self, as_of_date: date) -> WatchlistTriggerSummary:
        snapshot: WatchlistTriggerSummary | None
        if self.watchlist_trigger_service is not None:
            try:
                snapshot = self.watchlist_trigger_service.build_snapshot(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return WatchlistTriggerSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"watchlist_triggers_fetch_error:{exc}",),
                    trigger_count=0,
                    triggered_codes=(),
                )
        elif self.provider is not None:
            try:
                snapshot = self.provider.fetch_watchlist_triggers(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return WatchlistTriggerSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"watchlist_triggers_fetch_error:{exc}",),
                    trigger_count=0,
                    triggered_codes=(),
                )
        else:
            return WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("watchlist_triggers_missing",),
                trigger_count=0,
                triggered_codes=(),
            )

        if snapshot is None:
            return WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("watchlist_triggers_missing",),
                trigger_count=0,
                triggered_codes=(),
            )
        return snapshot

    def _build_portfolio_alerts(self, as_of_date: date) -> PortfolioAlertSummary:
        snapshot: PortfolioAlertSummary | None
        if self.portfolio_alert_service is not None:
            try:
                snapshot = self.portfolio_alert_service.build_snapshot(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return PortfolioAlertSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"portfolio_alerts_fetch_error:{exc}",),
                    alert_count=0,
                    alert_codes=(),
                    alert_level=None,
                )
        elif self.provider is not None:
            try:
                snapshot = self.provider.fetch_portfolio_alerts(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return PortfolioAlertSummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"portfolio_alerts_fetch_error:{exc}",),
                    alert_count=0,
                    alert_codes=(),
                    alert_level=None,
                )
        else:
            return PortfolioAlertSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("portfolio_alerts_missing",),
                alert_count=0,
                alert_codes=(),
                alert_level=None,
            )

        if snapshot is None:
            return PortfolioAlertSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("portfolio_alerts_missing",),
                alert_count=0,
                alert_codes=(),
                alert_level=None,
            )
        return snapshot

    @staticmethod
    def _compute_overall_quality(
        sections: tuple[
            MarketRegimeSummary,
            MarketBreadthSummary,
            SectorRotationSummary,
            RelativeStrengthLiquiditySummary,
            WatchlistTriggerSummary,
            PortfolioAlertSummary,
            DecisionDeskRiskPromptSummary,
        ],
    ) -> DecisionDeskQuality:
        qualities = [section.quality for section in sections]
        if DecisionDeskQuality.DEGRADED in qualities:
            return DecisionDeskQuality.DEGRADED
        if DecisionDeskQuality.MISSING in qualities:
            return DecisionDeskQuality.MISSING
        if DecisionDeskQuality.ESTIMATED in qualities:
            return DecisionDeskQuality.ESTIMATED
        return DecisionDeskQuality.OBSERVED

    @staticmethod
    def _collect_snapshot_warnings(
        sections: tuple[
            MarketRegimeSummary,
            MarketBreadthSummary,
            SectorRotationSummary,
            RelativeStrengthLiquiditySummary,
            WatchlistTriggerSummary,
            PortfolioAlertSummary,
            DecisionDeskRiskPromptSummary,
        ],
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        market_regime, market_breadth, sector_rotation, relative_strength_liquidity, watchlist_triggers, portfolio_alerts, risk_prompts = sections
        section_warnings = (
            ("market_regime", market_regime.warnings),
            ("market_breadth", market_breadth.warnings),
            ("sector_rotation", sector_rotation.warnings),
            ("relative_strength_liquidity", relative_strength_liquidity.warnings),
            ("watchlist_triggers", watchlist_triggers.warnings),
            ("portfolio_alerts", portfolio_alerts.warnings),
            ("risk_prompts", risk_prompts.warnings),
        )
        for section_name, section_warning in section_warnings:
            for warning in section_warning:
                warnings.append(f"{section_name}:{warning}")
        return tuple(warnings)

    @staticmethod
    def _collect_smart_money_candidate_codes(
        relative_strength_liquidity: RelativeStrengthLiquiditySummary,
        watchlist_triggers: WatchlistTriggerSummary,
        portfolio_alerts: PortfolioAlertSummary,
    ) -> tuple[str, ...]:
        codes: list[str] = []
        seen: set[str] = set()
        for raw_code in (
            tuple(relative_strength_liquidity.top_strength_codes)
            + tuple(relative_strength_liquidity.weak_strength_codes)
            + tuple(relative_strength_liquidity.low_liquidity_codes)
            + tuple(watchlist_triggers.triggered_codes)
            + tuple(portfolio_alerts.alert_codes)
        ):
            code = str(raw_code).strip()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        return tuple(codes[:20])
