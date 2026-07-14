from __future__ import annotations

from app_module.evidence_rehearsal_dtos import RehearsalArtifact
from app_module.evidence_rehearsal_lineage_adapter import (
    RehearsalArtifactIdentityAdapter,
)


def test_lineage_adapter_preserves_hash_parents_tier_and_rollback() -> None:
    artifact = RehearsalArtifact(
        artifact_id="replay-1",
        decision_date="2026-07-09",
        available_date="2026-07-09",
        tier="historical_replay_candidate",
        as_of_date="2026-07-09",
        parent_artifact_ids=("source-1", "recommendation-1"),
        source_version="source-v1",
        data_quality="observed",
        missing_state="none",
        content_hash="a" * 64,
        current_status="projected",
        rollback_reference="working-copy:replay-1",
    )

    identity = RehearsalArtifactIdentityAdapter().project(
        artifact,
        artifact_type="recommendation",
        run_id="run-1",
        source_id="historical-replay",
    )

    assert identity.artifact_id == artifact.artifact_id
    assert identity.content_hash == artifact.content_hash
    assert identity.parent_artifact_ids == artifact.parent_artifact_ids
    assert identity.evidence_tier == artifact.tier
    assert identity.rollback_reference == artifact.rollback_reference
    assert identity.artifact_type == "recommendation"
