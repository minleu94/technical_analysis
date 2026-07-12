"""MainWindow 使用的 Decision service composition root。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app_module.decision_data_providers import (
    industry_index_frame_provider,
    market_index_frame_provider,
    recent_industry_screen_provider,
    recent_stock_screen_provider,
)
from app_module.application_ports import MarketFrameProvider


@dataclass(frozen=True)
class DecisionServiceComposition:
    config: Any
    industry_mapper: Any
    screening_service: Any
    regime_service: Any
    recommendation_service: Any


def _default_dependencies() -> dict[str, Any]:
    from app_module.recommendation_service import RecommendationService
    from app_module.regime_service import RegimeService
    from app_module.screening_service import ScreeningService
    from decision_module.industry_mapper import IndustryMapper
    from decision_module.market_regime_detector import MarketRegimeDetector
    from decision_module.stock_screener import StockScreener

    return {
        "IndustryMapper": IndustryMapper,
        "ScreeningService": ScreeningService,
        "MarketRegimeDetector": MarketRegimeDetector,
        "RegimeService": RegimeService,
        "RecommendationService": RecommendationService,
        "StockScreener": StockScreener,
    }


def build_decision_service_composition(
    *,
    config: Any,
    dependencies: Mapping[str, Any] | None = None,
    industry_index_provider: MarketFrameProvider | None = None,
    market_index_provider: MarketFrameProvider | None = None,
) -> DecisionServiceComposition:
    """建立共享 mapper 與各自獨立的 regime detector。"""
    constructors = dict(dependencies or _default_dependencies())
    industry_provider = (
        industry_index_provider
        if industry_index_provider is not None
        else industry_index_frame_provider(config)
    )
    market_provider = (
        market_index_provider
        if market_index_provider is not None
        else market_index_frame_provider(config)
    )
    mapper = constructors["IndustryMapper"](
        config, industry_index_provider=industry_provider
    )
    stock_screener = constructors["StockScreener"](
        config,
        mapper,
        recent_stock_provider=recent_stock_screen_provider(config),
        recent_industry_provider=recent_industry_screen_provider(config),
    )
    screening_service = constructors["ScreeningService"](
        config, industry_mapper=mapper, stock_screener=stock_screener
    )
    regime_detector = constructors["MarketRegimeDetector"](
        config, market_frame_provider=market_provider
    )
    recommendation_detector = constructors["MarketRegimeDetector"](
        config, market_frame_provider=market_provider
    )
    regime_service = constructors["RegimeService"](
        config, regime_detector=regime_detector
    )
    recommendation_service = constructors["RecommendationService"](
        config,
        industry_mapper=mapper,
        regime_detector=recommendation_detector,
    )
    return DecisionServiceComposition(
        config=config,
        industry_mapper=mapper,
        screening_service=screening_service,
        regime_service=regime_service,
        recommendation_service=recommendation_service,
    )
