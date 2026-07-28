from __future__ import annotations

import json
from hashlib import sha256

from scripts.inspect_formal_clock_readiness import inspect_readiness
from development_module.formal_observation_lane import (
    CANDIDATE_SOURCE_IDS,
    FormalObservationLaneDecision,
    RULE_ONLY_SOURCE_IDS,
)


def _decision(root, holdout: str = "2026-07-14") -> None:
    governance = root / "governance"
    governance.mkdir(parents=True)
    payload = {
        "decision": "seen_oos",
        "owner_provided_authorization": "owner-record-1",
        "year_2025_usage": "development_only",
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "effective_timestamp_utc": "2026-07-13T00:00:00+00:00",
        "development_output_root": str(root),
        "new_holdout_start": holdout,
    }
    (governance / "DevelopmentDataUsageDecision.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _snapshot(
    path,
    decision_date: str = "2026-07-15",
    *,
    source_versions: dict[str, str] | None = None,
    why: list[str] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "decision_timestamp": f"{decision_date}T09:00:00+08:00",
                "data_as_of_date": decision_date,
                "max_available_timestamp": f"{decision_date}T08:59:59+08:00",
                "source_versions": source_versions
                or {"daily_prices": "sha256:" + "1" * 64},
                "strategy_version": "rule-v1", "policy_version": "policy-v1",
                "rule_champion_snapshot_id": "champion:rule-v1", "universe_id": "tw-equity",
                "universe_hash": "sha256:" + "2" * 64, "symbol": "2330", "score_bp": 7000,
                "score_status": "observed", "rank": 1, "action_or_prompt": "RESEARCH",
                "why": why or ["rule_rank_top_k"], "why_not": [], "risk_reasons": ["market_risk"],
                "market_regime": "neutral", "liquidity_state": "liquid", "restriction_state": "clear",
                "evidence_tier": "shadow", "missing_sources": [], "degraded_reasons": [],
                "parent_artifact_ids": ["research:20260714"], "capture_kind": "manual_observed",
            }
        ),
        encoding="utf-8",
    )


def test_missing_registry_fails_closed(tmp_path) -> None:
    _decision(tmp_path)

    report = inspect_readiness(tmp_path)

    assert report["owner_decision"] == "valid"
    assert report["consumption_registry"] == "missing"
    assert report["can_capture_shadow_snapshot"] is False
    assert "consumption_registry_missing" in report["blockers"]


def test_owner_attested_binding_and_valid_snapshot_only_allow_shadow_capture(tmp_path) -> None:
    _decision(tmp_path, holdout="2026-07-15")
    decision_sha256 = "sha256:" + sha256(
        (tmp_path / "governance" / "DevelopmentDataUsageDecision.jsonl").read_bytes()
    ).hexdigest()
    (tmp_path / "governance" / "HoldoutConsumptionRegistry.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "holdout-consumption-registry.v2",
                "record_type": "formal_holdout_binding",
                "development_holdout_start": "2026-07-15",
                "formal_trading_session": "2026-07-15",
                "owner_id": "owner-1",
                "binding_authorization": "owner-approved-decision-1",
                "bound_at": "2026-07-14T14:00:00+08:00",
                "owner_decision_sha256": decision_sha256,
                "unconsumed_before_binding": True,
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
            }
        ) + "\n",
        encoding="utf-8",
    )
    snapshot = tmp_path / "manual_observed.json"
    _snapshot(snapshot)

    report = inspect_readiness(tmp_path, snapshot)

    assert report["consumption_registry"] == "owner_attested_binding_valid"
    assert report["snapshot"] == "structurally_valid"
    assert report["can_capture_shadow_snapshot"] is True
    assert report["formal_readiness"] is False
    assert "holdout_binding_requires_owner_authority" not in report["blockers"]


def test_legacy_registry_record_never_allows_capture(tmp_path) -> None:
    _decision(tmp_path)
    (tmp_path / "governance" / "HoldoutConsumptionRegistry.jsonl").write_text(
        json.dumps({"trading_session": "2026-07-14"}) + "\n", encoding="utf-8"
    )

    report = inspect_readiness(tmp_path)

    assert report["owner_decision"] == "valid"
    assert report["can_capture_shadow_snapshot"] is False
    assert "holdout_binding_missing" in report["blockers"]


def test_snapshot_from_a_different_session_never_allows_capture(tmp_path) -> None:
    _decision(tmp_path, holdout="2026-07-15")
    decision_sha256 = "sha256:" + sha256(
        (tmp_path / "governance" / "DevelopmentDataUsageDecision.jsonl").read_bytes()
    ).hexdigest()
    (tmp_path / "governance" / "HoldoutConsumptionRegistry.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "holdout-consumption-registry.v2",
                "record_type": "formal_holdout_binding",
                "development_holdout_start": "2026-07-15",
                "formal_trading_session": "2026-07-16",
                "owner_id": "owner-1", "binding_authorization": "owner-approved-decision-1",
                "bound_at": "2026-07-14T14:00:00+08:00", "owner_decision_sha256": decision_sha256,
                "unconsumed_before_binding": True, "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
            }
        ) + "\n",
        encoding="utf-8",
    )
    snapshot = tmp_path / "manual_observed.json"
    _snapshot(snapshot, decision_date="2026-07-15")

    report = inspect_readiness(tmp_path, snapshot)

    assert report["formal_trading_session"] == "2026-07-16"
    assert report["can_capture_shadow_snapshot"] is False
    assert "manual_observed_session_mismatch" in report["blockers"]


def test_free_text_fubon_mention_does_not_create_source_dependency(tmp_path) -> None:
    snapshot = tmp_path / "manual_observed.json"
    _snapshot(snapshot, why=["Fubon not used; Rule-only input"])

    report = inspect_readiness(tmp_path, snapshot)

    assert "fubon_source_not_accepted_for_formal_clock" not in report["blockers"]


