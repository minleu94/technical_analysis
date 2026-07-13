from __future__ import annotations

import pytest

from app_module.evidence_rehearsal_source_comparison import (
    P0SourceShadowComparisonService,
)
from data_module.p0_institutional_flow_shadow_adapter import InstitutionalFlowShadowAdapter


def _ready_institutional_observation():
    return InstitutionalFlowShadowAdapter().adapt(
        row={
            "symbol": "2330",
            "trade_date": "2026-07-10",
            "available_date": "2026-07-10",
            "source_version": "official-v1",
            "foreign_buy": 1200,
            "foreign_sell": 900,
            "foreign_net": 300,
            "trust_buy": 240,
            "trust_sell": 180,
            "trust_net": 60,
            "dealer_buy": 150,
            "dealer_sell": 130,
            "dealer_net": 20,
        },
        decision_date="2026-07-12",
    )


def _item(payload: dict, source_id: str) -> dict:
    return next(item for item in payload["items"] if item["source_id"] == source_id)


def test_all_p0_contracts_remain_visible_when_no_source_has_been_ingested() -> None:
    payload = P0SourceShadowComparisonService(decision_date="2026-07-12").build_report().to_dict()

    assert len(payload["items"]) == 13
    assert payload["access_boundary"] == {
        "production_ingestion_allowed": False,
        "scoring_allowed": False,
        "advice_allowed": False,
        "portfolio_allowed": False,
        "scheduler_allowed": False,
    }
    for item in payload["items"]:
        assert item["shadow"]["coverage_bp"] == 0
        assert "source_not_ingested" in item["blockers"]
        assert "source_absent" not in item["blockers"]
        assert item["review_status"] == "blocked"


def test_observed_shadow_candidate_is_only_eligible_for_human_review() -> None:
    observation = _ready_institutional_observation()

    payload = P0SourceShadowComparisonService(
        decision_date="2026-07-12",
        shadow_observations=(observation,),
    ).build_report().to_dict()
    item = _item(payload, "institutional_flows")

    assert item["shadow"]["quality"] == "observed"
    assert item["review_status"] == "eligible_for_human_review"
    assert item["accepted"] is False
    assert item["downstream_eligibility"] == "none"
    assert item["scoring_eligible"] is False
    assert item["advice_eligible"] is False
    assert item["eligibility_delta"] == {"baseline": "none", "shadow": "none"}


@pytest.mark.parametrize(
    ("source_outages", "schema_missing_sources", "expected_blocker"),
    (
        ({"institutional_flows": "upstream_timeout"}, (), "source_outage:upstream_timeout"),
        ({}, ("institutional_flows",), "schema_missing"),
    ),
)
def test_ready_shadow_observation_is_fail_closed_when_source_is_blocked(
    source_outages: dict[str, str],
    schema_missing_sources: tuple[str, ...],
    expected_blocker: str,
) -> None:
    payload = P0SourceShadowComparisonService(
        decision_date="2026-07-12",
        shadow_observations=(_ready_institutional_observation(),),
        source_outages=source_outages,
        schema_missing_sources=schema_missing_sources,
    ).build_report().to_dict()
    item = _item(payload, "institutional_flows")

    assert expected_blocker in item["blockers"]
    assert item["shadow"]["quality"] == "blocked"
    assert item["shadow"]["coverage_bp"] == 0
    assert item["review_status"] == "blocked"


def test_outage_schema_and_future_data_emit_explicit_blockers_and_safe_guidance() -> None:
    future_observation = InstitutionalFlowShadowAdapter().adapt(
        row={
            **dict(_ready_institutional_observation().raw_payload),
            "available_date": "2026-07-13",
        },
        decision_date="2026-07-12",
    )

    payload = P0SourceShadowComparisonService(
        decision_date="2026-07-12",
        shadow_observations=(future_observation,),
        source_outages={"credit_transactions": "upstream_timeout"},
        schema_missing_sources={"tdcc_shareholding"},
    ).build_report().to_dict()

    institutional = _item(payload, "institutional_flows")
    credit = _item(payload, "credit_transactions")
    tdcc = _item(payload, "tdcc_shareholding")
    assert "future_available_date" in institutional["blockers"]
    assert institutional["shadow"]["quality"] == "blocked"
    assert "quarantine_observation" in institutional["guidance"]
    assert "source_outage:upstream_timeout" in credit["blockers"]
    assert "retry_shadow_observation" in credit["guidance"]
    assert "schema_missing" in tdcc["blockers"]
    assert "quarantine_observation" in tdcc["guidance"]
