from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from app_module.evidence_event_dtos import (
    EvidenceEvent,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
    normalize_outcome_status,
)
from app_module.score_effectiveness_dtos import ScoreBucketAuditRow, ScoreEffectivenessReport


SCORE_BUCKETS = ("0-40", "40-50", "50-60", "60-70", "70-80", "80-100")
SCORE_BUCKET_LIMITS: tuple[tuple[str, Decimal, Decimal, bool], ...] = (
    ("0-40", Decimal("0"), Decimal("40"), False),
    ("40-50", Decimal("40"), Decimal("50"), False),
    ("50-60", Decimal("50"), Decimal("60"), False),
    ("60-70", Decimal("60"), Decimal("70"), False),
    ("70-80", Decimal("70"), Decimal("80"), False),
    ("80-100", Decimal("80"), Decimal("100"), True),
)

READ_ONLY_ACCESS_BOUNDARY = {
    "writes_allowed": False,
    "production_scheduler_allowed": False,
    "investment_effectiveness_claim": False,
    "ml_training_allowed": False,
}

REPORT_LIMITATIONS = (
    "此報告僅為研究證據，用於檢視既有 score 與 forward outcome 的關係，不是交易建議。",
    "收盤到收盤前瞻報酬不是可執行實盤績效，也不能單獨證明投資有效性。",
    "本報告不改 ScoringEngine、不改推薦權重、不改 threshold、不啟用 scheduler，也不訓練 ML 模型。",
)


def total_score_bucket(score: Decimal) -> str:
    value = Decimal(score)
    if value < Decimal("0"):
        return "0-40"
    for bucket, lower, upper, include_upper in SCORE_BUCKET_LIMITS:
        if value >= lower and (value < upper or (include_upper and value <= upper)):
            return bucket
    return "80-100"


def total_score_bucket_from_bp(score_bp: int | None) -> str | None:
    if score_bp is None:
        return None
    return total_score_bucket(Decimal(int(score_bp)) / Decimal("100"))


@dataclass(frozen=True)
class _BucketAccumulator:
    event_ids: frozenset[str]
    outcomes: tuple[EvidenceOutcome, ...]


