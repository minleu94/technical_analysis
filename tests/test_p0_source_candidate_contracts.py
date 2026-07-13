from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data_module.p0_candidate_manifest import QuarantineRecord, RawPayloadManifest
from data_module.p0_source_candidate_contracts import (
    AvailabilityEvidence,
    NormalizedP0Observation,
)


UTC = timezone.utc


def test_normalized_observation_exposes_only_canonical_identity_names() -> None:
    observation = NormalizedP0Observation.build(
        source_id="twse_institutional",
        source_version="twse-T86.v1",
        symbol="2330",
        observation_date="2026-07-10",
        period="daily",
        publication_at=datetime(2026, 7, 10, 17, 30, tzinfo=UTC),
        first_observed_at=datetime(2026, 7, 10, 17, 31, tzinfo=UTC),
        raw_payload_sha256="a" * 64,
        quantities={"foreign_net_shares": 1200},
    )

    payload = observation.to_dict()

    assert payload["symbol"] == "2330"
    assert payload["observation_date"] == "2026-07-10"
    assert "stock_code" not in payload
    assert "decision_date" not in payload
    assert payload["downstream_eligibility"] == "none"
    assert payload["human_decision"] == "requires_human_acceptance"
    assert payload["production_scheduler_allowed"] is False


def test_official_publication_timestamp_is_the_verified_available_time() -> None:
    publication_at = datetime(2026, 7, 10, 17, 30, tzinfo=UTC)
    evidence = AvailabilityEvidence.resolve(
        publication_at=publication_at,
        first_observed_at=datetime(2026, 7, 10, 17, 31, tzinfo=UTC),
    )

    assert evidence.available_at == publication_at
    assert evidence.quality == "verified"
    assert evidence.evidence_kind == "official_publication_timestamp"


@pytest.mark.parametrize("observation_date", ["2026-07-10", "2026-07-07"])
def test_missing_publication_uses_actual_first_observed_not_derived_date(
    observation_date: str,
) -> None:
    first_observed = datetime(2026, 7, 13, 9, 15, tzinfo=UTC)

    evidence = AvailabilityEvidence.resolve(
        publication_at=None,
        first_observed_at=first_observed,
    )

    assert evidence.available_at == first_observed
    assert evidence.quality == "degraded"
    assert evidence.evidence_kind == "first_observed_only"
    assert evidence.available_at.date().isoformat() != observation_date
    assert "official_publication_timestamp_missing" in evidence.warnings


def test_availability_timestamps_must_include_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        AvailabilityEvidence.resolve(
            publication_at=None,
            first_observed_at=datetime(2026, 7, 13, 9, 15),
        )


def test_raw_manifest_hashes_payload_and_sanitizes_secret_parameters() -> None:
    manifest = RawPayloadManifest.capture(
        run_id="run-1",
        source_id="twse_institutional",
        source_version="twse-T86.v1",
        endpoint_id="twse:T86",
        request_parameters={"date": "20260710", "token": "secret"},
        http_status=200,
        http_headers={"Content-Type": "application/json", "Set-Cookie": "secret"},
        fetched_at=datetime(2026, 7, 10, 17, 31, tzinfo=UTC),
        payload=b'{"stat":"OK"}',
        parser_version="p0-parser.v1",
        raw_row_count=1,
        accepted_row_count=1,
        duplicate_row_count=0,
        quarantine_row_count=0,
        blocked_row_count=0,
    )

    payload = manifest.to_dict()

    assert payload["request_parameters"] == {"date": "20260710"}
    assert payload["http_headers"] == {"content-type": "application/json"}
    assert len(payload["payload_sha256"]) == 64
    assert payload["payload_size_bytes"] == len(b'{"stat":"OK"}')
    assert payload["raw_row_count"] == 1


def test_manifest_enforces_row_conservation() -> None:
    with pytest.raises(ValueError, match="row conservation"):
        RawPayloadManifest.capture(
            run_id="run-1",
            source_id="twse_institutional",
            source_version="twse-T86.v1",
            endpoint_id="twse:T86",
            request_parameters={},
            http_status=200,
            http_headers={},
            fetched_at=datetime(2026, 7, 10, 17, 31, tzinfo=UTC),
            payload=b"{}",
            parser_version="p0-parser.v1",
            raw_row_count=2,
            accepted_row_count=1,
            duplicate_row_count=0,
            quarantine_row_count=0,
            blocked_row_count=0,
        )


def test_quarantine_record_preserves_raw_hash_reason_and_source_version() -> None:
    record = QuarantineRecord.from_raw_row(
        run_id="run-1",
        source_id="tdcc_shareholding",
        source_version="tdcc-1-5.v1",
        raw_row={"證券代號": "2330", "持股分級": "invalid"},
        reason_code="malformed_integer",
        detail="持股分級不是整數",
    )

    assert len(record.raw_row_sha256) == 64
    assert record.reason_code == "malformed_integer"
    assert record.source_version == "tdcc-1-5.v1"
