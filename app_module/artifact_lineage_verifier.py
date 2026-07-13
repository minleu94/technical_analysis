"""Canonical read-only identity and lineage validation across existing artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable


_CROSS_DOMAIN_ARTIFACT_TYPES = (
    "daily_governed_data",
    "market_context",
    "recommendation",
    "bounded_advice",
    "paper_portfolio",
    "position_health",
    "evidence_event",
    "forward_outcome",
    "weekly_review",
    "signal_effectiveness",
    "ml_shadow_prediction",
)
_REQUIRED_PARENT_ARTIFACT_TYPES = {
    artifact_type: _CROSS_DOMAIN_ARTIFACT_TYPES[index - 1]
    for index, artifact_type in enumerate(_CROSS_DOMAIN_ARTIFACT_TYPES)
    if index > 0
}


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_id: str
    artifact_type: str
    run_id: str
    decision_date: str
    as_of_date: str
    available_date: str
    source_id: str
    source_version: str
    data_quality: str
    missing_state: str
    strategy_version: str
    policy_version: str
    model_version: str | None
    parent_artifact_ids: tuple[str, ...]
    evidence_tier: str
    current_status: str
    content_hash: str
    rollback_reference: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactLineageReport:
    status: str
    artifact_count: int
    ordered_artifact_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    formal_product_closeout: bool = False
    production_actions_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactLineageVerifier:
    """Validate a canonical projection without creating a parallel registry."""

    def verify(self, artifacts: Iterable[ArtifactIdentity]) -> ArtifactLineageReport:
        items = tuple(artifacts)
        blockers: list[str] = []
        by_id: dict[str, ArtifactIdentity] = {}
        for item in items:
            if item.artifact_id in by_id:
                blockers.append(f"duplicate_artifact_id:{item.artifact_id}")
            else:
                by_id[item.artifact_id] = item
            self._validate_fields(item, blockers)

        for item in items:
            for parent_id in item.parent_artifact_ids:
                if parent_id not in by_id:
                    blockers.append(f"missing_parent:{item.artifact_id}:{parent_id}")
            self._validate_cross_domain_parent_contract(item, by_id, blockers)

        ordered = self._topological_order(by_id)
        if len(ordered) != len(by_id):
            blockers.append("lineage_cycle")
        return ArtifactLineageReport(
            status="complete" if not blockers else "incomplete",
            artifact_count=len(items),
            ordered_artifact_ids=ordered,
            blockers=tuple(dict.fromkeys(blockers)),
        )

    @staticmethod
    def _validate_fields(item: ArtifactIdentity, blockers: list[str]) -> None:
        required = {
            "artifact_id": item.artifact_id,
            "artifact_type": item.artifact_type,
            "run_id": item.run_id,
            "decision_date": item.decision_date,
            "as_of_date": item.as_of_date,
            "available_date": item.available_date,
            "source_id": item.source_id,
            "source_version": item.source_version,
            "data_quality": item.data_quality,
            "missing_state": item.missing_state,
            "strategy_version": item.strategy_version,
            "policy_version": item.policy_version,
            "evidence_tier": item.evidence_tier,
            "current_status": item.current_status,
            "content_hash": item.content_hash,
        }
        for name, value in required.items():
            if not str(value).strip():
                blockers.append(f"missing_field:{item.artifact_id}:{name}")
        try:
            if date.fromisoformat(item.available_date) > date.fromisoformat(item.decision_date):
                blockers.append(f"future_available_date:{item.artifact_id}")
            if date.fromisoformat(item.as_of_date) > date.fromisoformat(item.decision_date):
                blockers.append(f"future_as_of_date:{item.artifact_id}")
        except ValueError:
            blockers.append(f"invalid_date:{item.artifact_id}")
        if len(item.content_hash) != 64:
            blockers.append(f"invalid_content_hash:{item.artifact_id}")
        if not item.rollback_reference.strip():
            blockers.append(f"missing_rollback_reference:{item.artifact_id}")

    @staticmethod
    def _validate_cross_domain_parent_contract(
        item: ArtifactIdentity,
        by_id: dict[str, ArtifactIdentity],
        blockers: list[str],
    ) -> None:
        """Enforce the fixed rehearsal chain while retaining upstream multi-parent lineage."""
        if item.artifact_type not in _CROSS_DOMAIN_ARTIFACT_TYPES:
            return
        parent_types = tuple(
            by_id[parent_id].artifact_type
            for parent_id in item.parent_artifact_ids
            if parent_id in by_id
        )
        if item.artifact_type == _CROSS_DOMAIN_ARTIFACT_TYPES[0]:
            for parent_id in item.parent_artifact_ids:
                parent = by_id.get(parent_id)
                if parent is not None:
                    blockers.append(
                        "invalid_cross_domain_parent:"
                        f"{item.artifact_id}:{parent_id}:{parent.artifact_type}:none"
                    )
            return
        expected_parent_type = _REQUIRED_PARENT_ARTIFACT_TYPES[item.artifact_type]
        if expected_parent_type not in parent_types:
            blockers.append(
                "missing_required_cross_domain_parent:"
                f"{item.artifact_id}:{expected_parent_type}"
            )
        permitted_parent_types = _CROSS_DOMAIN_ARTIFACT_TYPES[
            :_CROSS_DOMAIN_ARTIFACT_TYPES.index(item.artifact_type)
        ]
        for parent_id in item.parent_artifact_ids:
            parent = by_id.get(parent_id)
            if parent is not None and parent.artifact_type not in permitted_parent_types:
                blockers.append(
                    "invalid_cross_domain_parent:"
                    f"{item.artifact_id}:{parent_id}:{parent.artifact_type}:{expected_parent_type}"
                )

    @staticmethod
    def _topological_order(by_id: dict[str, ArtifactIdentity]) -> tuple[str, ...]:
        indegree = {artifact_id: 0 for artifact_id in by_id}
        children: dict[str, list[str]] = {artifact_id: [] for artifact_id in by_id}
        for item in by_id.values():
            for parent_id in item.parent_artifact_ids:
                if parent_id in by_id:
                    indegree[item.artifact_id] += 1
                    children[parent_id].append(item.artifact_id)
        ready = sorted(key for key, degree in indegree.items() if degree == 0)
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for child in sorted(children[current]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort()
        return tuple(ordered)