class ScoreEffectivenessReadModel:
    """Read-only TotalScore bucket audit over existing evidence outcomes."""

    def __init__(
        self,
        *,
        events: Iterable[EvidenceEvent],
        outcomes: Iterable[EvidenceOutcome],
        source_mode: str = "in_memory",
    ) -> None:
        self.events = tuple(events)
        self.outcomes = tuple(outcomes)
        self.source_mode = source_mode

    def build_report(self, *, min_sample_size: int = 1) -> ScoreEffectivenessReport:
        outcome_by_event_id: dict[str, list[EvidenceOutcome]] = defaultdict(list)
        for outcome in self.outcomes:
            outcome_by_event_id[outcome.event_id].append(outcome)

        grouped_event_ids: dict[str, set[str]] = {bucket: set() for bucket in SCORE_BUCKETS}
        grouped_outcomes: dict[str, list[EvidenceOutcome]] = {bucket: [] for bucket in SCORE_BUCKETS}
        diagnostics: list[str] = []

        for event in self.events:
            bucket = total_score_bucket_from_bp(event.score_bp)
            if bucket is None:
                diagnostics.append(f"event_missing_score_bp:{event.event_id}")
                continue
            grouped_event_ids[bucket].add(event.event_id)
            grouped_outcomes[bucket].extend(outcome_by_event_id.get(event.event_id, ()))

        rows = tuple(
            self._build_bucket_row(
                bucket,
                _BucketAccumulator(
                    event_ids=frozenset(grouped_event_ids[bucket]),
                    outcomes=tuple(grouped_outcomes[bucket]),
                ),
                min_sample_size=min_sample_size,
            )
            for bucket in SCORE_BUCKETS
        )
        return ScoreEffectivenessReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_mode=self.source_mode,
            buckets=rows,
            access_boundary=dict(READ_ONLY_ACCESS_BOUNDARY),
            limitations=REPORT_LIMITATIONS,
            diagnostics=tuple(diagnostics),
        )

    def _build_bucket_row(
        self,
        bucket: str,
        accumulator: _BucketAccumulator,
        *,
        min_sample_size: int,
    ) -> ScoreBucketAuditRow:
        outcomes = accumulator.outcomes
        ready = [outcome for outcome in outcomes if normalize_outcome_status(outcome.outcome_status) == EvidenceOutcomeStatus.READY]
        pending = [
            outcome
            for outcome in outcomes
            if normalize_outcome_status(outcome.outcome_status)
            in (EvidenceOutcomeStatus.PENDING, EvidenceOutcomeStatus.INSUFFICIENT_FUTURE_DATA)
        ]
        missing = [
            outcome
            for outcome in outcomes
            if normalize_outcome_status(outcome.outcome_status) == EvidenceOutcomeStatus.MISSING_PRICE
        ]
        warnings: list[str] = []
        limitations: list[str] = []
        if not accumulator.event_ids:
            limitations.append("此分數區間目前沒有樣本，不能解讀為有效或無效。")
        elif len(accumulator.event_ids) < min_sample_size:
            limitations.append("此分數區間樣本數低於最小門檻，只能作為觀察。")
        if any(outcome.benchmark_excess_bp is None for outcome in ready):
            warnings.append("missing_benchmark_excess")
        if any(outcome.industry_excess_bp is None for outcome in ready):
            warnings.append("missing_industry_excess")
        if pending:
            warnings.append("pending_forward_outcome")
        if missing:
            warnings.append("missing_forward_outcome")

        return ScoreBucketAuditRow(
            bucket=bucket,
            sample_count=len(accumulator.event_ids),
            ready_outcome_count=len(ready),
            pending_outcome_count=len(pending),
            missing_outcome_count=len(missing),
            forward_return_bp_by_horizon=self._mean_by_horizon(
                (outcome.window_days, outcome.forward_return_bp)
                for outcome in ready
                if outcome.forward_return_bp is not None
            ),
            benchmark_excess_bp_by_horizon=self._mean_by_horizon(
                (outcome.window_days, outcome.benchmark_excess_bp)
                for outcome in ready
                if outcome.benchmark_excess_bp is not None
            ),
            industry_excess_bp_by_horizon=self._mean_by_horizon(
                (outcome.window_days, outcome.industry_excess_bp)
                for outcome in ready
                if outcome.industry_excess_bp is not None
            ),
            max_drawdown_bp_by_horizon=self._worst_drawdown_by_horizon(ready),
            win_rate_bp_by_horizon=self._win_rate_by_horizon(ready),
            warnings=sorted(set(warnings)),
            limitations=limitations,
        )

    @staticmethod
    def _mean_by_horizon(pairs: Iterable[tuple[int, int | None]]) -> dict[str, int]:
        values: dict[int, list[int]] = defaultdict(list)
        for horizon, value in pairs:
            if value is not None:
                values[int(horizon)].append(int(value))
        return {
            str(horizon): int((Decimal(sum(items)) / Decimal(len(items))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            for horizon, items in sorted(values.items())
            if items
        }

    @staticmethod
    def _worst_drawdown_by_horizon(outcomes: Iterable[EvidenceOutcome]) -> dict[str, int]:
        values: dict[int, list[int]] = defaultdict(list)
        for outcome in outcomes:
            if outcome.max_adverse_excursion_bp is not None:
                values[outcome.window_days].append(int(outcome.max_adverse_excursion_bp))
        return {str(horizon): min(items) for horizon, items in sorted(values.items()) if items}

    @staticmethod
    def _win_rate_by_horizon(outcomes: Iterable[EvidenceOutcome]) -> dict[str, int]:
        success: dict[int, int] = defaultdict(int)
        total: dict[int, int] = defaultdict(int)
        for outcome in outcomes:
            if outcome.forward_return_bp is None:
                continue
            horizon = int(outcome.window_days)
            total[horizon] += 1
            if int(outcome.forward_return_bp) > 0:
                success[horizon] += 1
        return {
            str(horizon): int(round(success[horizon] * 10000 / denominator))
            for horizon, denominator in sorted(total.items())
            if denominator > 0
        }
