from __future__ import annotations

import pytest

from app_module.evidence_outcome_revision_repository import EvidenceOutcomeRevisionRepository
from app_module.external_evidence_contracts import EvidenceOutcomeRevision, ExternalEvidenceDecisionSnapshot


def _snapshot() -> ExternalEvidenceDecisionSnapshot:
    return ExternalEvidenceDecisionSnapshot.create(
        decision_timestamp="2026-07-13T09:00:00+08:00",
        data_as_of_date="2026-07-12",
        max_available_timestamp="2026-07-13T08:59:59+08:00",
        source_versions={"daily_prices": "sha256:" + "1" * 64},
        strategy_version="rule-v1", policy_version="policy-v1",
        rule_champion_snapshot_id="champion:rule-v1", universe_id="tw-equity-20260713",
        universe_hash="sha256:" + "2" * 64, symbol="2330", score_bp=7000,
        score_status="observed", rank=1, action_or_prompt="RESEARCH", why=("top_k",),
        why_not=(), risk_reasons=(), market_regime="neutral", liquidity_state="liquid",
        restriction_state="clear", evidence_tier="shadow", missing_sources=(),
        degraded_reasons=(), parent_artifact_ids=("recommendation:20260713",),
        capture_kind="manual_observed",
    )


def _revision(
    revision_id: str,
    parent: str | None,
    return_bp: int | None,
    *,
    status: str = "verified",
    snapshot_id: str = "snapshot:2330:20260713:test",
) -> EvidenceOutcomeRevision:
    return EvidenceOutcomeRevision(
        revision_id=revision_id,
        parent_revision_id=parent,
        snapshot_id=snapshot_id,
        window_trading_days=20,
        return_basis="stock_minus_benchmark",
        status=status,
        observed_at="2026-08-10T16:00:00+08:00",
        data_as_of_date="2026-08-10",
        return_bp=return_bp,
        benchmark_return_bp=50 if return_bp is not None else None,
        reason_code="initial" if parent is None else "source_correction",
        source_hashes={"daily_prices": "sha256:" + "3" * 64},
        content_hash="sha256:" + ("4" if parent is None else "5") * 64,
    )


def test_correction_appends_child_revision(tmp_path) -> None:
    repo = EvidenceOutcomeRevisionRepository(tmp_path / "evidence.sqlite")
    snapshot = repo.append_snapshot(_snapshot())
    first = repo.append(_revision("rev-1", parent=None, return_bp=120, snapshot_id=snapshot.snapshot_id))
    second = repo.append(
        _revision("rev-2", parent=first.revision_id, return_bp=110, snapshot_id=snapshot.snapshot_id)
    )

    assert repo.list_revisions(first.snapshot_id) == (first, second)
    assert repo.current(first.snapshot_id).revision_id == "rev-2"


def test_snapshot_is_insert_only_and_idempotent_for_identical_artifact(tmp_path) -> None:
    repo = EvidenceOutcomeRevisionRepository(tmp_path / "evidence.sqlite")
    snapshot = _snapshot()

    assert repo.append_snapshot(snapshot) == snapshot
    assert repo.append_snapshot(snapshot) == snapshot
    assert repo.get_snapshot(snapshot.snapshot_id) == snapshot


def test_duplicate_revision_id_with_different_payload_is_rejected(tmp_path) -> None:
    repo = EvidenceOutcomeRevisionRepository(tmp_path / "evidence.sqlite")
    snapshot = repo.append_snapshot(_snapshot())
    repo.append(_revision("rev-1", parent=None, return_bp=120, snapshot_id=snapshot.snapshot_id))

    with pytest.raises(ValueError, match="different payload"):
        repo.append(_revision("rev-1", parent=None, return_bp=121, snapshot_id=snapshot.snapshot_id))


def test_revision_requires_persisted_manual_observed_snapshot(tmp_path) -> None:
    repo = EvidenceOutcomeRevisionRepository(tmp_path / "evidence.sqlite")

    with pytest.raises(ValueError, match="persisted manual_observed"):
        repo.append(_revision("rev-orphan", parent=None, return_bp=120))
