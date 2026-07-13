from data_module.p0_institutional_flow_shadow_adapter import InstitutionalFlowShadowAdapter


def _row() -> dict[str, object]:
    return {
        "symbol": "2330",
        "trade_date": "2026-07-10",
        "available_date": "2026-07-10",
        "source_version": "twse-20260710",
        "foreign_buy": 1200,
        "foreign_sell": 900,
        "foreign_net": 300,
        "trust_buy": 240,
        "trust_sell": 180,
        "trust_net": 60,
        "dealer_buy": 150,
        "dealer_sell": 130,
        "dealer_net": 20,
    }


def test_adapter_normalizes_complete_observation_without_signal_claim() -> None:
    observation = InstitutionalFlowShadowAdapter().adapt(
        row=_row(), decision_date="2026-07-12"
    )

    assert observation.status == "shadow_ready"
    assert observation.source_id == "institutional_flows"
    assert observation.downstream_eligibility == "none"
    assert observation.raw_payload["foreign_net"] == 300
    assert "single_day_flow_is_not_a_trading_signal" in observation.diagnostics


def test_inconsistent_net_value_is_quarantined() -> None:
    row = _row()
    row["foreign_net"] = 301

    observation = InstitutionalFlowShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "foreign_net_mismatch" in observation.diagnostics


def test_future_available_date_is_blocked() -> None:
    row = _row()
    row["available_date"] = "2026-07-13"

    observation = InstitutionalFlowShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "future_available_date" in observation.diagnostics


def test_missing_actor_field_is_blocked() -> None:
    row = _row()
    del row["trust_sell"]

    observation = InstitutionalFlowShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "missing_trust_sell" in observation.diagnostics
