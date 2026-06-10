from decimal import Decimal

from app_module.financial_units import (
    apply_bps_to_price,
    bps_to_rate,
    calculate_fee,
    calculate_slippage_cost,
    round_down_to_lot,
)


def test_bps_to_rate_uses_decimal_basis_points():
    assert bps_to_rate(Decimal("14.25")) == Decimal("0.001425")
    assert bps_to_rate("5") == Decimal("0.0005")


def test_fee_uses_decimal_money_and_minimum_fee():
    assert calculate_fee(Decimal("1000"), Decimal("14.25")) == Decimal("20.00")
    assert calculate_fee(Decimal("900450"), Decimal("14.25")) == Decimal("1283.14")


def test_slippage_and_execution_price_are_quantized_to_cents():
    assert apply_bps_to_price(Decimal("100"), Decimal("5"), side="buy") == Decimal("100.05")
    assert apply_bps_to_price(Decimal("100"), Decimal("5"), side="sell") == Decimal("99.95")
    assert calculate_slippage_cost(9000, Decimal("100"), Decimal("5")) == Decimal("450.00")


def test_round_down_to_lot_uses_integer_shares():
    assert round_down_to_lot(9999, lot_size=1000) == 9000
    assert round_down_to_lot(999, lot_size=1000) == 0
