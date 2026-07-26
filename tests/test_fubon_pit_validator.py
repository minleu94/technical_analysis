from hashlib import sha256
import json

from data_module.fubon_pit_validator import (
    FubonPITObservationValidator,
)


def test_valid_decision_time_observation_accepted() -> None:
    validator = FubonPITObservationValidator()
    obs, diag = validator.validate_observation(
        {
            "symbol": "2330",
            "available_at": "2026-07-26T00:00:00+00:00",
            "published_at": "2026-07-26T00:00:00+00:00",
            "quantities": {"is_disposition": 1},
        },
        decision_timestamp="2026-07-26T01:00:00+00:00",
    )
    assert obs is not None
    assert obs.quality_status == "observed"
    assert obs.quarantine_status == "clean"


def test_future_observation_rejected() -> None:
    validator = FubonPITObservationValidator()
    obs, diag = validator.validate_observation(
        {
            "symbol": "2330",
            "available_at": "2026-07-27T00:00:00+00:00",
            "quantities": {"is_disposition": 1},
        },
        decision_timestamp="2026-07-26T01:00:00+00:00",
    )
    assert obs is None
    assert "rejected_future_observation_pit_violation" in diag


def test_missing_availability_fails_closed_no_time_guessing() -> None:
    validator = FubonPITObservationValidator()
    obs, diag = validator.validate_observation(
        {
            "symbol": "2330",
            "quantities": {"is_disposition": 1},
        },
        decision_timestamp="2026-07-26T01:00:00+00:00",
    )
    assert obs is None
    assert "fubon_missing_availability_timestamp" in diag


def test_hash_mismatch_quarantined() -> None:
    validator = FubonPITObservationValidator()
    obs, diag = validator.validate_observation(
        {
            "symbol": "2330",
            "available_at": "2026-07-25T00:00:00+00:00",
            "normalized_content_sha256": "sha256:wronghash",
            "quantities": {"is_disposition": 1},
        },
        decision_timestamp="2026-07-26T01:00:00+00:00",
    )
    assert obs is not None
    assert obs.quarantine_status == "quarantined"


def test_duplicate_handling_idempotent_vs_conflicting() -> None:
    validator = FubonPITObservationValidator()
    batch = [
        {
            "symbol": "2330",
            "available_at": "2026-07-25T00:00:00+00:00",
            "quantities": {"is_disposition": 1},
        },
        {
            "symbol": "2330",
            "available_at": "2026-07-25T00:00:00+00:00",
            "quantities": {"is_disposition": 1},
        },
    ]
    res = validator.validate_batch(batch, decision_timestamp="2026-07-26T01:00:00+00:00")
    assert len(res.accepted_observations) + len(res.degraded_observations) == 1

    batch_conflict = [
        {
            "symbol": "2330",
            "available_at": "2026-07-25T00:00:00+00:00",
            "quantities": {"is_disposition": 1},
        },
        {
            "symbol": "2330",
            "available_at": "2026-07-25T00:00:00+00:00",
            "quantities": {"is_disposition": 0},
        },
    ]
    res_conf = validator.validate_batch(batch_conflict, decision_timestamp="2026-07-26T01:00:00+00:00")
    assert len(res_conf.quarantined_observations) == 1


def test_date_only_available_at_compares_to_aware_decision_by_date() -> None:
    observation, diagnostics = FubonPITObservationValidator().validate_observation(
        {
            "symbol": "2330",
            "available_date": "2026-07-25",
            "quantities": {"is_disposition": 1},
        },
        decision_timestamp="2026-07-26T01:00:00+00:00",
    )

    assert observation is not None
    assert "rejected_invalid_available_at" not in diagnostics


def test_mixed_naive_and_aware_datetimes_fail_closed_without_guessing_timezone() -> None:
    observation, diagnostics = FubonPITObservationValidator().validate_observation(
        {
            "symbol": "2330",
            "available_at": "2026-07-25T12:00:00",
            "quantities": {"is_disposition": 1},
        },
        decision_timestamp="2026-07-26T01:00:00+00:00",
    )

    assert observation is None
    assert diagnostics == ["rejected_invalid_available_at"]


def test_declared_raw_hash_is_verified_without_hash_declaration_fields() -> None:
    payload = {
        "symbol": "2330",
        "available_at": "2026-07-25T00:00:00+00:00",
        "quantities": {"is_disposition": 1},
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )
    payload["raw_payload_sha256"] = f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"

    observation, diagnostics = FubonPITObservationValidator().validate_observation(
        payload,
        decision_timestamp="2026-07-26T01:00:00+00:00",
    )

    assert observation is not None
    assert observation.quarantine_status == "clean"
    assert "fubon_raw_hash_mismatch" not in diagnostics


def test_raw_hash_mismatch_and_invalid_timestamp_sequence_are_quarantined() -> None:
    observation, diagnostics = FubonPITObservationValidator().validate_observation(
        {
            "symbol": "2330",
            "published_at": "2026-07-25T02:00:00+00:00",
            "first_observed_at": "2026-07-25T01:00:00+00:00",
            "available_at": "2026-07-25T01:00:00+00:00",
            "raw_payload_sha256": "sha256:" + "0" * 64,
            "quantities": {"is_disposition": 1},
        },
        decision_timestamp="2026-07-26T01:00:00+00:00",
    )

    assert observation is not None
    assert observation.quarantine_status == "quarantined"
    assert "fubon_raw_hash_mismatch" in diagnostics
    assert any("timestamp_sequence_inconsistency" in item for item in diagnostics)
