from __future__ import annotations

import json
from hashlib import sha256

from scripts.inspect_formal_clock_readiness import inspect_readiness


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


def _snapshot(path, decision_date: str = "2026-07-15") -> None:
    path.write_text(
        json.dumps(
            {
                "decision_timestamp": f"{decision_date}T09:00:00+08:00",
                "data_as_of_date": decision_date,
                "max_available_timestamp": f"{decision_date}T08:59:59+08:00",
                "source_versions": {"daily_prices": "sha256:" + "1" * 64},
                "strategy_version": "rule-v1", "policy_version": "policy-v1",
                "rule_champion_snapshot_id": "champion:rule-v1", "universe_id": "tw-equity",
                "universe_hash": "sha256:" + "2" * 64, "symbol": "2330", "score_bp": 7000,
                "score_status": "observed", "rank": 1, "action_or_prompt": "RESEARCH",
                "why": ["rule_rank_top_k"], "why_not": [], "risk_reasons": ["market_risk"],
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
    assert "holdout_binding_requires_owner_authority" in report["blockers"]


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
