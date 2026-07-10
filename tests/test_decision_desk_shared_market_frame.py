from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from app_module.decision_desk_builder_factory import (
    build_service_backed_decision_desk_snapshot_builder,
)
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder
from app_module.decision_market_frame import DecisionMarketFrameLoader
from app_module.market_breadth_service import SQLiteDailyPriceMarketBreadthProvider
from app_module.relative_strength_liquidity_service import (
    SQLiteDailyPriceRelativeStrengthLiquidityProvider,
)
from app_module.smart_money_semantic_service import SQLiteSmartMoneyPriceProvider
from tests.test_decision_market_frame import _seed_daily_prices


def test_daily_price_providers_share_one_market_frame_read(tmp_path, monkeypatch) -> None:
    db_path = _seed_daily_prices(tmp_path)
    loader = DecisionMarketFrameLoader(db_path)
    reads = 0
    original = loader._read_frame

    def counted(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(loader, "_read_frame", counted)
    target = date(2026, 1, 9)
    loader.reset(target)
    breadth = SQLiteDailyPriceMarketBreadthProvider(
        db_path,
        market_frame_loader=loader,
    )
    relative = SQLiteDailyPriceRelativeStrengthLiquidityProvider(
        db_path,
        market_frame_loader=loader,
    )
    smart_money = SQLiteSmartMoneyPriceProvider(
        db_path,
        market_frame_loader=loader,
    )

    assert not breadth.fetch(target).empty
    assert not relative.fetch(target).empty
    assert smart_money.load_recent_prices("2330", target, 60)
    assert reads == 1


def test_snapshot_builder_resets_shared_market_frame_each_build() -> None:
    class ResetRecorder:
        def __init__(self) -> None:
            self.calls: list[date] = []

        def reset(self, as_of_date: date) -> None:
            self.calls.append(as_of_date)

    loader = ResetRecorder()
    builder = DecisionDeskSnapshotBuilder(market_frame_loader=loader)
    target = date(2026, 1, 9)

    builder.build_snapshot(target)
    builder.build_snapshot(target)

    assert loader.calls == [target, target]


def test_service_backed_factory_injects_one_loader_into_all_price_providers(
    tmp_path,
) -> None:
    config = MagicMock()
    config.db_file = _seed_daily_prices(tmp_path)

    builder = build_service_backed_decision_desk_snapshot_builder(
        config,
        regime_service=MagicMock(),
        portfolio_service=MagicMock(),
        watchlist_service=MagicMock(),
        broker_flow_service=MagicMock(),
    )

    loader = builder.market_frame_loader
    assert loader is not None
    assert builder.market_breadth_service.provider.market_frame_loader is loader
    assert (
        builder.relative_strength_liquidity_service.provider.market_frame_loader
        is loader
    )
    assert builder.smart_money_service.price_provider.market_frame_loader is loader
