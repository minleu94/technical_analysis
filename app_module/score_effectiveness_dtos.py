from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScoreBucketAuditRow:
    bucket: str
    sample_count: int = 0
    ready_outcome_count: int = 0
    pending_outcome_count: int = 0
    missing_outcome_count: int = 0
    forward_return_bp_by_horizon: dict[str, int] = field(default_factory=dict)
    benchmark_excess_bp_by_horizon: dict[str, int] = field(default_factory=dict)
    industry_excess_bp_by_horizon: dict[str, int] = field(default_factory=dict)
    max_drawdown_bp_by_horizon: dict[str, int] = field(default_factory=dict)
    win_rate_bp_by_horizon: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreEffectivenessReport:
    generated_at: str
    source_mode: str
    buckets: tuple[ScoreBucketAuditRow, ...]
    access_boundary: dict[str, bool]
    limitations: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "source_mode": self.source_mode,
            "buckets": [bucket.to_dict() for bucket in self.buckets],
            "access_boundary": dict(self.access_boundary),
            "limitations": list(self.limitations),
            "diagnostics": list(self.diagnostics),
        }
