from data_module.p0_source_contract_registry import (
    P0_SOURCE_IDS,
    build_p0_source_contract_registry,
)


def test_registry_contains_all_thirteen_governed_p0_sources() -> None:
    registry = build_p0_source_contract_registry()

    assert len(registry.list()) == 13
    assert {item.source_id for item in registry.list()} == set(P0_SOURCE_IDS)


def test_every_contract_is_versioned_and_fail_closed_before_human_acceptance() -> None:
    registry = build_p0_source_contract_registry()

    for contract in registry.list():
        assert contract.contract_version == "1.0.0"
        assert contract.human_decision == "requires_human_acceptance"
        assert contract.downstream_eligibility == "none"
        assert contract.available_date_required is True
        assert contract.missing_policy
        assert contract.license_status == "requires_review"
        assert contract.production_ingestion_allowed is False


def test_registry_payload_preserves_global_safety_boundary() -> None:
    payload = build_p0_source_contract_registry().to_dict()

    assert payload["schema_version"] == "p0-source-contract-registry.v1"
    assert payload["access_boundary"] == {
        "production_ingestion_allowed": False,
        "scoring_allowed": False,
        "advice_allowed": False,
        "portfolio_allowed": False,
        "scheduler_allowed": False,
    }


def test_unknown_source_cannot_be_silently_accepted() -> None:
    registry = build_p0_source_contract_registry()

    assert registry.get("unknown.source") is None
