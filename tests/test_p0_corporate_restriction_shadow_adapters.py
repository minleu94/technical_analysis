import pytest

from data_module.p0_corporate_restriction_shadow_adapters import (
    CorporateActionShadowAdapter,
    TradingRestrictionShadowAdapter,
)


def test_corporate_action_preserves_pit_dates_and_raw_payload() -> None:
    observation = CorporateActionShadowAdapter().adapt(
        source_id="corporate_action.reduction_split_par_value",
        row={
            "symbol": "2330",
            "event_type": "capital_reduction",
            "event_date": "2026-07-20",
            "announcement_date": "2026-07-10",
            "available_date": "2026-07-10",
            "source_version": "official-20260710",
        },
        decision_date="2026-07-12",
    )

    assert observation.status == "shadow_ready"
    assert observation.available_date == "2026-07-10"
    assert observation.effective_from == "2026-07-20"
    assert observation.downstream_eligibility == "none"
    assert observation.raw_payload["event_type"] == "capital_reduction"


def test_future_corporate_action_announcement_is_blocked() -> None:
    observation = CorporateActionShadowAdapter().adapt(
        source_id="corporate_action.ex_dividend_timeline",
        row={
            "symbol": "2330",
            "event_type": "ex_dividend",
            "event_date": "2026-07-20",
            "available_date": "2026-07-13",
            "source_version": "candidate-v1",
        },
        decision_date="2026-07-12",
    )

    assert observation.status == "blocked"
    assert "future_available_date" in observation.diagnostics


def test_corporate_action_rejects_available_before_announcement() -> None:
    observation = CorporateActionShadowAdapter().adapt(
        source_id="corporate_action.ex_dividend_timeline",
        row={
            "symbol": "2330",
            "event_type": "ex_dividend",
            "event_date": "2026-07-20",
            "announcement_date": "2026-07-10",
            "available_date": "2026-07-09",
            "source_version": "candidate-v1",
        },
        decision_date="2026-07-12",
    )

    assert observation.status == "blocked"
    assert "available_before_announcement" in observation.diagnostics


def test_corporate_action_requires_distinct_announcement_evidence() -> None:
    observation = CorporateActionShadowAdapter().adapt(
        source_id="corporate_action.ex_dividend_timeline",
        row={
            "symbol": "2330",
            "event_type": "ex_dividend",
            "event_date": "2026-07-20",
            "available_date": "2026-07-09",
            "source_version": "candidate-v1",
        },
        decision_date="2026-07-12",
    )

    assert observation.status == "blocked"
    assert "missing_announcement_date" in observation.diagnostics


def test_restriction_requires_effective_range() -> None:
    observation = TradingRestrictionShadowAdapter().adapt(
        source_id="microstructure.disposition_stock",
        row={"symbol": "1234", "available_date": "2026-07-10", "source_version": "v1"},
        decision_date="2026-07-12",
    )

    assert observation.status == "blocked"
    assert "missing_effective_from" in observation.diagnostics


def test_adapter_rejects_source_outside_its_contract_family() -> None:
    with pytest.raises(ValueError):
        CorporateActionShadowAdapter().adapt(
            source_id="institutional_flows",
            row={},
            decision_date="2026-07-12",
        )
