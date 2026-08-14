from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from app_module.rule_champion_snapshot_service import (
    PersistedFormalDecisionArtifactRepository,
    RuleChampionSnapshotService,
    load_verified_rule_champion_snapshot_history,
)
from ml_module.allocation_oos_portfolio_replay import (
    _load_formal_rule_champion_history_custody,
)


_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
_STORE_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
_TEST_KEY = "isolated-test-controlled-store-key"
_TEST_STORE_ID = "controlled-store:test"


@pytest.fixture(autouse=True)
def _controlled_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the test runtime injects the attestation secret and store identity."""
    monkeypatch.setenv(_KEY_ENV, _TEST_KEY)
    monkeypatch.setenv(_STORE_ENV, _TEST_STORE_ID)


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _artifact(
    *,
    snapshot_id: str = "decision:2026-07-13:2330",
    decision_timestamp: str = "2026-07-13T09:00:00+08:00",
    rank: int = 1,
    source_lineage_hash: str = "sha256:" + "2" * 64,
    restrictions_hash: str = "sha256:" + "3" * 64,
    store_id: str = _TEST_STORE_ID,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "FormalRuleDecisionSnapshot.v1",
        "source_artifact_kind": "formal_rule_only_immutable_decision_snapshot",
        "rule_only_proof": "formal_rule_only",
        "decision_snapshot_id": snapshot_id,
        "decision_timestamp": decision_timestamp,
        "symbol": "2330",
        "rule_score_bp": 7_500,
        "rule_rank": rank,
        "source_lineage_artifact_id": f"decision-ledger:{snapshot_id}",
        "source_lineage_hash": source_lineage_hash,
        "restrictions_hash": restrictions_hash,
    }
    payload["immutable_snapshot_hash"] = "sha256:" + hashlib.sha256(
        _canonical_bytes(payload)
    ).hexdigest()
    payload["registered_store_id"] = store_id
    payload["attestation_signature"] = "hmac-sha256:" + hmac.new(
        _TEST_KEY.encode("utf-8"), _canonical_bytes(payload), hashlib.sha256
    ).hexdigest()
    return payload


def _resign(artifact: dict[str, object]) -> None:
    artifact["attestation_signature"] = "hmac-sha256:" + hmac.new(
        _TEST_KEY.encode("utf-8"),
        _canonical_bytes({key: value for key, value in artifact.items() if key != "attestation_signature"}),
        hashlib.sha256,
    ).hexdigest()


class _ControlledPersistedArtifactLoader:
    """Test-only read-only loader that yields persisted artifact bytes."""

    def __init__(self, artifacts: Mapping[str, Mapping[str, object]]) -> None:
        self._artifacts = dict(artifacts)

    def load_registered_formal_decision_bytes(self, decision_snapshot_id: str) -> bytes | None:
        artifact = self._artifacts.get(decision_snapshot_id)
        return _canonical_bytes(artifact) if artifact is not None else None


def _repository(*artifacts: Mapping[str, object]) -> PersistedFormalDecisionArtifactRepository:
    return PersistedFormalDecisionArtifactRepository(
        _ControlledPersistedArtifactLoader(
            {str(artifact["decision_snapshot_id"]): artifact for artifact in artifacts}
        )
    )


def _build(repository: PersistedFormalDecisionArtifactRepository, *snapshot_ids: str):
    return RuleChampionSnapshotService().build(
        strategy_version="rule-v1",
        policy_version="policy-v1",
        score_configuration_hash="sha256:" + "0" * 64,
        universe_hash="sha256:" + "1" * 64,
        selection_capacity=10,
        repository=repository,
        decision_snapshot_ids=snapshot_ids,
    )


def test_builds_only_from_hmac_attested_controlled_store_bytes() -> None:
    snapshot = _build(_repository(_artifact()), "decision:2026-07-13:2330")

    assert snapshot.source_kind == "formal_rule_only"
    assert snapshot.rule_only_proof == "formal_rule_only"
    assert snapshot.decision_snapshot_ids == ("decision:2026-07-13:2330",)
    assert snapshot.content_hash.startswith("sha256:")


@pytest.mark.parametrize(
    ("mutator", "expected_blocker", "resign"),
    [
        (lambda artifact: artifact.pop("attestation_signature"), "attestation_signature", False),
        (lambda artifact: artifact.__setitem__("attestation_signature", "hmac-sha256:" + "0" * 64), "attestation", False),
        (lambda artifact: artifact.__setitem__("registered_store_id", "attacker-store"), "registered_store_id", True),
        (lambda artifact: artifact.__setitem__("source_lineage_artifact_id", ""), "source_lineage_artifact_id", True),
        (lambda artifact: artifact.__setitem__("decision_timestamp", ""), "decision_timestamp", True),
        (lambda artifact: artifact.__setitem__("restrictions_hash", "not-a-hash"), "restrictions_hash", True),
        (lambda artifact: artifact.__setitem__("rule_only_proof", "forged"), "rule-only proof", True),
    ],
)
def test_missing_or_tampered_required_proof_fails_closed(
    mutator, expected_blocker: str, resign: bool
) -> None:
    artifact = _artifact()
    mutator(artifact)
    if resign:
        _resign(artifact)

    with pytest.raises(ValueError, match=f"needs_human_decision.*{expected_blocker}"):
        _build(_repository(artifact), "decision:2026-07-13:2330")


def test_unkeyed_attacker_repository_with_self_consistent_sha_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attacker_artifact = _artifact()
    monkeypatch.delenv(_KEY_ENV)

    with pytest.raises(ValueError, match="needs_human_decision.*runtime attestation key"):
        _build(_repository(attacker_artifact), "decision:2026-07-13:2330")


def test_attacker_loader_cannot_bypass_missing_controlled_runtime_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AttackerLoader:
        def load_registered_formal_decision_bytes(self, _decision_snapshot_id: str) -> bytes:
            return _canonical_bytes(_artifact())

    monkeypatch.delenv(_KEY_ENV)
    repository = PersistedFormalDecisionArtifactRepository(AttackerLoader())

    with pytest.raises(ValueError, match="needs_human_decision.*runtime attestation key"):
        _build(repository, "decision:2026-07-13:2330")


def test_missing_registered_identity_or_artifact_bytes_is_rejected() -> None:
    class MissingBytesLoader:
        def load_registered_formal_decision_bytes(self, _decision_snapshot_id: str) -> None:
            return None

    with pytest.raises(ValueError, match="needs_human_decision.*registered"):
        _build(PersistedFormalDecisionArtifactRepository(MissingBytesLoader()), "decision:2026-07-13:2330")


def test_caller_cannot_supply_an_attestation_key_parameter() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'attestation_key'"):
        PersistedFormalDecisionArtifactRepository(  # type: ignore[call-arg]
            _ControlledPersistedArtifactLoader({}), attestation_key=_TEST_KEY
        )


def test_noncontiguous_ranks_and_cross_decision_timestamp_remain_rejected() -> None:
    first = _artifact(rank=1)
    second = _artifact(
        snapshot_id="decision:2026-07-14:2317",
        decision_timestamp="2026-07-14T09:00:00+08:00",
        rank=2,
    )
    with pytest.raises(ValueError, match="same decision_timestamp"):
        _build(_repository(first, second), first["decision_snapshot_id"], second["decision_snapshot_id"])


def _history_payload(snapshot) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "rule-champion-snapshot-history.v1",
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "rule_only_proof": "formal_rule_only",
        "registered_store_id": _TEST_STORE_ID,
        "decision_dates": ["2026-07-13"],
        "snapshot_count": 1,
        "snapshots": [snapshot.to_manifest()],
    }
    body["manifest_hash"] = "sha256:" + hashlib.sha256(
        _canonical_bytes(body)
    ).hexdigest()
    return body


def test_history_loader_verifies_signed_snapshot_manifest_and_date_coverage(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    snapshot = _build(
        _repository(artifact),
        str(artifact["decision_snapshot_id"]),
    )
    path = tmp_path / "rule_champion_history.json"
    path.write_text(
        json.dumps(_history_payload(snapshot), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    custody = load_verified_rule_champion_snapshot_history(
        path,
        decision_dates=("2026-07-13",),
        training_as_of="2026-07-13T23:59:59+08:00",
    )

    assert custody.decision_dates == ("2026-07-13",)
    assert custody.snapshot_by_date["2026-07-13"].decision_rows[0].symbol == "2330"
    assert custody.custody_payload()["research_only"] is False


def test_history_loader_rejects_research_shadow_and_missing_coverage(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    snapshot = _build(
        _repository(artifact),
        str(artifact["decision_snapshot_id"]),
    )
    payload = _history_payload(snapshot)
    payload["research_only"] = True
    payload["manifest_hash"] = "sha256:" + hashlib.sha256(
        _canonical_bytes({key: value for key, value in payload.items() if key != "manifest_hash"})
    ).hexdigest()
    path = tmp_path / "research_history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="research-only"):
        load_verified_rule_champion_snapshot_history(path)

    valid = _history_payload(snapshot)
    valid_path = tmp_path / "valid_history.json"
    valid_path.write_text(json.dumps(valid), encoding="utf-8")
    with pytest.raises(ValueError, match="does not cover assembly"):
        load_verified_rule_champion_snapshot_history(
            valid_path,
            decision_dates=("2026-07-12",),
        )


def test_oos_consumer_revalidates_rule_history_custody(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    snapshot = _build(
        _repository(artifact),
        str(artifact["decision_snapshot_id"]),
    )
    path = tmp_path / "rule_champion_history.json"
    path.write_text(
        json.dumps(_history_payload(snapshot), ensure_ascii=False),
        encoding="utf-8",
    )
    history = load_verified_rule_champion_snapshot_history(path)

    verified = _load_formal_rule_champion_history_custody(
        {"formal_rule_champion_history": history.custody_payload()},
        training={"training_as_of": "2026-07-13T23:59:59+08:00"},
    )

    assert verified is not None
    assert verified.manifest_hash == history.manifest_hash
    assert verified.snapshot_by_date["2026-07-13"].decision_rows[0].symbol == (
        "2330"
    )
