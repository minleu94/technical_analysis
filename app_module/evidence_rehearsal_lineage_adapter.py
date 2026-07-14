"""將 Evidence rehearsal artifact 投影到既有 lineage identity。"""

from __future__ import annotations

from typing import Any

from app_module.artifact_lineage_verifier import ArtifactIdentity
from app_module.evidence_rehearsal_dtos import RehearsalArtifact


class RehearsalArtifactIdentityAdapter:
    """只轉換 identity metadata，不重新計算 domain artifact。"""

    def project(
        self,
        artifact: RehearsalArtifact,
        *,
        artifact_type: str,
        run_id: str,
        source_id: str,
    ) -> ArtifactIdentity:
        if artifact.content_hash is None:
            raise ValueError("rehearsal artifact content_hash is required")
        if artifact.rollback_reference is None:
            raise ValueError("rehearsal artifact rollback_reference is required")
        payload = artifact.canonical_payload or {}
        return ArtifactIdentity(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact_type,
            run_id=run_id,
            decision_date=artifact.decision_date,
            as_of_date=artifact.as_of_date or artifact.decision_date,
            available_date=artifact.available_date,
            source_id=source_id,
            source_version=artifact.source_version or "missing",
            data_quality=artifact.data_quality or "missing",
            missing_state=artifact.missing_state or "none",
            strategy_version=_payload_string(payload, "strategy_version", "not_applicable"),
            policy_version=_payload_string(payload, "policy_version", "not_applicable"),
            model_version=_optional_payload_string(payload, "model_version"),
            parent_artifact_ids=artifact.parent_artifact_ids,
            evidence_tier=artifact.tier,
            current_status=artifact.current_status or "projected",
            content_hash=artifact.content_hash,
            rollback_reference=artifact.rollback_reference,
        )


def _payload_string(payload: Any, key: str, default: str) -> str:
    value = payload.get(key) if hasattr(payload, "get") else None
    return str(value) if value is not None and str(value) else default


def _optional_payload_string(payload: Any, key: str) -> str | None:
    value = payload.get(key) if hasattr(payload, "get") else None
    return str(value) if value is not None and str(value) else None
