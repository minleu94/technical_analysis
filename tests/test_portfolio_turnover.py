from __future__ import annotations

import pytest

from financial_module.portfolio_turnover import canonical_turnover_bp


def test_cash_to_position_and_position_rotation_share_one_way_units() -> None:
    cash_to_a = canonical_turnover_bp(
        current_position_weights_bp=(0, 0),
        current_cash_bp=10_000,
        target_position_weights_bp=(1000, 0),
        target_cash_bp=9000,
    )
    a_to_b = canonical_turnover_bp(
        current_position_weights_bp=(1000, 0),
        current_cash_bp=9000,
        target_position_weights_bp=(0, 1000),
        target_cash_bp=9000,
    )

    assert cash_to_a == 1000
    assert a_to_b == 1000


def test_turnover_rejects_bool_and_incomplete_weight_contracts() -> None:
    with pytest.raises(ValueError, match="integer bp"):
        canonical_turnover_bp(
            current_position_weights_bp=(True,),
            current_cash_bp=9999,
            target_position_weights_bp=(0,),
            target_cash_bp=10_000,
        )
    with pytest.raises(ValueError, match="equal 10000 bp"):
        canonical_turnover_bp(
            current_position_weights_bp=(1000,),
            current_cash_bp=8000,
            target_position_weights_bp=(0,),
            target_cash_bp=10_000,
        )
