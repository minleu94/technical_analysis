from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
from pathlib import Path
from collections.abc import Mapping

import pytest

from data_module.prospective_formal_clock import (
    build_clock_manifest,
    canonical_json,
    load_clock_manifest,
    load_clock_manifest_for_capture,
    payload_hash,
)
from data_module.prospective_rule_champion_publisher import (
    PROSPECTIVE_RULE_HISTORY_SCHEMA_VERSION,
    ProspectiveRuleChampionPublisherError,
    ProspectiveRuleSnapshotRequest,
    publish_prospective_rule_history,
)
from data_module.rule_champion_snapshot_service import (
    PersistedFormalDecisionArtifactRepository,
)


_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
_STORE_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
_TEST_KEY = "pfs03-test-controlled-store-key"
_TEST_STORE_ID = "controlled-store:pfs03-test"
_NOW = datetime.fromisoformat("2026-08-18T09:00:00+08:00")


@pytest.fixture(autouse=True)
def _controlled_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_KEY_ENV, _TEST_KEY)
    monkeypatch.setenv(_STORE_ENV, _TEST_STORE_ID)


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return canonical_json(value).encode("utf-8")


def _artifact(
    *,
    snapshot_id: str,
    decision_timestamp: str,
    rank: int = 1,
    symbol: str = "2330",
    signature_key: str = _TEST_KEY,
) -> dict[str, object]:
    immutable: dict[str, object] = {
        "schema_version": "FormalRuleDecisionSnapshot.v1",
        "source_artifact_kind": "formal_rule_only_immutable_decision_snapshot",
        "rule_only_proof": "formal_rule_only",
        "decision_snapshot_id": snapshot_id,
        "decision_timestamp": decision_timestamp,
        "symbol": symbol,
        "rule_score_bp": 7_500 - rank,
        "rule_rank": rank,
        "source_lineage_artifact_id": f"lineage:{snapshot_id}",
        "source_lineage_hash": "sha256:" + "2" * 64,
        "restrictions_hash": "sha256:" + "3" * 64,
    }
    signed: dict[str, object] = {
        **immutable,
        "immutable_snapshot_hash": payload_hash(immutable),
        "registered_store_id": _TEST_STORE_ID,
    }
    signed["attestation_signature"] = "hmac-sha256:" + hmac.new(
        signature_key.encode("utf-8"),
        _canonical_bytes(signed),
        hashlib.sha256,
    ).hexdigest()
    return signed


class _Loader:
    def __init__(self, artifacts: Mapping[str, Mapping[str, object]]) -> None:
        self._artifacts = dict(artifacts)

    def load_registered_formal_decision_bytes(
        self,
        decision_snapshot_id: str,
    ) -> bytes | None:
        artifact = self._artifacts.get(decision_snapshot_id)
        if artifact is None:
            return None
        return _canonical_bytes(artifact)


def _repository(*artifacts: Mapping[str, object]) -> PersistedFormalDecisionArtifactRepository:
    return PersistedFormalDecisionArtifactRepository(
        _Loader(
            {
                str(artifact["decision_snapshot_id"]): artifact
                for artifact in artifacts
            }
        )
    )


