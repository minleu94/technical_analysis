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
    def __init__(
        self,
        results: dict[str, FakeReplayResult],
        period_results: dict[tuple[str, str, str], FakeReplayResult] | None = None,
    ) -> None:
        self.results = results
        self.period_results = period_results or {}
        self.calls: list[tuple[RecommendationProfile, ProfileReplayComparisonRequest]] = []

    def run_profile_replay(
        self,
        profile: RecommendationProfile,
        request: ProfileReplayComparisonRequest,
    ) -> FakeReplayResult:
        self.calls.append((profile, request))
        period_key = (profile.profile_id, request.start_date, request.end_date)
        if period_key in self.period_results:
            return self.period_results[period_key]
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


def test_compare_profiles_uses_independent_validation_period_for_candidate() -> None:
    runner = FakeReplayRunner(
        results={},
        period_results={
            ("momentum", "2025-01-01", "2025-06-30"): FakeReplayResult(2600, 1800, 1000, 28),
            ("momentum", "2025-07-01", "2025-12-31"): FakeReplayResult(-500, -300, 4200, 24),
            ("stable", "2025-01-01", "2025-06-30"): FakeReplayResult(400, 200, 1200, 24),
            ("stable", "2025-07-01", "2025-12-31"): FakeReplayResult(900, 500, 1800, 24),
            ("long_term", "2025-01-01", "2025-06-30"): FakeReplayResult(100, 50, 800, 24),
            ("long_term", "2025-07-01", "2025-12-31"): FakeReplayResult(150, None, 700, 24),
        },
    )
    service = ProfileReplayComparisonService(
        profile_service=FakeProfileService(),
        replay_runner=runner,
    )

    result = service.compare_profiles(
        ProfileReplayComparisonRequest(
            start_date="2025-01-01",
            end_date="2025-06-30",
            validation_start_date="2025-07-01",
            validation_end_date="2025-12-31",
        )
    )

    by_profile = {row.profile_id: row for row in result.rows}
    assert [row.profile_id for row in result.rows] == ["stable", "momentum", "long_term"]
    assert by_profile["momentum"].benchmark_excess_bp == -300
    assert by_profile["momentum"].training_benchmark_excess_bp == 1800
    assert by_profile["momentum"].validation_benchmark_excess_bp == -300
    assert by_profile["momentum"].validation_gap_benchmark_excess_bp == -2100
    assert by_profile["momentum"].lifecycle_candidate == "demote_candidate"
    assert by_profile["stable"].lifecycle_candidate == "promote_candidate"
    assert by_profile["long_term"].lifecycle_candidate == "insufficient_evidence"
    assert "validation_period_used" in by_profile["stable"].warnings
    assert "validation_benchmark_excess_missing" in by_profile["long_term"].warnings
    assert len(runner.calls) == 6


def test_compare_profiles_rejects_overlapping_validation_period() -> None:
    service = ProfileReplayComparisonService(
        profile_service=FakeProfileService(),
        replay_runner=FakeReplayRunner({}),
    )

    try:
        service.compare_profiles(
            ProfileReplayComparisonRequest(
                start_date="2025-01-01",
                end_date="2025-07-01",
                validation_start_date="2025-07-01",
                validation_end_date="2025-12-31",
            )
        )
    except ValueError as exc:
        assert "validation_start_date must be after end_date" in str(exc)
    else:
        raise AssertionError("Expected overlapping validation period to be rejected")
