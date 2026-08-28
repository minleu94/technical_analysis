from data_module.p0_source_contract_registry import (
    P0_CANDIDATE_SOURCE_ALIGNMENT_VERSION,
    P0_SOURCE_IDS,
    build_p0_source_contract_registry,
    map_candidate_source_id,
    map_legacy_source_id,
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


def test_legacy_id_alignment_never_rewrites_decisions_and_reports_unmapped() -> None:
    aligned = map_legacy_source_id("institutional_flows")
    unmapped = map_legacy_source_id("legacy.broker.branch")

    assert aligned.source_id == "institutional_flows"
    assert aligned.blockers == ()
    assert unmapped.source_id is None
    assert unmapped.blockers == ("unmapped_legacy_id",)


def test_mops_candidate_identity_maps_only_to_quarterly_financials_contract() -> None:
    aligned = map_candidate_source_id("mops.statement.publication")

    assert aligned.candidate_source_id == "mops.statement.publication"
    assert aligned.source_id == "pit.quarterly_financials"
    assert aligned.mapping_version == P0_CANDIDATE_SOURCE_ALIGNMENT_VERSION
    assert aligned.blockers == ()


def test_phase3c_provider_identities_map_explicitly_to_canonical_p0_contracts() -> None:
    expected = {
        "twse_institutional": "institutional_flows",
        "twse_credit": "credit_transactions",
        "tdcc_shareholding": "tdcc_shareholding",
    }

    for candidate_source_id, governed_source_id in expected.items():
        aligned = map_candidate_source_id(candidate_source_id)
        assert aligned.source_id == governed_source_id
        assert aligned.mapping_version == P0_CANDIDATE_SOURCE_ALIGNMENT_VERSION
        assert aligned.blockers == ()


def test_unknown_candidate_identity_fails_closed() -> None:
    alignment = map_candidate_source_id("mops.unreviewed.numeric_source")

    assert alignment.source_id is None
    assert alignment.mapping_version == P0_CANDIDATE_SOURCE_ALIGNMENT_VERSION
    assert alignment.blockers == ("unmapped_candidate_source_id",)
