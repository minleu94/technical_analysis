from types import SimpleNamespace
from unittest.mock import MagicMock

from app_module.decision_service_composition import build_decision_service_composition


def test_decision_service_composition_injects_shared_mapper_and_data_ports() -> None:
    dependencies = {
        name: MagicMock(name=name)
        for name in (
            "IndustryMapper",
            "ScreeningService",
            "MarketRegimeDetector",
            "RegimeService",
            "RecommendationService",
            "StockScreener",
        )
    }
    dependencies["IndustryMapper"].return_value = mapper = object()
    dependencies["MarketRegimeDetector"].side_effect = [
        regime_detector := object(),
        recommendation_detector := object(),
    ]
    dependencies["StockScreener"].return_value = stock_screener = object()
    industry_provider = object()
    market_provider = object()

    composition = build_decision_service_composition(
        config=SimpleNamespace(),
        dependencies=dependencies,
        industry_index_provider=industry_provider,
        market_index_provider=market_provider,
    )

    dependencies["IndustryMapper"].assert_called_once_with(
        composition.config, industry_index_provider=industry_provider
    )
    dependencies["ScreeningService"].assert_called_once_with(
        composition.config, industry_mapper=mapper, stock_screener=stock_screener
    )
    assert dependencies["MarketRegimeDetector"].call_count == 2
    dependencies["RegimeService"].assert_called_once_with(
        composition.config, regime_detector=regime_detector
    )
    dependencies["RecommendationService"].assert_called_once_with(
        composition.config,
        industry_mapper=mapper,
        regime_detector=recommendation_detector,
    )
