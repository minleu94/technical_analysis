"""V1.1 recommendation profile replay comparison service.

本服務只聚合已治理的 Profile 與回放 runner 結果，產生人工覆盤用比較摘要。
它不直接重跑推薦核心、不寫入策略生命週期狀態，也不套用降級或淘汰動作。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app_module.profile_replay_comparison_dtos import (
    LIFECYCLE_DEMOTE_CANDIDATE,
    LIFECYCLE_HOLD,
    LIFECYCLE_INSUFFICIENT_EVIDENCE,
    LIFECYCLE_PROMOTE_CANDIDATE,
    LIFECYCLE_RETIRE_CANDIDATE,
    ProfileReplayComparisonRequest,
    ProfileReplayComparisonResult,
    ProfileReplayComparisonRow,
)
from app_module.recommendation_profile_service import RecommendationProfile


class ProfileReplayComparisonService:
    """Compare multiple recommendation profiles under the same replay assumptions."""

    def __init__(
        self,
        profile_service: Any,
        replay_runner: Any,
        *,
        min_trades: int = 20,
        promote_max_drawdown_bp: int = 3000,
        demote_drawdown_bp: int = 4000,
        retire_drawdown_bp: int = 6000,
    ) -> None:
        self.profile_service = profile_service
        self.replay_runner = replay_runner
        self.min_trades = int(min_trades)
        self.promote_max_drawdown_bp = int(promote_max_drawdown_bp)
        self.demote_drawdown_bp = int(demote_drawdown_bp)
        self.retire_drawdown_bp = int(retire_drawdown_bp)

    def compare_profiles(
        self,
        request: ProfileReplayComparisonRequest,
    ) -> ProfileReplayComparisonResult:
        rows = [
            self._compare_profile(profile, request)
            for profile in self.profile_service.list_profiles()
            if getattr(profile, "enabled", True)
        ]
        ordered_rows = tuple(
            sorted(
                rows,
                key=lambda row: (
                    self._sort_value(row.benchmark_excess_bp),
                    self._sort_value(row.total_return_bp),
                    -self._sort_value(row.max_drawdown_bp),
                    row.profile_id,
                ),
                reverse=True,
            )
        )
        return ProfileReplayComparisonResult(
            request=request,
            rows=ordered_rows,
            summary=self._summary(ordered_rows),
        )

    def _compare_profile(
        self,
        profile: RecommendationProfile,
        request: ProfileReplayComparisonRequest,
    ) -> ProfileReplayComparisonRow:
        replay_result = self.replay_runner.run_profile_replay(profile, request)
        warnings = list(self._get_tuple(replay_result, "warnings"))
        quality = str(self._get_value(replay_result, "quality", "observed") or "observed").lower()
        trade_count = int(self._get_value(replay_result, "trade_count", 0) or 0)
        benchmark_excess_bp = self._optional_int(self._get_value(replay_result, "benchmark_excess_bp", None))
        total_return_bp = self._optional_int(self._get_value(replay_result, "total_return_bp", None))
        max_drawdown_bp = self._optional_int(self._get_value(replay_result, "max_drawdown_bp", None))

        if trade_count < self.min_trades:
            warnings.append("trade_count_below_minimum")
        if benchmark_excess_bp is None:
            warnings.append("benchmark_excess_missing")
        if quality in {"missing", "degraded", "stale", "unavailable"}:
            warnings.append(f"quality_{quality}")

        lifecycle_candidate = self._candidate(
            trade_count=trade_count,
            benchmark_excess_bp=benchmark_excess_bp,
            max_drawdown_bp=max_drawdown_bp,
            quality=quality,
        )
        return ProfileReplayComparisonRow(
            profile_id=profile.profile_id,
            profile_name=profile.name,
            profile_version=profile.version,
            applicable_regimes=tuple(profile.applicable_regimes),
            total_return_bp=total_return_bp,
            benchmark_excess_bp=benchmark_excess_bp,
            max_drawdown_bp=max_drawdown_bp,
            trade_count=trade_count,
            quality=quality,
            warnings=tuple(sorted(set(warnings))),
            lifecycle_candidate=lifecycle_candidate,
        )

    def _candidate(
        self,
        *,
        trade_count: int,
        benchmark_excess_bp: int | None,
        max_drawdown_bp: int | None,
        quality: str,
    ) -> str:
        if trade_count < self.min_trades or benchmark_excess_bp is None:
            return LIFECYCLE_INSUFFICIENT_EVIDENCE

        drawdown_bp = int(max_drawdown_bp or 0)
        if benchmark_excess_bp <= -1000 and drawdown_bp >= self.retire_drawdown_bp:
            return LIFECYCLE_RETIRE_CANDIDATE
        if benchmark_excess_bp < 0 or drawdown_bp >= self.demote_drawdown_bp:
            return LIFECYCLE_DEMOTE_CANDIDATE
        if quality in {"missing", "degraded", "stale", "unavailable"}:
            return LIFECYCLE_HOLD
        if benchmark_excess_bp >= 0 and drawdown_bp <= self.promote_max_drawdown_bp:
            return LIFECYCLE_PROMOTE_CANDIDATE
        return LIFECYCLE_HOLD

    @staticmethod
    def _summary(rows: tuple[ProfileReplayComparisonRow, ...]) -> dict[str, int]:
        counts = Counter(row.lifecycle_candidate for row in rows)
        return {
            "profile_count": len(rows),
            "promote_candidate_count": counts.get(LIFECYCLE_PROMOTE_CANDIDATE, 0),
            "hold_count": counts.get(LIFECYCLE_HOLD, 0),
            "demote_candidate_count": counts.get(LIFECYCLE_DEMOTE_CANDIDATE, 0),
            "retire_candidate_count": counts.get(LIFECYCLE_RETIRE_CANDIDATE, 0),
            "insufficient_evidence_count": counts.get(LIFECYCLE_INSUFFICIENT_EVIDENCE, 0),
        }

    @staticmethod
    def _get_value(value: Any, key: str, default: Any) -> Any:
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)

    @classmethod
    def _get_tuple(cls, value: Any, key: str) -> tuple[str, ...]:
        raw = cls._get_value(value, key, ())
        if raw is None:
            return ()
        return tuple(str(item) for item in raw)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @staticmethod
    def _sort_value(value: int | None) -> int:
        if value is None:
            return -10**12
        return int(value)
