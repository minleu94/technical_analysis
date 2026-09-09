from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from data_module.ml_historical_snapshot_provider import (
    HistoricalIndexObservation,
    HistoricalPriceObservation,
)
from data_module.ml_price_availability_contract import (
    build_price_unavailable_research_contract,
)
from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.historical_contracts import HistoricalFeatureRow
from ml_module.historical_label_builder import (
    CorporateActionLabelEligibility,
    HistoricalLabelBuilder,
)


def _feature(symbol: str) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        symbol=symbol,
        decision_date="2024-01-02",
        feature_as_of_date="2024-01-01",
        available_date="2024-01-02",
        values=tuple((spec.feature_id, None) for spec in CORE_LONG_HISTORY_FEATURE_REGISTRY.specs),
    )


def _prices(symbol: str, multiplier: int) -> tuple[HistoricalPriceObservation, ...]:
    return tuple(
        HistoricalPriceObservation(
            symbol=symbol,
            trading_date=f"2024-01-{day:02d}",
            open_price=Decimal(day * multiplier),
            high_price=Decimal(day * multiplier),
            low_price=Decimal(day * multiplier),
            close_price=Decimal(day * multiplier),
            volume=100,
            turnover_amount_minor=1000,
        )
        for day in range(1, 22)
    )


def _market() -> tuple[HistoricalIndexObservation, ...]:
    return tuple(
        HistoricalIndexObservation("market", f"2024-01-{day:02d}", Decimal(day))
        for day in range(1, 22)
    )


def _clean() -> CorporateActionLabelEligibility:
    return CorporateActionLabelEligibility(
        label_start_date="2024-01-01", label_end_date="2024-01-21",
        eligible=True, quality="clean"
    )


def _gates(*symbols: str) -> dict[tuple[str, str], CorporateActionLabelEligibility]:
    return {(symbol, "2024-01-02"): _clean() for symbol in symbols}


def test_builds_four_mature_labels_on_twentieth_common_trading_day() -> None:
    result = HistoricalLabelBuilder(downside_threshold_bp=-500).build(
        feature_rows=(_feature("2330"),),
        prices=_prices("2330", 2),
        market=_market(),
        label_as_of="2024-01-21",
        corporate_action_by_row=_gates("2330"),
        mode="strict",
    )

    by_id = {label.label_id: label for label in result.labels}
    assert tuple(by_id) == (
        "relative_return_20d_bp",
        "maximum_adverse_excursion_20d_bp",
        "downside_20d_flag",
        "cross_sectional_top_quintile_20d_flag",
    )
    assert by_id["relative_return_20d_bp"].value == 0
    assert by_id["maximum_adverse_excursion_20d_bp"].value == 0
    assert by_id["downside_20d_flag"].value == 0
    assert by_id["cross_sectional_top_quintile_20d_flag"].value == 1
    assert all(label.horizon_end_date == "2024-01-21" for label in result.labels)
    assert all(label.available_date == "2024-01-21" for label in result.labels)
    assert all(label.maturity_status == "ready" for label in result.labels)
    assert result.formal_oos_allowed is True


def test_uses_market_calendar_and_does_not_compress_a_missing_stock_day() -> None:
    prices = tuple(row for row in _prices("2330", 2) if row.trading_date != "2024-01-10")
    result = HistoricalLabelBuilder().build(
        feature_rows=(_feature("2330"),), prices=prices, market=_market(),
        label_as_of="2024-01-21", corporate_action_by_row=_gates("2330"),
        mode="strict",
    )

    assert result.labels == ()
    assert result.excluded_diagnostics == {"price_gap_in_label_window": 1}


def test_price_unavailable_contract_blocks_label_window_without_bridging() -> None:
    contract = build_price_unavailable_research_contract(
        symbol="2330",
        date_iso="2024-01-10",
        raw_row={
            "symbol": "2330",
            "open": "--",
            "high": "--",
            "low": "--",
            "close": "--",
            "volume": 100,
        },
        feature_window_dates=("2024-01-10",),
        label_window_dates=tuple(
            f"2024-01-{day:02d}" for day in range(1, 22)
        ),
    )
    result = HistoricalLabelBuilder().build(
        feature_rows=(_feature("2330"),),
        prices=_prices("2330", 2),
        market=_market(),
        label_as_of="2024-01-21",
        corporate_action_by_row=_gates("2330"),
        mode="strict",
        price_unavailable_contracts=(contract,),
    )

    assert result.labels == ()
    assert result.excluded_diagnostics == {
        "price_unavailable_in_label_window": 1
    }


