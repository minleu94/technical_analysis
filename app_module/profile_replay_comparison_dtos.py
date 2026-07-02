"""DTOs for V1.1 recommendation profile replay comparison.

本模組只保存已完成推薦回放的比較摘要，不重新計算推薦或績效。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProfileReplayComparisonRequest:
    start_date: str
    end_date: str
    rebalance_frequency: str = "weekly"
    holding_days: int = 20
    top_n: int = 10
    benchmark_id: str = "taiex"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileReplayComparisonRow:
    profile_id: str
    profile_name: str
    profile_version: str
    applicable_regimes: tuple[str, ...]
    total_return_bp: int | None
    benchmark_excess_bp: int | None
    max_drawdown_bp: int | None
    trade_count: int
    quality: str
    warnings: tuple[str, ...] = ()
    lifecycle_candidate: str = "hold"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileReplayComparisonResult:
    request: ProfileReplayComparisonRequest
    rows: tuple[ProfileReplayComparisonRow, ...] = ()
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "rows": [row.to_dict() for row in self.rows],
            "summary": dict(self.summary),
        }


LIFECYCLE_PROMOTE_CANDIDATE = "promote_candidate"
LIFECYCLE_HOLD = "hold"
LIFECYCLE_DEMOTE_CANDIDATE = "demote_candidate"
LIFECYCLE_RETIRE_CANDIDATE = "retire_candidate"
LIFECYCLE_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
