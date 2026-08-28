from __future__ import annotations

from dataclasses import dataclass

import pytest

from app_module.portfolio_stress_lab_service import PortfolioStressLabService


@dataclass
class Position:
    stock_code: str
    stock_name: str
    quantity: object
    current_price: object
    is_holding: bool = True


def _positions() -> tuple[Position, ...]:
    return (
        Position("2330", "台積電", 1000, 100),
        Position("2317", "鴻海", 1000, 50),
    )


def test_fast_drop_is_decimal_and_research_only() -> None:
    result = PortfolioStressLabService().evaluate_positions(
        _positions(), scenario_id="fast_drop", as_of_date="2026-08-26"
    )

    assert result.status == "ready"
    assert result.base_market_value == 150000
    assert result.stressed_market_value == 135000
    assert result.value_delta == -15000
    assert result.priced_position_count == 2
    assert result.research_only is True
    assert result.investment_effectiveness_claim is False
    assert result.to_dict()["base_market_value"] == "150000.00"


def test_concentration_event_only_shocks_largest_position() -> None:
    result = PortfolioStressLabService().evaluate_positions(
        _positions(), scenario_id="concentration_event"
    )

    rows = {row.stock_code: row for row in result.positions}
    assert rows["2330"].shock_bp == -2000
    assert rows["2317"].shock_bp == 0
    assert result.stressed_market_value == 130000
    assert result.value_delta == -20000


def test_missing_price_is_partial_and_never_extrapolated() -> None:
    positions = (*_positions(), Position("1101", "台泥", 1000, None))
    result = PortfolioStressLabService().evaluate_positions(positions, scenario_id="fast_drop")

    assert result.status == "partial"
    assert result.priced_position_count == 2
    assert result.total_position_count == 3
    assert result.missing_price_codes == ("1101",)
    assert result.base_market_value == 150000
    assert result.stressed_market_value == 135000
    assert "partial_positions_only_no_extrapolation" in result.warnings


@pytest.mark.parametrize("scenario_id", ("rotation_failure", "source_outage"))
def test_unsupported_or_outage_scenarios_are_fail_closed(scenario_id: str) -> None:
    result = PortfolioStressLabService().evaluate_positions(
        _positions(), scenario_id=scenario_id
    )

    assert result.status == "not_computable"
    assert result.base_market_value is None
    assert result.stressed_market_value is None
    assert result.value_delta is None
    assert result.blockers


def test_empty_positions_are_not_computable() -> None:
    result = PortfolioStressLabService().evaluate_positions((), scenario_id="fast_drop")

    assert result.status == "not_computable"
    assert result.blockers == ("active_positions_missing",)


def test_unknown_scenario_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported stress scenario"):
        PortfolioStressLabService().evaluate_positions(_positions(), scenario_id="unknown")