def test_typed_fubon_source_version_blocks_formal_clock(tmp_path) -> None:
    snapshot = tmp_path / "manual_observed.json"
    _snapshot(
        snapshot,
        source_versions={"fubon.marketdata": "sha256:" + "3" * 64},
    )

    report = inspect_readiness(tmp_path, snapshot)

    assert "fubon_source_not_accepted_for_formal_clock" in report["blockers"]


def test_owner_approved_lane_selects_its_unique_forward_binding(tmp_path) -> None:
    _decision(tmp_path, holdout="2026-07-15")
    development_sha = "sha256:" + sha256(
        (tmp_path / "governance" / "DevelopmentDataUsageDecision.jsonl").read_bytes()
    ).hexdigest()
    lane = FormalObservationLaneDecision(
        decision_id="decision:rule-only:20260728-r1",
        holdout_id="formal-rule-only-20260729-r1",
        decided_at="2026-07-28T12:40:11+08:00",
        owner_id="archi",
        first_eligible_session="2026-07-29",
        allowed_source_ids=RULE_ONLY_SOURCE_IDS,
        excluded_source_ids=CANDIDATE_SOURCE_IDS,
        rollback_reference="append disable revision",
    )
    lane_path = tmp_path / "lane.json"
    lane_path.write_text(
        json.dumps({**lane.to_dict(), "content_hash": lane.content_hash}),
        encoding="utf-8",
    )
    registry = tmp_path / "governance" / "HoldoutConsumptionRegistry.jsonl"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "holdout-consumption-registry.v2",
                "record_type": "formal_holdout_binding",
                "development_holdout_start": "2026-07-15",
                "formal_trading_session": "2026-07-21",
                "owner_id": "archi",
                "binding_authorization": "legacy",
                "bound_at": "2026-07-21T06:49:50+08:00",
                "owner_decision_sha256": development_sha,
                "unconsumed_before_binding": True,
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
            }
        )
        + "\n"
        + json.dumps(
            {
                "schema_version": "holdout-consumption-registry.v3",
                "record_type": "formal_observation_lane_binding",
                "holdout_id": lane.holdout_id,
                "development_holdout_start": "2026-07-15",
                "formal_trading_session": "2026-07-29",
                "owner_id": "archi",
                "binding_authorization": lane.decision_id,
                "bound_at": "2026-07-28T12:45:00+08:00",
                "lane_decision_sha256": lane.content_hash,
                "development_decision_sha256": development_sha,
                "unconsumed_before_binding": True,
                "rule_only_formal_path": True,
                "no_retroactive_credit": True,
                "formal_oos_allowed": False,
                "formal_evidence_credit_authorized": False,
                "production_blend_alpha_bp": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = inspect_readiness(tmp_path, lane_decision_json=lane_path)

    assert report["observation_lane_decision"] == "valid"
    assert report["consumption_registry"] == "owner_attested_lane_binding_valid"
    assert report["formal_trading_session"] == "2026-07-29"
    assert report["fubon_shadow_usable"] is True
    assert report["fubon_formal_credit_allowed"] is False
    assert "manual_observed_snapshot_missing" in report["blockers"]


def test_disabled_lane_fails_closed_without_deleting_binding(tmp_path) -> None:
    _decision(tmp_path, holdout="2026-07-15")
    development_sha = "sha256:" + sha256(
        (tmp_path / "governance" / "DevelopmentDataUsageDecision.jsonl").read_bytes()
    ).hexdigest()
    lane = FormalObservationLaneDecision(
        decision_id="decision:rule-only:20260728-r1",
        holdout_id="formal-rule-only-20260729-r1",
        decided_at="2026-07-28T12:40:11+08:00",
        owner_id="archi",
        first_eligible_session="2026-07-29",
        allowed_source_ids=RULE_ONLY_SOURCE_IDS,
        excluded_source_ids=CANDIDATE_SOURCE_IDS,
        rollback_reference="append disable revision",
    )
    lane_path = tmp_path / "lane.json"
    lane_path.write_text(
        json.dumps({**lane.to_dict(), "content_hash": lane.content_hash}),
        encoding="utf-8",
    )
    binding = {
        "schema_version": "holdout-consumption-registry.v3",
        "record_type": "formal_observation_lane_binding",
        "holdout_id": lane.holdout_id,
        "development_holdout_start": "2026-07-15",
        "formal_trading_session": "2026-07-29",
        "owner_id": "archi",
        "binding_authorization": lane.decision_id,
        "bound_at": "2026-07-28T12:45:00+08:00",
        "lane_decision_sha256": lane.content_hash,
        "development_decision_sha256": development_sha,
        "unconsumed_before_binding": True,
        "rule_only_formal_path": True,
        "no_retroactive_credit": True,
        "formal_oos_allowed": False,
        "formal_evidence_credit_authorized": False,
        "production_blend_alpha_bp": 0,
    }
    disabled = {
        "schema_version": "formal-observation-lane-disabled.v1",
        "record_type": "formal_observation_lane_disabled",
        "holdout_id": lane.holdout_id,
        "disabled_at": "2026-07-28T13:00:00+08:00",
        "reason": "owner rollback",
    }
    (tmp_path / "governance" / "HoldoutConsumptionRegistry.jsonl").write_text(
        json.dumps(binding) + "\n" + json.dumps(disabled) + "\n",
        encoding="utf-8",
    )

    report = inspect_readiness(tmp_path, lane_decision_json=lane_path)

    assert report["consumption_registry"] == "disabled"
    assert "observation_lane_disabled_or_revoked" in report["blockers"]
    assert "holdout_binding_requires_owner_authority" in report["blockers"]
