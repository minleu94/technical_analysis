from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from app_module.broker_flow_service import BrokerFlowService
from app_module.decision_desk_dtos import DecisionDeskQuality, MarketRegimeSummary
from app_module.decision_market_frame import DecisionMarketFrameLoader
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder
from app_module.market_breadth_service import MarketBreadthService, SQLiteDailyPriceMarketBreadthProvider
from app_module.portfolio_alert_service import PortfolioAlertService
from app_module.portfolio_chip_service import PortfolioChipService
from app_module.portfolio_condition_monitor import PortfolioConditionMonitor
from app_module.portfolio_service import PortfolioService
from app_module.regime_service import RegimeService
from app_module.relative_strength_liquidity_service import (
    RelativeStrengthLiquidityService,
    SQLiteDailyPriceRelativeStrengthLiquidityProvider,
)
from app_module.sector_rotation_service import SectorRotationService, SQLiteIndustryIndexSectorRotationProvider
from app_module.smart_money_semantic_service import SmartMoneySemanticService, SQLiteSmartMoneyPriceProvider
from app_module.watchlist_service import WatchlistService
from app_module.watchlist_trigger_service import (
    SQLiteRankingProvider,
    WatchlistServiceWatchlistProvider,
    WatchlistTriggerService,
)
from data_module.config import TWStockConfig


logger = logging.getLogger(__name__)


class DecisionDeskMarketRegimeProvider:
    """Non-UI adapter that exposes RegimeService to DecisionDeskSnapshotBuilder."""

    def __init__(self, regime_service: RegimeService | None) -> None:
        self.regime_service = regime_service

    def _to_confidence_bp(self, confidence: Any) -> int | None:
        if confidence is None:
            return None
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            return None
        if 0 <= value <= 1:
            return int(value * 10000)
        if 0 <= value <= 100:
            return int(value * 100)
        return int(value)

    def fetch_market_regime(self, as_of_date):
        if self.regime_service is None:
            return None
        try:
            as_of_date_text = as_of_date.isoformat()
            try:
                result = self.regime_service.detect_regime(as_of_date=as_of_date_text)
            except TypeError:
                result = self.regime_service.detect_regime(date=as_of_date_text)
            details = dict(getattr(result, "details", {}) or {})
            regime_score = self._regime_score(details)
            return MarketRegimeSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                regime_label=getattr(result, "regime_name_cn", None) or getattr(result, "regime", None),
                regime_score=regime_score,
                regime_confidence=self._to_confidence_bp(getattr(result, "confidence", None)),
                meta=details,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Decision Desk market regime provider failed: %s", exc)
            return None

    def fetch_market_breadth(self, _as_of_date):
        return None

    def fetch_sector_rotation(self, _as_of_date):
        return None

    def fetch_watchlist_triggers(self, _as_of_date):
        return None

    def fetch_portfolio_alerts(self, _as_of_date):
        return None

    def _regime_score(self, details: dict[str, Any]) -> int | None:
        regime_score = details.get("ma20_slope")
        if regime_score is None:
            regime_score = details.get("score")
        if regime_score is None:
            regime_score = details.get("regime_score")
        if regime_score is None:
            return None
        try:
            return int(float(regime_score) * 100)
        except (TypeError, ValueError):
            return None


def build_service_backed_decision_desk_snapshot_builder(
    config: TWStockConfig,
    *,
    clock: Callable[[], datetime] | None = None,
    regime_service: RegimeService | None = None,
    portfolio_service: PortfolioService | None = None,
    watchlist_service: WatchlistService | None = None,
    broker_flow_service: BrokerFlowService | None = None,
    smart_money_service: Any | None = None,
) -> DecisionDeskSnapshotBuilder:
    """Create the Decision Desk builder used by non-UI batch and CLI flows."""

    active_regime_service = regime_service or _try_create("RegimeService", lambda: RegimeService(config))
    active_portfolio_service = portfolio_service or _try_create("PortfolioService", lambda: PortfolioService(config))
    active_watchlist_service = watchlist_service or _try_create("WatchlistService", lambda: WatchlistService(config))
    active_broker_flow_service = broker_flow_service or _try_create("BrokerFlowService", lambda: BrokerFlowService(config))
    market_frame_loader = DecisionMarketFrameLoader(config.db_file)

    market_breadth_service = _try_create(
        "MarketBreadthService",
        lambda: MarketBreadthService(
            SQLiteDailyPriceMarketBreadthProvider(
                config.db_file,
                market_frame_loader=market_frame_loader,
            )
        ),
    )
    sector_rotation_service = _try_create(
        "SectorRotationService",
        lambda: SectorRotationService(SQLiteIndustryIndexSectorRotationProvider(config.db_file)),
    )
    relative_strength_liquidity_service = _try_create(
        "RelativeStrengthLiquidityService",
        lambda: RelativeStrengthLiquidityService(
            SQLiteDailyPriceRelativeStrengthLiquidityProvider(
                config.db_file,
                market_frame_loader=market_frame_loader,
            )
        ),
    )
    watchlist_trigger_service = _try_create(
        "WatchlistTriggerService",
        lambda: WatchlistTriggerService(
            WatchlistServiceWatchlistProvider(active_watchlist_service),
            SQLiteRankingProvider(config.db_file),
        ),
    )
    portfolio_alert_service = None
    if active_portfolio_service is not None:
        portfolio_alert_service = _try_create(
            "PortfolioAlertService",
            lambda: PortfolioAlertService(
                portfolio_service=active_portfolio_service,
                condition_monitor=PortfolioConditionMonitor(),
                chip_summary_provider=_try_create(
                    "PortfolioChipService",
                    lambda: PortfolioChipService(config, broker_flow_service=active_broker_flow_service),
                ),
            ),
        )
    active_smart_money_service = smart_money_service
    if active_smart_money_service is None and active_broker_flow_service is not None:
        active_smart_money_service = _try_create(
            "SmartMoneySemanticService",
            lambda: SmartMoneySemanticService(
                active_broker_flow_service,
                price_provider=SQLiteSmartMoneyPriceProvider(
                    config.db_file,
                    market_frame_loader=market_frame_loader,
                ),
            ),
        )

    return DecisionDeskSnapshotBuilder(
        provider=DecisionDeskMarketRegimeProvider(active_regime_service),
        clock=clock,
        market_breadth_service=market_breadth_service,
        sector_rotation_service=sector_rotation_service,
        relative_strength_liquidity_service=relative_strength_liquidity_service,
        watchlist_trigger_service=watchlist_trigger_service,
        portfolio_alert_service=portfolio_alert_service,
        smart_money_service=active_smart_money_service,
        market_frame_loader=market_frame_loader,
    )


def _try_create(name: str, factory: Callable[[], Any]) -> Any | None:
    try:
        return factory()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Decision Desk %s initialization failed: %s", name, exc)
        return None
