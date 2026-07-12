from datetime import date
from types import SimpleNamespace

from app_module.decision_desk_composition import (
    DecisionDeskMarketRegimeProvider,
    build_smart_money_composition,
)


class _RegimeService:
    def detect_regime(self, *, as_of_date: str):
        assert as_of_date == "2026-06-15"
        return SimpleNamespace(
            confidence="0.77",
            details={"ma20_slope": "1.2"},
            regime_name_cn="趨勢循環",
            regime="Trend",
        )


def test_market_regime_adapter_uses_decimal_basis_point_boundary() -> None:
    provider = DecisionDeskMarketRegimeProvider(_RegimeService())

    summary = provider.fetch_market_regime(date(2026, 6, 15))

    assert summary is not None
    assert summary.regime_confidence == 7700
    assert summary.regime_score == 120


def test_market_regime_adapter_rejects_invalid_numeric_values() -> None:
    provider = DecisionDeskMarketRegimeProvider(None)

    assert provider.to_confidence_bp(None) is None
    assert provider.to_confidence_bp("invalid") is None


def test_smart_money_composition_reuses_injected_market_frame_loader() -> None:
    loader = object()
    broker_flow_service = object()

    class PriceProvider:
        def __init__(self, db_file, *, market_frame_loader):
            self.db_file = db_file
            self.market_frame_loader = market_frame_loader

    class SemanticService:
        def __init__(self, broker_service, *, price_provider):
            self.broker_service = broker_service
            self.price_provider = price_provider

    result = build_smart_money_composition(
        config=SimpleNamespace(db_file="db.sqlite"),
        broker_flow_service=broker_flow_service,
        market_frame_loader=loader,
        dependencies={
            "DecisionMarketFrameLoader": lambda _: (_ for _ in ()).throw(AssertionError()),
            "SQLiteSmartMoneyPriceProvider": PriceProvider,
            "SmartMoneySemanticService": SemanticService,
        },
    )

    assert result.market_frame_loader is loader
    assert result.service.broker_service is broker_flow_service
    assert result.service.price_provider.market_frame_loader is loader


def test_smart_money_composition_fails_closed_without_raising() -> None:
    errors = []
    result = build_smart_money_composition(
        config=SimpleNamespace(db_file="db.sqlite"),
        broker_flow_service=object(),
        dependencies={
            "DecisionMarketFrameLoader": lambda _: (_ for _ in ()).throw(RuntimeError("db")),
            "SQLiteSmartMoneyPriceProvider": object,
            "SmartMoneySemanticService": object,
        },
        report_error=errors.append,
    )

    assert result.service is None
    assert result.market_frame_loader is None
    assert errors and "db" in errors[0]
