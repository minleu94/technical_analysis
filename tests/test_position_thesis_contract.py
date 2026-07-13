from decimal import Decimal

import pytest

from app_module.position_thesis_contract import (
    PositionInvalidationRule,
    PositionThesisContract,
)


def test_contract_preserves_structured_thesis_and_invalidation_rules() -> None:
    contract = PositionThesisContract(
        position_id="paper-main:2330",
        stock_code="2330",
        entry_date="2026-07-10",
        decision_date="2026-07-10",
        available_date="2026-07-10",
        entry_thesis="relative strength with stable regime",
        holding_horizon_trading_days=20,
        next_review_date="2026-07-17",
        source_trace=("recommendation:rec-1",),
        invalidation_rules=(
            PositionInvalidationRule("close_drawdown_bp", "gte", Decimal("800")),
        ),
    )

    assert contract.invalidation_rules[0].threshold == Decimal("800")
    assert contract.auto_exit_allowed is False
    assert contract.schema_version == "position-thesis.v1"


def test_future_available_thesis_is_rejected() -> None:
    with pytest.raises(ValueError, match="available_date"):
        PositionThesisContract(
            position_id="p",
            stock_code="2330",
            entry_date="2026-07-10",
            decision_date="2026-07-10",
            available_date="2026-07-11",
            entry_thesis="thesis",
            holding_horizon_trading_days=20,
            next_review_date="2026-07-17",
            source_trace=("rec-1",),
            invalidation_rules=(PositionInvalidationRule("risk_bp", "gte", Decimal("500")),),
        )


def test_contract_requires_at_least_one_invalidation_rule() -> None:
    with pytest.raises(ValueError, match="invalidation rule"):
        PositionThesisContract(
            position_id="p",
            stock_code="2330",
            entry_date="2026-07-10",
            decision_date="2026-07-10",
            available_date="2026-07-10",
            entry_thesis="thesis",
            holding_horizon_trading_days=20,
            next_review_date="2026-07-17",
            source_trace=("rec-1",),
            invalidation_rules=(),
        )


def test_rule_rejects_float_threshold_and_unknown_operator() -> None:
    with pytest.raises(ValueError):
        PositionInvalidationRule("risk_bp", "gte", 5.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        PositionInvalidationRule("risk_bp", "contains", Decimal("5"))
