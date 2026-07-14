from __future__ import annotations

from app_module.evidence_cadence_review_service import EvidenceCadenceReviewService
from app_module.external_evidence_contracts import EvidenceOutcomeRevision, ExternalEvidenceDecisionSnapshot


def _snapshot(symbol: str) -> ExternalEvidenceDecisionSnapshot:
    return ExternalEvidenceDecisionSnapshot.create(
        decision_timestamp="2026-07-13T09:00:00+08:00",
        data_as_of_date="2026-07-12",
        max_available_timestamp="2026-07-13T08:59:59+08:00",
        source_versions={"daily_prices": "sha256:" + "1" * 64},
        strategy_version="rule-v1", policy_version="policy-v1",
        rule_champion_snapshot_id="champion:rule-v1", universe_id="tw-equity-20260713",
        universe_hash="sha256:" + "2" * 64, symbol=symbol, score_bp=7000,
        score_status="observed", rank=1, action_or_prompt="RESEARCH", why=("top_k",),
        why_not=(), risk_reasons=(), market_regime="neutral", liquidity_state="liquid",
        restriction_state="clear", evidence_tier="shadow", missing_sources=(),
        degraded_reasons=(), parent_artifact_ids=("recommendation:20260713",),
        capture_kind="manual_observed",
    )


def _revision(
    revision_id: str, snapshot_id: str, *, parent_revision_id: str | None = None, status: str = "verified"
) -> EvidenceOutcomeRevision:
    return EvidenceOutcomeRevision(
        revision_id=revision_id,
        parent_revision_id=parent_revision_id,
        snapshot_id=snapshot_id,
        window_trading_days=20,
        return_basis="stock_minus_benchmark",
        status=status,
        observed_at="2026-08-10T16:00:00+08:00",
        data_as_of_date="2026-08-10",
        return_bp=120 if status == "verified" else None,
        benchmark_return_bp=50 if status == "verified" else None,
        reason_code="source_correction" if parent_revision_id else "initial",
        source_hashes={"daily_prices": "sha256:" + "3" * 64},
        content_hash="sha256:" + revision_id[-1] * 64,
    )


def test_pending_outcomes_are_not_in_effectiveness_denominator() -> None:
    snapshot = _snapshot("2330")
    pending = EvidenceOutcomeRevision(
        revision_id="revision:pending-20d",
        parent_revision_id=None,
        snapshot_id=snapshot.snapshot_id,
        window_trading_days=20,
        return_basis="stock_minus_benchmark",
        status="pending_maturity",
        observed_at="2026-07-13T16:00:00+08:00",
        data_as_of_date="2026-07-13",
        return_bp=None,
        benchmark_return_bp=None,
        reason_code="horizon_not_mature",
        source_hashes={"daily_prices": "sha256:" + "1" * 64},
        content_hash="sha256:" + "2" * 64,
    )

    package = EvidenceCadenceReviewService().build_monthly(
        snapshots=(snapshot,), outcome_revisions=(pending,)
    )

    assert package.primary_matured_count == 0
    assert package.primary_effectiveness_denominator == 0
    assert "primary_horizon_pending" in package.blockers


def test_daily_requires_named_reason_when_expected_day_has_no_snapshot() -> None:
    package = EvidenceCadenceReviewService().build_daily(
        expected_operation_days=("2026-07-13",), snapshots=(), missing_reasons={}
    )

    assert package.status == "indeterminate"
    assert "missing_decision_or_reason:2026-07-13" in package.blockers


def test_weekly_requires_three_real_periods_without_synthesizing_them() -> None:
    package = EvidenceCadenceReviewService().build_weekly(period_end_dates=("2026-07-10",))

    assert package.status == "indeterminate"
    assert "three_real_weekly_periods_required" in package.blockers


def test_monthly_counts_only_current_verified_leaf_for_registered_manual_snapshot() -> None:
    registered = _snapshot("2330")
    unregistered = _snapshot("2317")
    parent = _revision("revision-parent", registered.snapshot_id)
    leaf = _revision("revision-leaf", registered.snapshot_id, parent_revision_id=parent.revision_id)
    orphan = _revision("revision-orphan", unregistered.snapshot_id)

    package = EvidenceCadenceReviewService().build_monthly(
        snapshots=(registered,), outcome_revisions=(parent, leaf, orphan)
    )

    assert package.primary_matured_count == 1
    assert package.primary_effectiveness_denominator == 1
