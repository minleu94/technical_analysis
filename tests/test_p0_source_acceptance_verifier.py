from data_module.p0_source_acceptance_verifier import P0SourceAcceptanceVerifier
from data_module.p0_shadow_observation import P0ShadowObservation


def _observation(status: str = "shadow_ready") -> P0ShadowObservation:
    return P0ShadowObservation(
        source_id="institutional_flows",
        symbol="2330",
        decision_date="2026-07-12",
        available_date="2026-07-10",
        source_version="official-v1",
        status=status,
        diagnostics=(),
        raw_payload={},
    )


def test_complete_evidence_only_becomes_eligible_for_human_review() -> None:
    result = P0SourceAcceptanceVerifier(minimum_coverage_bp=8000).verify(
        source_id="institutional_flows",
        decision_date="2026-07-12",
        observations=(_observation(),),
        coverage_bp=9000,
        license_evidence="official open-data terms reviewed",
        quality_evidence="schema and reconciliation passed",
    )

    assert result.status == "eligible_for_human_review"
    assert result.human_decision == "requires_human_acceptance"
    assert result.downstream_eligibility == "none"
    assert result.formal_acceptance_applied is False


def test_missing_license_evidence_blocks_review() -> None:
    result = P0SourceAcceptanceVerifier().verify(
        source_id="institutional_flows",
        decision_date="2026-07-12",
        observations=(_observation(),),
        coverage_bp=10000,
        license_evidence="",
        quality_evidence="passed",
    )

    assert result.status == "blocked"
    assert "missing_license_evidence" in result.diagnostics


def test_blocked_shadow_observation_blocks_review() -> None:
    result = P0SourceAcceptanceVerifier().verify(
        source_id="institutional_flows",
        decision_date="2026-07-12",
        observations=(_observation("blocked"),),
        coverage_bp=10000,
        license_evidence="reviewed",
        quality_evidence="passed",
    )

    assert result.status == "blocked"
    assert "shadow_observation_blocked" in result.diagnostics


def test_insufficient_coverage_blocks_review() -> None:
    result = P0SourceAcceptanceVerifier(minimum_coverage_bp=8000).verify(
        source_id="institutional_flows",
        decision_date="2026-07-12",
        observations=(_observation(),),
        coverage_bp=7999,
        license_evidence="reviewed",
        quality_evidence="passed",
    )

    assert result.status == "blocked"
    assert "coverage_below_minimum" in result.diagnostics


def test_future_observation_is_revalidated_against_service_decision_date() -> None:
    future_observation = P0ShadowObservation(
        source_id="institutional_flows",
        symbol="2330",
        decision_date="2026-07-01",
        available_date="2026-07-13",
        source_version="official-v1",
        status="shadow_ready",
        diagnostics=(),
        raw_payload={},
    )

    result = P0SourceAcceptanceVerifier(minimum_coverage_bp=8000).verify(
        source_id="institutional_flows",
        decision_date="2026-07-12",
        observations=(future_observation,),
        coverage_bp=9000,
        license_evidence="reviewed",
        quality_evidence="passed",
    )

    assert result.status == "blocked"
    assert result.coverage_bp == 0
    assert "future_blocked" in result.diagnostics
    assert "quality_blocked" in result.diagnostics
    assert result.human_decision == "requires_human_acceptance"
    assert result.downstream_eligibility == "none"
    assert result.formal_acceptance_applied is False
