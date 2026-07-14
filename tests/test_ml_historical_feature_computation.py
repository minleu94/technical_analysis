from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from data_module.ml_historical_snapshot_provider import (
    HistoricalIndexObservation,
    HistoricalPriceObservation,
    HistoricalRawSnapshot,
    HistoricalTechnicalObservation,
)
from ml_module.historical_feature_builder import HistoricalFeatureBuilder


def _snapshot(*, future: bool = False) -> HistoricalRawSnapshot:
    prices = tuple(
        HistoricalPriceObservation(
            symbol="2330", trading_date=f"2024-01-{day:02d}",
            open_price=Decimal(day), high_price=Decimal(day + 1),
            low_price=Decimal(day - 1), close_price=Decimal(day),
            volume=day * 100, turnover_amount_minor=day * 1000,
        )
        for day in range(1, 22)
    )
    if future:
        prices += (replace(prices[-1], trading_date="2024-02-01", close_price=Decimal("999")),)
    market = tuple(
        HistoricalIndexObservation("market", f"2024-01-{day:02d}", Decimal(day * 2))
        for day in range(1, 22)
    )
    industry = tuple(
        HistoricalIndexObservation("半導體類指數", f"2024-01-{day:02d}", Decimal(day * 3))
        for day in range(1, 22)
    )
    return HistoricalRawSnapshot(
        decision_date="2024-01-22", feature_as_of_date="2024-01-21",
        prices=prices, technicals=(HistoricalTechnicalObservation(
            "2330", "2024-01-21", Decimal("55"), Decimal("0.5"), Decimal("25")
        ),), market=market, industries=industry,
        source_fingerprint="sha256:" + "1" * 64, query_count=5,
    )


def test_computation_uses_integer_units_and_excludes_fundamental_and_broker() -> None:
    row = HistoricalFeatureBuilder().compute(
        _snapshot(), industry_index_name_by_symbol={"2330": "半導體類指數"}
    )[0]
    values = dict(row.values)

    assert row.feature_as_of_date == "2024-01-21"
    assert values["stock_return_20d_bp"] == 200000
    assert values["market_return_20d_bp"] == 200000
    assert values["stock_minus_market_20d_bp"] == 0
    assert values["industry_relative_return_20d_bp"] == 0
    assert values["turnover_amount_minor"] == 21000
    assert all(value is None or type(value) is int for value in values.values())
    assert not any("fundamental" in name or "broker" in name for name in values)


def test_future_rows_are_ignored_and_do_not_change_existing_feature_vector() -> None:
    builder = HistoricalFeatureBuilder()
    arguments = {"industry_index_name_by_symbol": {"2330": "半導體類指數"}}

    prefix = builder.compute(_snapshot(), **arguments)
    extended = builder.compute(_snapshot(future=True), **arguments)

    assert extended == prefix


def test_missing_close_inside_window_is_not_compressed_into_a_different_horizon() -> None:
    snapshot = _snapshot()
    prices = list(snapshot.prices)
    prices[-6] = replace(prices[-6], close_price=None)

    row = HistoricalFeatureBuilder().compute(
        replace(snapshot, prices=tuple(prices)),
        industry_index_name_by_symbol={"2330": "半導體類指數"},
    )[0]

    assert dict(row.values)["close_to_ma_20d_bp"] is None
    assert dict(row.values)["trailing_volatility_20d_bp"] is None