def test_label_builder_auto_contracts_in_row_price_gap() -> None:
    prices = list(_prices("2330", 2))
    prices[9] = replace(
        prices[9],
        open_price=None,
        high_price=None,
        low_price=None,
        close_price=None,
    )
    result = HistoricalLabelBuilder().build(
        feature_rows=(_feature("2330"),),
        prices=tuple(prices),
        market=_market(),
        label_as_of="2024-01-21",
        corporate_action_by_row=_gates("2330"),
        mode="strict",
    )

    assert result.labels == ()
    assert result.excluded_diagnostics == {
        "price_unavailable_in_label_window": 1
    }


def test_immature_window_is_diagnostic_and_does_not_read_after_label_as_of() -> None:
    result = HistoricalLabelBuilder().build(
        feature_rows=(_feature("2330"),), prices=_prices("2330", 2), market=_market(),
        label_as_of="2024-01-20", corporate_action_by_row=_gates("2330"),
        mode="strict",
    )

    assert result.labels == ()
    assert result.excluded_diagnostics == {"immature_label_window": 1}


def test_strict_excludes_unknown_corporate_coverage_but_research_keeps_degraded() -> None:
    unknown = CorporateActionLabelEligibility(
        label_start_date="2024-01-01", label_end_date="2024-01-21",
        eligible=False, quality="degraded", reasons=("coverage_unknown",)
    )
    kwargs = dict(
        feature_rows=(_feature("2330"),), prices=_prices("2330", 2), market=_market(),
        label_as_of="2024-01-21", corporate_action_by_row={("2330", "2024-01-02"): unknown},
    )

    strict = HistoricalLabelBuilder().build(**kwargs, mode="strict")
    research = HistoricalLabelBuilder().build(**kwargs, mode="research")

    assert strict.labels == ()
    assert strict.excluded_diagnostics == {"corporate_action_coverage_blocked": 1}
    assert len(research.labels) == 4
    assert {label.quality for label in research.labels} == {"degraded"}
    assert research.formal_oos_allowed is False
    assert research.corporate_action_coverage == "research_only_degraded"
    assert research.blockers == ("coverage_unknown",)


def test_cross_sectional_top_quintile_is_deterministic_under_input_reordering() -> None:
    prices = (*_prices("1101", 1), *_prices("2330", 2), *_prices("3008", 3),
              *_prices("6505", 4), *_prices("9999", 5))
    features = tuple(_feature(symbol) for symbol in ("1101", "2330", "3008", "6505", "9999"))
    gates = {row.symbol: _clean() for row in features}
    builder = HistoricalLabelBuilder()

    first = builder.build(
        feature_rows=features, prices=prices, market=_market(), label_as_of="2024-01-21",
        corporate_action_by_row={
            (symbol, "2024-01-02"): gate for symbol, gate in gates.items()
        }, mode="strict",
    )
    second = builder.build(
        feature_rows=tuple(reversed(features)), prices=tuple(reversed(prices)),
        market=tuple(reversed(_market())), label_as_of="2024-01-21",
        corporate_action_by_row={
            (symbol, "2024-01-02"): gate for symbol, gate in gates.items()
        }, mode="strict",
    )

    assert second == first
    top = [label.symbol for label in first.labels if label.label_id.endswith("top_quintile_20d_flag") and label.value == 1]
    assert top == ["1101"]


def test_future_observations_do_not_change_labels_at_same_label_as_of() -> None:
    builder = HistoricalLabelBuilder()
    prices = _prices("2330", 2)
    future = replace(prices[-1], trading_date="2024-02-01", close_price=Decimal("9999"))
    kwargs = dict(
        feature_rows=(_feature("2330"),), market=_market(), label_as_of="2024-01-21",
        corporate_action_by_row=_gates("2330"), mode="strict",
    )
    assert builder.build(prices=prices, **kwargs) == builder.build(prices=(*prices, future), **kwargs)


def test_corporate_gate_for_a_different_label_window_is_rejected() -> None:
    wrong_window = CorporateActionLabelEligibility(
        label_start_date="2024-01-01", label_end_date="2024-01-20",
        eligible=True, quality="clean",
    )
    result = HistoricalLabelBuilder().build(
        feature_rows=(_feature("2330"),), prices=_prices("2330", 2), market=_market(),
        label_as_of="2024-01-21",
        corporate_action_by_row={("2330", "2024-01-02"): wrong_window},
        mode="strict",
    )

    assert result.labels == ()
    assert result.excluded_diagnostics == {"corporate_action_gate_window_mismatch": 1}
