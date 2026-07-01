from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any, Iterable

from app_module.evidence_event_dtos import EvidenceEvent, EvidenceOutcome, EvidenceOutcomeStatus
from app_module.evidence_event_repository import EvidenceEventRepository


SUMMARY_STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
SUMMARY_STATUS_READY = "READY"
SUMMARY_STATUS_DEGRADED = "DEGRADED"
SUMMARY_STATUS_MISSING_BENCHMARK = "MISSING_BENCHMARK"
SUMMARY_STATUS_MISSING_INDUSTRY = "MISSING_INDUSTRY"

SUPPORTED_GROUP_BY = (
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


@dataclass(frozen=True)
class ForwardPerformanceFilter:
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
    window_days: int | None = None


@dataclass(frozen=True)
class ForwardPerformanceGroupSummary:
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
    quality_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)
    first_event_date: str | None = None
    last_event_date: str | None = None
    summary_status: str = SUMMARY_STATUS_INSUFFICIENT_SAMPLE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ForwardPerformanceReadModel:
    """Read-only aggregate view over evidence events and forward outcomes."""

    def __init__(self, repository: EvidenceEventRepository) -> None:
        self.repository = repository

    def summarize(
        self,
        *,
        group_by: str = "event_type",
        filters: ForwardPerformanceFilter | None = None,
        min_sample_size: int = 1,
    ) -> list[ForwardPerformanceGroupSummary]:
        if group_by not in SUPPORTED_GROUP_BY:
            raise ValueError(f"unsupported group_by: {group_by}")
        filters = filters or ForwardPerformanceFilter()
        events = self._filtered_events(filters)
        if not events:
            return []

        event_by_id = {event.event_id: event for event in events}
        outcomes = [
            outcome
            for outcome in self.repository.list_outcomes(window_days=filters.window_days)
            if outcome.event_id in event_by_id
        ]

        grouped: dict[tuple[str, int], list[tuple[EvidenceEvent, EvidenceOutcome]]] = defaultdict(list)
        for outcome in outcomes:
            event = event_by_id[outcome.event_id]
            grouped[(self._group_key(event, group_by), outcome.window_days)].append((event, outcome))

        summaries = [
            self._build_summary(group_by, group_key, window_days, rows, min_sample_size)
            for (group_key, window_days), rows in grouped.items()
        ]
        return sorted(summaries, key=lambda item: (item.group_by, item.group_key, item.window_days))

    def _filtered_events(self, filters: ForwardPerformanceFilter) -> list[EvidenceEvent]:
        events = self.repository.list_events(
            symbol=filters.symbol,
            event_type=filters.event_type,
            start_date=filters.start_date,
            end_date=filters.end_date,
        )
        return [
            event
            for event in events
            if self._matches(event.event_family, filters.event_family)
            and self._matches(event.source_type, filters.source_type)
            and self._matches(event.regime, filters.regime)
            and self._matches(event.sector, filters.sector)
            and self._matches(event.profile_id, filters.profile_id)
            and self._matches(event.strategy_version_id, filters.strategy_version_id)
        ]

    def _build_summary(
        self,
        group_by: str,
        group_key: str,
        window_days: int,
        rows: list[tuple[EvidenceEvent, EvidenceOutcome]],
        min_sample_size: int,
    ) -> ForwardPerformanceGroupSummary:
        ready = [row for row in rows if row[1].outcome_status == EvidenceOutcomeStatus.READY]
        pending_count = sum(1 for _, outcome in rows if outcome.outcome_status == EvidenceOutcomeStatus.INSUFFICIENT_FUTURE_DATA)
        missing_count = sum(1 for _, outcome in rows if outcome.outcome_status == EvidenceOutcomeStatus.MISSING_PRICE)
        dates = sorted(event.event_date for event, _ in rows)
        quality_counts = Counter(event.data_quality.value for event, _ in rows)
        quality_counts.update(outcome.data_quality.value for _, outcome in rows)
        warning_counts: Counter[str] = Counter()
        for event, outcome in rows:
            warning_counts.update(event.warnings)
            warning_counts.update(outcome.warnings)

        forward_values = [outcome.forward_return_bp for _, outcome in ready if outcome.forward_return_bp is not None]
        benchmark_values = [
            outcome.benchmark_excess_bp for _, outcome in ready if outcome.benchmark_excess_bp is not None
        ]
        industry_values = [
            outcome.industry_excess_bp for _, outcome in ready if outcome.industry_excess_bp is not None
        ]
        mae_values = [outcome.max_adverse_excursion_bp for _, outcome in ready if outcome.max_adverse_excursion_bp is not None]
        mfe_values = [
            outcome.max_favorable_excursion_bp for _, outcome in ready if outcome.max_favorable_excursion_bp is not None
        ]
        sample_size = len(ready)
        summary_status = self._summary_status(
            sample_size=sample_size,
            total_count=len(rows),
            min_sample_size=min_sample_size,
            missing_benchmark_count=sum(1 for _, outcome in ready if outcome.benchmark_excess_bp is None),
            missing_industry_count=sum(1 for _, outcome in ready if outcome.industry_excess_bp is None),
        )

        return ForwardPerformanceGroupSummary(
            group_by=group_by,
            group_key=group_key,
            window_days=window_days,
            sample_size=sample_size,
            pending_count=pending_count,
            missing_count=missing_count,
            mean_forward_return_bp=self._mean_bp(forward_values),
            median_forward_return_bp=self._median_bp(forward_values),
            mean_benchmark_excess_bp=self._mean_bp(benchmark_values),
            median_benchmark_excess_bp=self._median_bp(benchmark_values),
            mean_industry_excess_bp=self._mean_bp(industry_values),
            median_industry_excess_bp=self._median_bp(industry_values),
            positive_rate_bp=self._rate_bp(sum(1 for value in forward_values if value > 0), sample_size),
            win_vs_benchmark_rate_bp=self._rate_bp(sum(1 for value in benchmark_values if value > 0), len(benchmark_values)),
            win_vs_industry_rate_bp=self._rate_bp(sum(1 for value in industry_values if value > 0), len(industry_values)),
            mean_mae_bp=self._mean_bp(mae_values),
            mean_mfe_bp=self._mean_bp(mfe_values),
            quality_counts=dict(sorted(quality_counts.items())),
            warning_counts=dict(sorted(warning_counts.items())),
            first_event_date=dates[0] if dates else None,
            last_event_date=dates[-1] if dates else None,
            summary_status=summary_status,
        )

    @staticmethod
    def _summary_status(
        *,
        sample_size: int,
        total_count: int,
        min_sample_size: int,
        missing_benchmark_count: int,
        missing_industry_count: int,
    ) -> str:
        if sample_size < min_sample_size:
            return SUMMARY_STATUS_INSUFFICIENT_SAMPLE
        if sample_size == 0:
            return SUMMARY_STATUS_INSUFFICIENT_SAMPLE
        if missing_benchmark_count * 2 > sample_size:
            return SUMMARY_STATUS_MISSING_BENCHMARK
        if missing_industry_count * 2 > sample_size:
            return SUMMARY_STATUS_MISSING_INDUSTRY
        if total_count > sample_size:
            return SUMMARY_STATUS_DEGRADED
        if missing_benchmark_count or missing_industry_count:
            return SUMMARY_STATUS_DEGRADED
        return SUMMARY_STATUS_READY

    @staticmethod
    def _group_key(event: EvidenceEvent, group_by: str) -> str:
        if group_by == "event_type":
            return event.event_type.value
        if group_by == "data_quality":
            return event.data_quality.value
        if group_by == "score_percentile_bucket":
            return score_percentile_bucket(event.score_percentile_bp)
        value = getattr(event, group_by)
        return str(value) if value not in (None, "") else "missing"

    @staticmethod
    def _matches(actual: Any, expected: str | None) -> bool:
        return expected is None or str(actual) == expected

    @staticmethod
    def _mean_bp(values: Iterable[int | None]) -> int | None:
        clean = [int(value) for value in values if value is not None]
        if not clean:
            return None
        return int(round(sum(clean) / len(clean)))

    @staticmethod
    def _median_bp(values: Iterable[int | None]) -> int | None:
        clean = [int(value) for value in values if value is not None]
        if not clean:
            return None
        return int(round(median(clean)))

    @staticmethod
    def _rate_bp(success_count: int, denominator: int) -> int | None:
        if denominator <= 0:
            return None
        return int(round(success_count * 10000 / denominator))


def score_percentile_bucket(value: int | None) -> str:
    if value is None:
        return "missing"
    parsed = int(value)
    if parsed <= 2000:
        return "0-2000"
    if parsed <= 4000:
        return "2001-4000"
    if parsed <= 6000:
        return "4001-6000"
    if parsed <= 8000:
        return "6001-8000"
    return "8001-10000"
