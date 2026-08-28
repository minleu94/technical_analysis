from __future__ import annotations

from data_module.p0_source_acquisition_routes import (
    build_p0_acquisition_route_registry,
)
from data_module.p0_source_contract_registry import P0_SOURCE_IDS


def test_every_p0_source_has_a_governed_acquisition_route() -> None:
    registry = build_p0_acquisition_route_registry()

    assert all(registry.for_source(source_id) for source_id in P0_SOURCE_IDS)
    payload = registry.to_dict()
    assert payload["p0_source_count"] == 13
    assert payload["route_count"] >= 26
    assert payload["sources_with_multiple_routes"] >= 12
    assert payload["boundary"] == {
        "candidate_evidence_only": True,
        "source_acceptance_granted": False,
        "formal_eligible": False,
        "production_ingestion_allowed": False,
        "scheduler_allowed": False,
    }
    assert all(route["formal_eligible"] is False for route in payload["routes"])


def test_limit_lock_uses_real_twse_twt84u_and_tpex_alternate() -> None:
    routes = build_p0_acquisition_route_registry().for_source(
        "microstructure.limit_lock"
    )

    assert {route.route_id for route in routes} == {
        "twse.TWT84U",
        "tpex.tpex_ceil_non_trading",
    }
    assert "MI_INDEX" not in " ".join(route.endpoint for route in routes)