def _clock(tmp_path: Path):
    seed = {"kind": "cash", "cash_bp": 10_000, "position_count": 0}
    seed["state_hash"] = payload_hash(seed)
    calendar = {
        "schema_version": "official-trading-calendar-evidence.v1",
        "date": "2026-08-17",
        "is_trading_day": True,
        "reason_code": "twse_holiday_schedule_open",
        "source": "TWSE holidaySchedule",
        "source_hash": "sha256:" + "1" * 64,
    }
    body: dict[str, object] = {
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
        "clock_id": "clock:prospective:pfs03:r1",
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-decision:pfs03-test",
        "owner_decision_timestamp": "2026-08-14T08:45:00+08:00",
        "activation_trading_day": "2026-08-17",
        "decision_timezone": "Asia/Taipei",
        "decision_time": "08:30:00",
        "activation_calendar_evidence": calendar,
        "seed_state": seed,
        "virtual_notional_minor_units": 1_000_000,
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        "policy_hash": "sha256:" + "4" * 64,
        "universe_hash": "sha256:" + "5" * 64,
        "source_policy_hash": "sha256:" + "6" * 64,
        "candidate_model_hash": "sha256:" + "7" * 64,
        "candidate_feature_manifest_hash": "sha256:" + "8" * 64,
        "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
        "calibration_policy_hash": "sha256:" + "9" * 64,
        "evaluation_policy_hash": "sha256:" + "a" * 64,
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    path = tmp_path / "clock.json"
    path.write_text(json.dumps(build_clock_manifest(body)), encoding="utf-8")
    return path, load_clock_manifest_for_capture(path, now=_NOW)


def _publish_kwargs(tmp_path: Path, clock, repository):
    return {
        "clock": clock,
        "output_path": tmp_path / "prospective_rule_history.json",
        "now": _NOW,
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        "score_configuration_hash": "sha256:" + "b" * 64,
        "universe_hash": "sha256:" + "5" * 64,
        "selection_capacity": 2,
        "repository": repository,
        "requests": (
            ProspectiveRuleSnapshotRequest(
                decision_date="2026-08-17",
                decision_snapshot_ids=("decision:20260817:2330", "decision:20260817:2317"),
            ),
        ),
    }


def test_capture_loader_allows_elapsed_activation_but_planning_loader_blocks(
    tmp_path: Path,
) -> None:
    path, clock = _clock(tmp_path)
    assert clock.activation_trading_day.isoformat() == "2026-08-17"
    with pytest.raises(ValueError, match="strictly after"):
        load_clock_manifest(path, now=_NOW)


def test_publishes_clock_bound_hmac_history_with_canonical_manifest(tmp_path: Path) -> None:
    _, clock = _clock(tmp_path)
    first = _artifact(
        snapshot_id="decision:20260817:2330",
        decision_timestamp="2026-08-17T08:30:00+08:00",
        rank=1,
        symbol="2330",
    )
    second = _artifact(
        snapshot_id="decision:20260817:2317",
        decision_timestamp="2026-08-17T08:30:00+08:00",
        rank=2,
        symbol="2317",
    )
    result = publish_prospective_rule_history(
        **_publish_kwargs(tmp_path, clock, _repository(first, second))
    )

    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == PROSPECTIVE_RULE_HISTORY_SCHEMA_VERSION
    assert payload["clock_id"] == clock.clock_id
    assert payload["clock_manifest_hash"] == clock.manifest_hash
    assert payload["status"] == "complete"
    assert payload["formal_source_only"] is True
    assert payload["research_only"] is False
    assert payload["formal_consumer_compatible"] is True
    assert payload["promotion_eligible"] is False
    assert payload["historical_backfill_claimed"] is False
    assert payload["decision_dates"] == ["2026-08-17"]
    assert payload["snapshot_count"] == 1
    assert payload["snapshots"][0]["schema_version"] == "RuleChampionSnapshot.v1"
    assert payload["snapshots"][0]["decision_rows"][1]["attestation_signature"].startswith(
        "hmac-sha256:"
    )
    body = dict(payload)
    manifest_hash = body.pop("manifest_hash")
    assert manifest_hash == payload_hash(body)
    assert result.manifest_file_hash == "sha256:" + hashlib.sha256(
        result.manifest_path.read_bytes()
    ).hexdigest()
    assert _TEST_KEY not in result.manifest_path.read_text(encoding="utf-8")


def test_owner_decision_may_be_captured_after_clock_boundary(tmp_path: Path) -> None:
    _, clock = _clock(tmp_path)
    snapshot_id = "decision:20260817:2330-after-boundary"
    artifact = _artifact(
        snapshot_id=snapshot_id,
        decision_timestamp="2026-08-17T08:45:00+08:00",
    )
    kwargs = _publish_kwargs(tmp_path, clock, _repository(artifact))
    kwargs["requests"] = (
        ProspectiveRuleSnapshotRequest(
            decision_date="2026-08-17",
            decision_snapshot_ids=(snapshot_id,),
        ),
    )
    result = publish_prospective_rule_history(**kwargs)
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["snapshots"][0]["decision_timestamp"] == (
        "2026-08-17T08:45:00+08:00"
    )


def test_clock_and_hmac_boundaries_fail_closed(tmp_path: Path) -> None:
    _, clock = _clock(tmp_path)
    valid = _artifact(
        snapshot_id="decision:20260817:2330",
        decision_timestamp="2026-08-17T08:30:00+08:00",
    )
    kwargs = _publish_kwargs(tmp_path, clock, _repository(valid))
    kwargs["requests"] = (
        ProspectiveRuleSnapshotRequest(
            decision_date="2026-08-16",
            decision_snapshot_ids=("decision:20260817:2330",),
        ),
    )
    with pytest.raises(ProspectiveRuleChampionPublisherError, match="precedes"):
        publish_prospective_rule_history(**kwargs)

    future_artifact = _artifact(
        snapshot_id="decision:20260818:2330",
        decision_timestamp="2026-08-18T08:30:00+08:00",
    )
    kwargs = _publish_kwargs(tmp_path, clock, _repository(future_artifact))
    kwargs["requests"] = (
        ProspectiveRuleSnapshotRequest(
            decision_date="2026-08-18",
            decision_snapshot_ids=("decision:20260818:2330",),
        ),
    )
    kwargs["now"] = datetime.fromisoformat("2026-08-18T08:00:00+08:00")
    with pytest.raises(ProspectiveRuleChampionPublisherError, match="after capture now"):
        publish_prospective_rule_history(**kwargs)


def test_bad_signature_and_noncontiguous_rank_are_rejected(tmp_path: Path) -> None:
    _, clock = _clock(tmp_path)
    bad_signature = _artifact(
        snapshot_id="decision:20260817:2330",
        decision_timestamp="2026-08-17T08:30:00+08:00",
        signature_key="wrong-key",
    )
    with pytest.raises(ValueError, match="attestation"):
        publish_prospective_rule_history(
            **_publish_kwargs(tmp_path, clock, _repository(bad_signature))
        )

    rank_two = _artifact(
        snapshot_id="decision:20260817:2317",
        decision_timestamp="2026-08-17T08:30:00+08:00",
        rank=2,
    )
    rank_kwargs = _publish_kwargs(tmp_path, clock, _repository(rank_two))
    rank_kwargs["requests"] = (
        ProspectiveRuleSnapshotRequest(
            decision_date="2026-08-17",
            decision_snapshot_ids=("decision:20260817:2317",),
        ),
    )
    with pytest.raises(ValueError, match="contiguous"):
        publish_prospective_rule_history(**rank_kwargs)


def test_output_is_immutable_and_parent_must_exist(tmp_path: Path) -> None:
    _, clock = _clock(tmp_path)
    artifact = _artifact(
        snapshot_id="decision:20260817:2330",
        decision_timestamp="2026-08-17T08:30:00+08:00",
    )
    kwargs = _publish_kwargs(tmp_path, clock, _repository(artifact))
    kwargs["requests"] = (
        ProspectiveRuleSnapshotRequest(
            decision_date="2026-08-17",
            decision_snapshot_ids=("decision:20260817:2330",),
        ),
    )
    publish_prospective_rule_history(**kwargs)
    with pytest.raises(ProspectiveRuleChampionPublisherError, match="already exists"):
        publish_prospective_rule_history(**kwargs)

    kwargs["output_path"] = tmp_path / "missing" / "history.json"
    with pytest.raises(ProspectiveRuleChampionPublisherError, match="parent"):
        publish_prospective_rule_history(**kwargs)


def test_fixture_cli_publishes_without_emitting_secret(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.publish_prospective_rule_champion_history import main

    clock_path, _ = _clock(tmp_path)
    snapshot_id = "decision:20260817:2330"
    artifact = _artifact(
        snapshot_id=snapshot_id,
        decision_timestamp="2026-08-17T08:30:00+08:00",
    )
    artifacts_path = tmp_path / "artifacts.json"
    artifacts_path.write_text(json.dumps({snapshot_id: artifact}), encoding="utf-8")
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [{"decision_date": "2026-08-17", "decision_snapshot_ids": [snapshot_id]}]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "history.json"
    exit_code = main(
        [
            "--fixture-only",
            "--clock-manifest",
            str(clock_path),
            "--now",
            _NOW.isoformat(),
            "--output",
            str(output_path),
            "--requests-json",
            str(requests_path),
            "--artifacts-json",
            str(artifacts_path),
            "--strategy-version",
            "rule-v1",
            "--policy-version",
            "policy-v1",
            "--score-configuration-hash",
            "sha256:" + "b" * 64,
            "--universe-hash",
            "sha256:" + "5" * 64,
            "--selection-capacity",
            "1",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert output_path.is_file()
    assert '"status": "published"' in captured.out
    assert _TEST_KEY not in captured.out
    assert captured.err == ""
