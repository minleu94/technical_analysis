from dataclasses import replace

import pytest

from data_module.fubon_shadow_candidate_repository import (
    FubonShadowCandidateRepository,
    ProductionPathRejectedError,
    validate_fubon_shadow_db_path,
)
from data_module.fubon_shadow_authorization import FubonShadowComputationAuthorization
from data_module.fubon_pit_validator import FubonPITObservation
from app_module.fubon_shadow_decision_service import FubonShadowDecisionBundle


def test_repository_path_guard_rejects_formal_db(tmp_path) -> None:
    prod_data_root = tmp_path / "FA_Data"
    prod_db = prod_data_root / "sqlite" / "twstock.db"
    prod_db.parent.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ProductionPathRejectedError):
        validate_fubon_shadow_db_path(
            prod_db,
            production_data_root=prod_data_root,
            production_db_path=prod_db,
        )


def test_repository_saves_and_reads_bundle_idempotent(tmp_path) -> None:
    db_file = tmp_path / "candidate_shadow.db"
    repo = FubonShadowCandidateRepository(db_file)

    bundle = FubonShadowDecisionBundle(
        run_id="run-test-123",
        decision_timestamp="2026-07-26T00:00:00+00:00",
        pit_validation_status="passed",
    )

    obs1 = FubonPITObservation(
        source_id="fubon.marketdata",
        source_version="v1",
        symbol="2330",
        market_timestamp="2026-07-25T00:00:00",
        published_at="2026-07-25T00:00:00",
        first_observed_at="2026-07-25T00:00:00",
        available_at="2026-07-25T00:00:00",
        decision_timestamp="2026-07-26T00:00:00",
        revision_id="rev-1",
        raw_payload_sha256="sha256:" + "1" * 64,
        normalized_content_sha256="sha256:" + "2" * 64,
        quality_status="observed",
        missing_or_degraded_reasons=(),
        quarantine_status="clean",
        quantities={"is_disposition": 1},
    )

    res1 = repo.save_shadow_decision_bundle(bundle, [obs1])
    assert res1.accepted_count == 1
    assert res1.duplicate_count == 0

    # Idempotent write
    res2 = repo.save_shadow_decision_bundle(bundle, [obs1])
    assert res2.accepted_count == 0
    assert res2.duplicate_count == 1
    assert res2.bundle_duplicate_count == 1

    read_back = repo.read_shadow_decision_bundle("run-test-123")
    assert read_back is not None
    assert read_back["run_id"] == "run-test-123"

    summary = repo.inspect_summary()
    assert summary["bundle_count"] == 1
    assert summary["observation_count"] == 1

    conflicting = replace(
        obs1,
        normalized_content_sha256="sha256:" + "3" * 64,
    )
    conflict_result = repo.save_shadow_decision_bundle(bundle, [conflicting])
    assert conflict_result.quarantined_count == 1
    assert repo.inspect_summary()["quarantine_count"] == 1


def test_repository_preserves_revisions_and_never_accepts_quarantined_rows(tmp_path) -> None:
    repo = FubonShadowCandidateRepository(tmp_path / "candidate_shadow.db")
    bundle = FubonShadowDecisionBundle(
        run_id="run-revisions",
        decision_timestamp="2026-07-26T00:00:00+00:00",
    )
    base = FubonPITObservation(
        source_id="fubon.marketdata",
        source_version="v1",
        symbol="2330",
        market_timestamp=None,
        published_at=None,
        first_observed_at=None,
        available_at="2026-07-25",
        decision_timestamp="2026-07-26",
        revision_id="rev-1",
        raw_payload_sha256="sha256:" + "1" * 64,
        normalized_content_sha256="sha256:" + "2" * 64,
        quality_status="degraded",
        missing_or_degraded_reasons=("publication_time_missing",),
        quarantine_status="clean",
        quantities={"is_disposition": 1},
    )
    revision = replace(
        base,
        revision_id="rev-2",
        normalized_content_sha256="sha256:" + "3" * 64,
    )
    quarantined = replace(
        base,
        revision_id="rev-bad",
        normalized_content_sha256="sha256:" + "4" * 64,
        quality_status="quarantined",
        quarantine_status="quarantined",
        missing_or_degraded_reasons=("hash_mismatch",),
    )

    result = repo.save_shadow_decision_bundle(
        bundle, [base, revision, quarantined]
    )

    assert result.accepted_count == 2
    assert result.quarantined_count == 1
    assert repo.inspect_summary()["observation_count"] == 2


def test_repository_rejects_conflicting_bundle_and_invalid_digest(tmp_path) -> None:
    repo = FubonShadowCandidateRepository(tmp_path / "candidate_shadow.db")
    bundle = FubonShadowDecisionBundle(run_id="run-conflict")
    repo.save_shadow_decision_bundle(bundle)

    with pytest.raises(ValueError, match="conflicting bundle payload"):
        repo.save_shadow_decision_bundle(
            replace(bundle, decision_timestamp="2026-07-27T00:00:00+00:00")
        )

    invalid_observation = FubonPITObservation(
        source_id="fubon.marketdata",
        source_version="v1",
        symbol="2330",
        market_timestamp=None,
        published_at=None,
        first_observed_at=None,
        available_at="2026-07-25",
        decision_timestamp="2026-07-26",
        revision_id="rev-1",
        raw_payload_sha256="invalid",
        normalized_content_sha256="sha256:" + "2" * 64,
        quality_status="observed",
        missing_or_degraded_reasons=(),
        quarantine_status="clean",
        quantities={},
    )
    with pytest.raises(ValueError, match="observation hashes"):
        repo.save_shadow_decision_bundle(
            FubonShadowDecisionBundle(run_id="run-invalid-hash"),
            [invalid_observation],
        )
