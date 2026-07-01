from __future__ import annotations

from dataclasses import dataclass, field


SUPPORTED_DASHBOARD_GROUP_BY = (
    "event_type",
    "event_family",
    "source_type",
    "regime",
    "sector",
    "profile_id",
    "score_percentile_bucket",
    "liquidity_state",
    "data_quality",
)

DASHBOARD_STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
DASHBOARD_STATUS_MISSING_BENCHMARK = "MISSING_BENCHMARK"


@dataclass(frozen=True)
class ForwardPerformanceDashboardRequest:
    start_date: str | None = None
    end_date: str | None = None
    event_type: str | None = None
    event_family: str | None = None
    source_type: str | None = None
    symbol: str | None = None
    regime: str | None = None
    sector: str | None = None
    profile_id: str | None = None
    strategy_version_id: str | None = None
    window_days: int = 20
    group_by: str = "event_type"
    min_sample_size: int = 10


@dataclass(frozen=True)
class ForwardPerformanceDashboardCardSummary:
    total_events: int = 0
    ready_outcomes: int = 0
    pending_outcomes: int = 0
    missing_outcomes: int = 0
    groups_ready: int = 0
    groups_insufficient_sample: int = 0
    groups_degraded: int = 0
    missing_benchmark_count: int = 0
    missing_industry_count: int = 0
    warnings_count: int = 0


@dataclass(frozen=True)
class ForwardPerformanceDashboardRow:
    group_by: str
    group_key: str
    window_days: int
    sample_size: int
    pending_count: int
    missing_count: int
    mean_forward_return_bp: int | None
    median_forward_return_bp: int | None
    mean_benchmark_excess_bp: int | None
    median_benchmark_excess_bp: int | None
    mean_industry_excess_bp: int | None
    median_industry_excess_bp: int | None
    positive_rate_bp: int | None
    win_vs_benchmark_rate_bp: int | None
    win_vs_industry_rate_bp: int | None
    mean_mae_bp: int | None
    mean_mfe_bp: int | None
    summary_status: str
    first_event_date: str | None = None
    last_event_date: str | None = None
    quality_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ForwardPerformanceDashboardResult:
    request: ForwardPerformanceDashboardRequest
    cards: ForwardPerformanceDashboardCardSummary
    rows: tuple[ForwardPerformanceDashboardRow, ...] = ()
    empty_state_message: str = ""
    limitations: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
