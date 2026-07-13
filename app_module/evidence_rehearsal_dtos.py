from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import PurePath
from typing import Literal


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
    parts = {part.lower() for part in PurePath(value.replace("\\", "/")).parts}
    if parts & _PRODUCTION_PATH_MARKERS:
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

    def __post_init__(self) -> None:
        decision_date = _require_date(self.decision_date, "decision_date")
        available_date = _require_date(self.available_date, "available_date")
        if available_date > decision_date:
            raise ValueError("available_date must not be later than decision_date")
        _require_tier(self.tier)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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
