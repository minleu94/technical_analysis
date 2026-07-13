from data_module.p0_credit_transaction_shadow_adapter import CreditTransactionShadowAdapter


def _row() -> dict[str, object]:
    return {
        "symbol": "2330",
        "trade_date": "2026-07-10",
        "available_date": "2026-07-10",
        "source_version": "twse-20260710",
        "margin_purchase": 100,
        "margin_balance": 2500,
        "short_sale": 20,
        "short_balance": 400,
    }


def test_credit_observation_is_risk_only_shadow() -> None:
    observation = CreditTransactionShadowAdapter().adapt(
        row=_row(), decision_date="2026-07-12"
    )

    assert observation.status == "shadow_ready"
    assert observation.source_id == "credit_transactions"
    assert observation.downstream_eligibility == "none"
    assert "risk_only_not_directional_signal" in observation.diagnostics


def test_negative_balance_is_blocked() -> None:
    row = _row()
    row["margin_balance"] = -1

    observation = CreditTransactionShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "negative_margin_balance" in observation.diagnostics


def test_missing_required_credit_field_is_blocked() -> None:
    row = _row()
    del row["short_balance"]

    observation = CreditTransactionShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "missing_short_balance" in observation.diagnostics


def test_future_credit_row_is_blocked() -> None:
    row = _row()
    row["available_date"] = "2026-07-13"

    observation = CreditTransactionShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "future_available_date" in observation.diagnostics
