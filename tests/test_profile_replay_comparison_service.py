from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app_module.profile_replay_comparison_dtos import ProfileReplayComparisonRequest
from app_module.profile_replay_comparison_service import ProfileReplayComparisonService
from app_module.recommendation_profile_service import RecommendationProfile


@dataclass(frozen=True)
class FakeReplayResult:
    total_return_bp: int | None
    benchmark_excess_bp: int | None
    max_drawdown_bp: int | None
    trade_count: int
    quality: str = "observed"
    warnings: tuple[str, ...] = ()


class FakeProfileService:
    def __init__(self) -> None:
        self._profiles = [
            RecommendationProfile(
                profile_id="momentum",
                profile_type="builtin",
                name="暴衝策略",
                version="1.0.0",
                description="test",
                config={"signals": {"weights": {"pattern": 2500, "technical": 5500, "volume": 2000}}},
                applicable_regimes=["Trend", "Breakout"],
            ),
            RecommendationProfile(
                profile_id="stable",
                profile_type="builtin",
                name="穩健策略",
                version="1.0.0",
                description="test",
                config={"signals": {"weights": {"pattern": 3500, "technical": 4500, "volume": 2000}}},
                applicable_regimes=["Reversion"],
            ),
            RecommendationProfile(
                profile_id="long_term",
                profile_type="builtin",
                name="長期策略",
                version="1.0.0",
                description="test",
                config={"signals": {"weights": {"pattern": 2000, "technical": 6000, "volume": 2000}}},
                applicable_regimes=["Trend"],
            ),
        ]

    def list_profiles(self) -> list[RecommendationProfile]:
        return list(self._profiles)


class FakeReplayRunner:
    def __init__(self, results: dict[str, FakeReplayResult]) -> None:
        self.results = results
        self.calls: list[tuple[RecommendationProfile, ProfileReplayComparisonRequest]] = []

    def run_profile_replay(
        self,
        profile: RecommendationProfile,
        request: ProfileReplayComparisonRequest,
    ) -> FakeReplayResult:
        self.calls.append((profile, request))
        return self.results[profile.profile_id]


def test_compare_profiles_ranks_rows_and_marks_promote_candidate() -> None:
    service = ProfileReplayComparisonService(
        profile_service=FakeProfileService(),
        replay_runner=FakeReplayRunner(
            {
                "momentum": FakeReplayResult(1200, 500, 1800, 24),
                "stable": FakeReplayResult(800, 200, 1200, 22),
                "long_term": FakeReplayResult(400, 100, 900, 21),
            }
        ),
    )

    result = service.compare_profiles(
        ProfileReplayComparisonRequest(start_date="2025-07-02", end_date="2026-07-02")
    )

    assert [row.profile_id for row in result.rows] == ["momentum", "stable", "long_term"]
    assert result.rows[0].profile_name == "暴衝策略"
    assert result.rows[0].benchmark_excess_bp == 500
    assert result.rows[0].lifecycle_candidate == "promote_candidate"
    assert result.rows[0].applicable_regimes == ("Trend", "Breakout")
    assert result.summary["profile_count"] == 3
    assert result.summary["promote_candidate_count"] == 3


def test_compare_profiles_marks_insufficient_evidence_when_trade_count_low() -> None:
    service = ProfileReplayComparisonService(
        profile_service=FakeProfileService(),
        replay_runner=FakeReplayRunner(
            {
                "momentum": FakeReplayResult(2000, 1200, 2000, 6),
                "stable": FakeReplayResult(1000, None, 1000, 30),
                "long_term": FakeReplayResult(900, 300, 900, 21),
            }
        ),
        min_trades=20,
    )

    result = service.compare_profiles(
        ProfileReplayComparisonRequest(start_date="2025-07-02", end_date="2026-07-02")
    )

    by_profile = {row.profile_id: row for row in result.rows}
    assert by_profile["momentum"].lifecycle_candidate == "insufficient_evidence"
    assert by_profile["stable"].lifecycle_candidate == "insufficient_evidence"
    assert "trade_count_below_minimum" in by_profile["momentum"].warnings
    assert "benchmark_excess_missing" in by_profile["stable"].warnings


def test_compare_profiles_marks_demote_and_retire_candidates_from_saved_metrics() -> None:
    service = ProfileReplayComparisonService(
        profile_service=FakeProfileService(),
        replay_runner=FakeReplayRunner(
            {
                "momentum": FakeReplayResult(-300, -200, 4200, 25),
                "stable": FakeReplayResult(-1800, -1200, 6500, 25),
                "long_term": FakeReplayResult(200, 50, 2800, 25, quality="degraded"),
            }
        ),
    )

    result = service.compare_profiles(
        ProfileReplayComparisonRequest(start_date="2025-07-02", end_date="2026-07-02")
    )

    by_profile = {row.profile_id: row for row in result.rows}
    assert by_profile["momentum"].lifecycle_candidate == "demote_candidate"
    assert by_profile["stable"].lifecycle_candidate == "retire_candidate"
    assert by_profile["long_term"].lifecycle_candidate == "hold"
    assert "quality_degraded" in by_profile["long_term"].warnings
