from __future__ import annotations

import json

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


def _snapshot(path) -> None:
    path.write_text(
        json.dumps(
            {
                "decision_timestamp": "2026-07-14T09:00:00+08:00",
                "data_as_of_date": "2026-07-14",
                "max_available_timestamp": "2026-07-14T08:59:59+08:00",
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


def test_unconsumed_registry_and_valid_snapshot_only_allow_shadow_capture(tmp_path) -> None:
    _decision(tmp_path)
    (tmp_path / "governance" / "HoldoutConsumptionRegistry.jsonl").write_text(
        json.dumps({"trading_session": "2026-07-15"}) + "\n", encoding="utf-8"
    )
    snapshot = tmp_path / "manual_observed.json"
    _snapshot(snapshot)

    report = inspect_readiness(tmp_path, snapshot)

    assert report["consumption_registry"] == "present_unconsumed"
    assert report["snapshot"] == "structurally_valid"
    assert report["can_capture_shadow_snapshot"] is True
    assert report["formal_readiness"] is False
    assert "holdout_binding_requires_owner_authority" in report["blockers"]


def test_consumed_holdout_never_allows_capture(tmp_path) -> None:
    _decision(tmp_path)
    (tmp_path / "governance" / "HoldoutConsumptionRegistry.jsonl").write_text(
        json.dumps({"trading_session": "2026-07-14"}) + "\n", encoding="utf-8"
    )

    report = inspect_readiness(tmp_path)

    assert report["owner_decision"] == "missing"
    assert report["can_capture_shadow_snapshot"] is False
    assert "owner_decision_missing_or_invalid" in report["blockers"]
