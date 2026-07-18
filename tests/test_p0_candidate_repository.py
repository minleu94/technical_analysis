from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from data_module.p0_candidate_repository import (
    CandidateRepository,
    ProductionPathRejectedError,
    validate_candidate_working_copy_path,
)
from data_module.p0_candidate_manifest import QuarantineRecord, RawPayloadManifest
from data_module.p0_source_candidate_contracts import NormalizedP0Observation


UTC = timezone.utc


def _observation(*, foreign_net_shares: int = 1200) -> NormalizedP0Observation:
    return NormalizedP0Observation.build(
        source_id="twse_institutional",
        source_version="twse-T86.v1",
        symbol="2330",
        observation_date="2026-07-10",
        period="daily",
        publication_at=datetime(2026, 7, 10, 17, 30, tzinfo=UTC),
        first_observed_at=datetime(2026, 7, 10, 17, 31, tzinfo=UTC),
        raw_payload_sha256="a" * 64,
        quantities={"foreign_net_shares": foreign_net_shares},
    )


def _manifest(*, run_id: str) -> RawPayloadManifest:
    return RawPayloadManifest.capture(
        run_id=run_id,
        source_id="twse_institutional",
        source_version="twse-T86.v1",
        endpoint_id="twse:T86",
        request_parameters={"date": "20260710"},
        http_status=200,
        http_headers={"Content-Type": "application/json"},
        fetched_at=datetime(2026, 7, 10, 17, 31, tzinfo=UTC),
        payload=b'{"stat":"OK"}',
        parser_version="p0-parser.v1",
        raw_row_count=1,
        accepted_row_count=1,
        duplicate_row_count=0,
        quarantine_row_count=0,
        blocked_row_count=0,
    )


def test_candidate_apply_rejects_production_database_and_descendants(tmp_path: Path) -> None:
    data_root = tmp_path / "formal-data"
    production_db = data_root / "sqlite" / "twstock.db"

    with pytest.raises(ProductionPathRejectedError):
        validate_candidate_working_copy_path(
            production_db,
            production_data_root=data_root,
            production_db_path=production_db,
        )

    with pytest.raises(ProductionPathRejectedError):
        validate_candidate_working_copy_path(
            data_root / "candidate" / "working.sqlite",
            production_data_root=data_root,
            production_db_path=production_db,
        )


def test_candidate_apply_accepts_only_explicit_isolated_working_copy(tmp_path: Path) -> None:
    data_root = tmp_path / "formal-data"
    candidate_db = tmp_path / "isolated-output" / "candidate.sqlite"

    resolved = validate_candidate_working_copy_path(
        candidate_db,
        production_data_root=data_root,
        production_db_path=data_root / "sqlite" / "twstock.db",
    )

    assert resolved == candidate_db.resolve()
    assert candidate_db.exists() is False
    assert candidate_db.parent.exists() is False


def test_missing_working_copy_path_is_rejected_without_side_effect(tmp_path: Path) -> None:
    before = tuple(tmp_path.rglob("*"))

    with pytest.raises(ValueError, match="working-copy"):
        validate_candidate_working_copy_path(
            None,
            production_data_root=tmp_path / "formal-data",
            production_db_path=tmp_path / "formal-data" / "sqlite" / "twstock.db",
        )

    assert tuple(tmp_path.rglob("*")) == before


def test_repository_requires_explicit_confirmation_before_creating_working_copy(tmp_path: Path) -> None:
    candidate_db = tmp_path / "candidate" / "p0.sqlite"
    repository = CandidateRepository(
        candidate_db,
        production_data_root=tmp_path / "formal",
        production_db_path=tmp_path / "formal" / "sqlite" / "twstock.db",
    )

    with pytest.raises(PermissionError, match="confirm-candidate-write"):
        repository.apply(
            manifest=_manifest(run_id="run-1"),
            observations=(_observation(),),
            confirm_candidate_write=False,
        )

    assert candidate_db.exists() is False
    assert candidate_db.parent.exists() is False


def test_repository_duplicate_is_idempotent_and_conflict_is_quarantined(tmp_path: Path) -> None:
    candidate_db = tmp_path / "candidate" / "p0.sqlite"
    repository = CandidateRepository(
        candidate_db,
        production_data_root=tmp_path / "formal",
        production_db_path=tmp_path / "formal" / "sqlite" / "twstock.db",
    )

    first = repository.apply(
        manifest=_manifest(run_id="run-1"),
        observations=(_observation(),),
        confirm_candidate_write=True,
    )
    duplicate = repository.apply(
        manifest=_manifest(run_id="run-2"),
        observations=(_observation(),),
        confirm_candidate_write=True,
    )
    conflict = repository.apply(
        manifest=_manifest(run_id="run-3"),
        observations=(_observation(foreign_net_shares=999),),
        confirm_candidate_write=True,
    )

    assert first.to_dict() == {"accepted": 1, "duplicates": 0, "conflicts": 0, "quarantined": 0}
    assert duplicate.to_dict() == {"accepted": 0, "duplicates": 1, "conflicts": 0, "quarantined": 0}
    assert conflict.to_dict() == {"accepted": 0, "duplicates": 0, "conflicts": 1, "quarantined": 1}

    with sqlite3.connect(candidate_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM p0_candidate_observations").fetchone()[0] == 1
        quarantine = conn.execute(
            "SELECT reason_code FROM p0_candidate_quarantine"
        ).fetchall()
    assert quarantine == [("identity_content_conflict",)]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("raw_row_count", -1, "row counts"),
        ("accepted_row_count", 0, "row conservation"),
        ("payload_sha256", "not-a-digest", "payload_sha256"),
        ("payload_size_bytes", -1, "payload_size_bytes"),
        ("payload_size_bytes", True, "payload_size_bytes"),
    ],
)
def test_manifest_direct_construction_remains_fail_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    manifest = _manifest(run_id="run-1")

    with pytest.raises(ValueError, match=message):
        replace(manifest, **{field: value})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("raw_row_sha256", "invalid", "raw_row_sha256"),
        ("reason_code", "", "identity and reason"),
    ],
)
def test_quarantine_record_direct_construction_remains_fail_closed(
    field: str,
    value: str,
    message: str,
) -> None:
    payload = {
        "run_id": "run-1",
        "source_id": "twse_institutional",
        "source_version": "twse-T86.v1",
        "raw_row_sha256": "a" * 64,
        "reason_code": "malformed_row",
        "detail": "invalid quantity",
    }
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        QuarantineRecord(**payload)
