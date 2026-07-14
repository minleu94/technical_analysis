from __future__ import annotations

import pytest

from app_module.external_evidence_contracts import ExternalEvidenceDecisionSnapshot
from app_module.external_evidence_contracts import EvidenceOutcomeRevision


def _snapshot(**overrides: object) -> ExternalEvidenceDecisionSnapshot:
    payload: dict[str, object] = {
        "decision_timestamp": "2026-07-13T09:00:00+08:00",
        "data_as_of_date": "2026-07-12",
        "max_available_timestamp": "2026-07-13T08:59:59+08:00",
        "source_versions": {"daily_prices": "sha256:" + "1" * 64},
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        "rule_champion_snapshot_id": "champion:rule-v1",
        "universe_id": "tw-equity-20260713",
        "universe_hash": "sha256:" + "2" * 64,
        "symbol": "2330",
        "score_bp": 7000,
        "score_status": "observed",
        "rank": 1,
        "action_or_prompt": "RESEARCH",
        "why": ("rule_rank_top_k",),
        "why_not": (),
        "risk_reasons": ("market_risk",),
        "market_regime": "neutral",
        "liquidity_state": "liquid",
        "restriction_state": "clear",
        "evidence_tier": "shadow",
        "missing_sources": (),
        "degraded_reasons": (),
        "parent_artifact_ids": ("recommendation:20260713",),
        "capture_kind": "manual_observed",
    }
    payload.update(overrides)
    return ExternalEvidenceDecisionSnapshot.create(**payload)


def test_future_available_snapshot_is_rejected() -> None:
    with pytest.raises(ValueError, match="available"):
        _snapshot(max_available_timestamp="2026-07-13T09:00:01+08:00")


def test_not_applicable_score_is_preserved_without_zero_substitution() -> None:
    snapshot = _snapshot(score_bp=None, score_status="not_applicable", rank=None)

    assert snapshot.score_bp is None
    assert snapshot.score_status == "not_applicable"
    assert snapshot.rank is None
    assert snapshot.snapshot_id.startswith("snapshot:2330:20260713:")


def test_snapshot_and_revision_mappings_are_actually_immutable() -> None:
    source_versions = {"daily_prices": "sha256:" + "1" * 64}
    snapshot = _snapshot(source_versions=source_versions, capture_kind="manual_observed")
    source_versions["daily_prices"] = "tampered"
    revision = EvidenceOutcomeRevision(
        revision_id="revision:immutable-mappings",
        parent_revision_id=None,
        snapshot_id=snapshot.snapshot_id,
        window_trading_days=20,
        return_basis="stock_minus_benchmark",
        status="verified",
        observed_at="2026-08-10T16:00:00+08:00",
        data_as_of_date="2026-08-10",
        return_bp=120,
        benchmark_return_bp=50,
        reason_code="initial",
        source_hashes={"daily_prices": "sha256:" + "3" * 64},
        content_hash="sha256:" + "4" * 64,
    )

    assert snapshot.source_versions["daily_prices"] == "sha256:" + "1" * 64
    with pytest.raises(TypeError):
        snapshot.source_versions["daily_prices"] = "tampered"  # type: ignore[index]
    with pytest.raises(TypeError):
        revision.source_hashes["daily_prices"] = "tampered"  # type: ignore[index]
