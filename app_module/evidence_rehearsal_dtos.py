from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import PurePath
import re
from typing import Any, Literal, Mapping


EvidenceTier = Literal[
    "engineering_fixture",
    "historical_replay_candidate",
    "shadow_comparison",
    "forward_handoff_pending",
]

_ALLOWED_TIERS = frozenset(
    {
        "engineering_fixture",
        "historical_replay_candidate",
        "shadow_comparison",
        "forward_handoff_pending",
    }
)
_PRODUCTION_PATH_MARKERS = frozenset({"prod", "production"})


def _require_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an ISO date") from error


def _require_safe_db_path(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty path")
    normalized_path = value.replace("\\", "/")
    parts = {part.lower() for part in PurePath(normalized_path).parts}
    path_tokens = {
        token.lower()
        for part in normalized_path.split("/")
        for token in re.split(r"[_.-]+", part)
        if token
    }
    if parts & _PRODUCTION_PATH_MARKERS or path_tokens & _PRODUCTION_PATH_MARKERS:
        raise ValueError(f"{field_name} must not reference a production-like database")


def _require_tier(value: str, field_name: str = "tier") -> None:
    if value not in _ALLOWED_TIERS:
        raise ValueError(f"{field_name} must be a supported evidence tier")


def _require_non_negative_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True)
class EvidenceRehearsalScenario:
    scenario_id: str
    decision_date: str
    source_db_path: str
    working_copy_db_path: str
    tier: EvidenceTier
    production_actions_allowed: bool = False

    def __post_init__(self) -> None:
        _require_date(self.decision_date, "decision_date")
        _require_safe_db_path(self.source_db_path, "source_db_path")
        _require_safe_db_path(self.working_copy_db_path, "working_copy_db_path")
        _require_tier(self.tier)
        if self.production_actions_allowed is not False:
            raise ValueError("production_actions_allowed must be False")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CoverageMetric:
    source_id: str
    total_count: int
    observed_count: int
    degraded_count: int
    missing_count: int
    future_blocked_count: int
    immature_label_count: int
    coverage_bp: int

    def __post_init__(self) -> None:
        for field_name in (
            "total_count",
            "observed_count",
            "degraded_count",
            "missing_count",
            "future_blocked_count",
            "immature_label_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        if isinstance(self.coverage_bp, bool) or not isinstance(self.coverage_bp, int):
            raise ValueError("coverage_bp must be an integer")
        if not 0 <= self.coverage_bp <= 10_000:
            raise ValueError("coverage_bp must be between 0 and 10000")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RehearsalArtifact:
    artifact_id: str
    decision_date: str
    available_date: str
    tier: EvidenceTier
    as_of_date: str | None = None
    parent_artifact_ids: tuple[str, ...] = ()
    source_version: str | None = None
    data_quality: str | None = None
    missing_state: str | None = None
    content_hash: str | None = None
    current_status: str | None = None
    effectiveness_denominator_included: bool | None = None
    diagnostics: tuple[str, ...] = ()
    canonical_payload: Mapping[str, Any] | None = None
    rollback_reference: str | None = None

    def __post_init__(self) -> None:
        decision_date = _require_date(self.decision_date, "decision_date")
        available_date = _require_date(self.available_date, "available_date")
        if available_date > decision_date:
            raise ValueError("available_date must not be later than decision_date")
        _require_tier(self.tier)
        if self.as_of_date is not None and _require_date(self.as_of_date, "as_of_date") > decision_date:
            raise ValueError("as_of_date must not be later than decision_date")
        if self.content_hash is not None and (len(self.content_hash) != 64 or not self.content_hash.isalnum()):
            raise ValueError("content_hash must be a SHA-256 hexadecimal digest")
        if self.effectiveness_denominator_included is not None and not isinstance(
            self.effectiveness_denominator_included, bool
        ):
            raise ValueError("effectiveness_denominator_included must be a boolean")
        object.__setattr__(self, "parent_artifact_ids", tuple(self.parent_artifact_ids))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "as_of_date",
            "source_version",
            "data_quality",
            "missing_state",
            "content_hash",
            "current_status",
            "effectiveness_denominator_included",
            "canonical_payload",
            "rollback_reference",
        ):
            if payload[field_name] is None:
                payload.pop(field_name)
        if not payload["parent_artifact_ids"]:
            payload.pop("parent_artifact_ids")
        if not payload["diagnostics"]:
            payload.pop("diagnostics")
        return payload


@dataclass(frozen=True)
class EvidenceRehearsalReport:
    scenario: EvidenceRehearsalScenario
    coverage_metrics: tuple[CoverageMetric, ...] = ()
    artifacts: tuple[RehearsalArtifact, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage_metrics", tuple(self.coverage_metrics))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario.to_dict(),
            "coverage_metrics": [metric.to_dict() for metric in self.coverage_metrics],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }
