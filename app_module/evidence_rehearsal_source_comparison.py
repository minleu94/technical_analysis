"""Read-only P0 baseline/shadow comparison for evidence rehearsal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from app_module.source_candidate_readiness import SourceCandidateReadinessService
from data_module.p0_shadow_observation import P0ShadowObservation
from data_module.p0_source_contract_registry import ACCESS_BOUNDARY, P0_SOURCE_IDS, build_p0_source_contract_registry


@dataclass(frozen=True)
class P0SourceShadowComparisonItem:
    source_id: str
    baseline: dict[str, Any]
    shadow: dict[str, Any]
    blockers: tuple[str, ...]
    guidance: tuple[str, ...]
    review_status: str
    accepted: bool = False
    downstream_eligibility: str = "none"
    scoring_eligible: bool = False
    advice_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "baseline": dict(self.baseline),
            "shadow": dict(self.shadow),
            "blockers": list(self.blockers),
            "guidance": list(self.guidance),
            "review_status": self.review_status,
            "accepted": self.accepted,
            "downstream_eligibility": self.downstream_eligibility,
            "scoring_eligible": self.scoring_eligible,
            "advice_eligible": self.advice_eligible,
            "eligibility_delta": {"baseline": "none", "shadow": "none"},
        }


@dataclass(frozen=True)
class P0SourceShadowComparisonReport:
    decision_date: str
    items: tuple[P0SourceShadowComparisonItem, ...]
    access_boundary: dict[str, bool]
    candidate_readiness_access_boundary: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "p0-source-shadow-comparison.v1",
            "decision_date": self.decision_date,
            "items": [item.to_dict() for item in self.items],
            "access_boundary": dict(self.access_boundary),
            "candidate_readiness_access_boundary": dict(self.candidate_readiness_access_boundary),
        }


class P0SourceShadowComparisonService:
    """Projects adapter observations without accepting a P0 source or enabling downstream use."""

    def __init__(
        self,
        *,
        decision_date: str,
        baseline_observations: Iterable[P0ShadowObservation] = (),
        shadow_observations: Iterable[P0ShadowObservation] = (),
        source_outages: Mapping[str, str] | None = None,
        schema_missing_sources: Iterable[str] = (),
    ) -> None:
        self._decision_date = decision_date
        self._baseline_observations = tuple(baseline_observations)
        self._shadow_observations = tuple(shadow_observations)
        self._source_outages = dict(source_outages or {})
        self._schema_missing_sources = frozenset(schema_missing_sources)

    def build_report(self) -> P0SourceShadowComparisonReport:
        registry = build_p0_source_contract_registry()
        candidate_readiness = SourceCandidateReadinessService(
            decision_date=self._decision_date
        ).build_report()
        return P0SourceShadowComparisonReport(
            decision_date=self._decision_date,
            items=tuple(self._build_item(registry.require(source_id).source_id) for source_id in P0_SOURCE_IDS),
            access_boundary=dict(ACCESS_BOUNDARY),
            candidate_readiness_access_boundary=dict(candidate_readiness.access_boundary),
        )

    def _build_item(self, source_id: str) -> P0SourceShadowComparisonItem:
        baseline = self._for_source(self._baseline_observations, source_id)
        shadow = self._for_source(self._shadow_observations, source_id)
        blockers = self._blockers(source_id, shadow)
        return P0SourceShadowComparisonItem(
            source_id=source_id,
            baseline=_summary(baseline),
            shadow=_summary(shadow),
            blockers=blockers,
            guidance=_guidance(blockers),
            review_status="blocked" if blockers else "eligible_for_human_review",
        )

    @staticmethod
    def _for_source(
        observations: tuple[P0ShadowObservation, ...], source_id: str
    ) -> tuple[P0ShadowObservation, ...]:
        return tuple(item for item in observations if item.source_id == source_id)

    def _blockers(
        self, source_id: str, observations: tuple[P0ShadowObservation, ...]
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        if not observations:
            blockers.append("source_not_ingested")
        if source_id in self._source_outages:
            blockers.append(f"source_outage:{self._source_outages[source_id]}")
        if source_id in self._schema_missing_sources:
            blockers.append("schema_missing")
        for observation in observations:
            if observation.status != "shadow_ready":
                blockers.extend(observation.diagnostics)
                blockers.append("shadow_observation_blocked")
        return tuple(sorted(set(blockers)))


def _summary(observations: tuple[P0ShadowObservation, ...]) -> dict[str, Any]:
    ready_count = sum(item.status == "shadow_ready" for item in observations)
    coverage_bp = 10000 if observations and ready_count == len(observations) else 0
    quality = "observed" if ready_count else "missing"
    if observations and ready_count != len(observations):
        quality = "blocked"
    return {
        "observation_count": len(observations),
        "ready_observation_count": ready_count,
        "coverage_bp": coverage_bp,
        "quality": quality,
    }


def _guidance(blockers: tuple[str, ...]) -> tuple[str, ...]:
    guidance: list[str] = ["requires_human_acceptance"]
    if any(item.startswith("source_outage:") or item == "source_not_ingested" for item in blockers):
        guidance.append("retry_shadow_observation")
    if any(
        item == "schema_missing"
        or item == "shadow_observation_blocked"
        or item.startswith("future_available_date")
        for item in blockers
    ):
        guidance.append("quarantine_observation")
    return tuple(guidance)
