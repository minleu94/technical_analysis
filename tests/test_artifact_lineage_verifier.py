from app_module.artifact_lineage_verifier import (
    ArtifactIdentity,
    ArtifactLineageVerifier,
)


def _artifact(artifact_id: str, artifact_type: str, *, parents: tuple[str, ...] = ()) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        run_id="run-20260712",
        decision_date="2026-07-12",
        as_of_date="2026-07-11",
        available_date="2026-07-12",
        source_id="fixture.governed",
        source_version="v1",
        data_quality="observed",
        missing_state="complete",
        strategy_version="rule-v1",
        policy_version="policy-v1",
        model_version=None,
        parent_artifact_ids=parents,
        evidence_tier="engineering_fixture",
        current_status="current_engineering",
        content_hash="a" * 64,
        rollback_reference="commit:rollback-sha",
    )


def test_complete_cross_gate_chain_is_valid() -> None:
    artifacts = (
        _artifact("daily", "daily_governed_data"),
        _artifact("market", "market_context", parents=("daily",)),
        _artifact("recommendation", "recommendation", parents=("market",)),
        _artifact("advice", "bounded_advice", parents=("recommendation",)),
        _artifact("paper", "paper_portfolio", parents=("advice",)),
        _artifact("health", "position_health", parents=("paper",)),
        _artifact("evidence", "evidence_event", parents=("health",)),
        _artifact("outcome", "forward_outcome", parents=("evidence",)),
        _artifact("weekly", "weekly_review", parents=("outcome",)),
        _artifact("signal", "signal_effectiveness", parents=("weekly",)),
        _artifact("ml", "ml_shadow_prediction", parents=("signal",)),
    )

    report = ArtifactLineageVerifier().verify(artifacts)

    assert report.status == "complete"
    assert report.blockers == ()
    assert report.ordered_artifact_ids[-1] == "ml"
    assert report.formal_product_closeout is False
    assert report.production_actions_allowed is False


def test_verifier_fails_closed_for_future_data_missing_parent_and_rollback() -> None:
    bad = _artifact("advice", "bounded_advice", parents=("missing",))
    bad = ArtifactIdentity(**{**bad.to_dict(), "available_date": "2026-07-13", "rollback_reference": ""})

    report = ArtifactLineageVerifier().verify((bad,))

    assert report.status == "incomplete"
    assert "future_available_date:advice" in report.blockers
    assert "missing_parent:advice:missing" in report.blockers
    assert "missing_rollback_reference:advice" in report.blockers


def test_verifier_detects_cycles_and_duplicate_ids() -> None:
    first = _artifact("a", "daily_governed_data", parents=("b",))
    second = _artifact("b", "market_context", parents=("a",))

    cycle = ArtifactLineageVerifier().verify((first, second))
    duplicate = ArtifactLineageVerifier().verify((first, first))

    assert "lineage_cycle" in cycle.blockers
    assert "duplicate_artifact_id:a" in duplicate.blockers
