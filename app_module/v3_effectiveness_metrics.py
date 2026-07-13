"""Deterministic, integer-basis-point V3 effectiveness metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class EffectivenessMetrics:
    ready_count: int
    precision_at_k_bp: int | None
    hit_rate_bp: int | None
    average_gain_bp: int | None
    average_loss_abs_bp: int | None
    payoff_ratio_bp: int | None
    score_monotonic: bool | None
    bucket_average_returns_bp: tuple[int, ...]
    mae_mfe_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_count": self.ready_count,
            "precision_at_k_bp": self.precision_at_k_bp,
            "hit_rate_bp": self.hit_rate_bp,
            "average_gain_bp": self.average_gain_bp,
            "average_loss_abs_bp": self.average_loss_abs_bp,
            "payoff_ratio_bp": self.payoff_ratio_bp,
            "score_monotonic": self.score_monotonic,
            "bucket_average_returns_bp": list(self.bucket_average_returns_bp),
            "mae_mfe_ready": self.mae_mfe_ready,
        }


def compute_effectiveness_metrics(
    rows: Iterable[Mapping[str, Any]], *, k: int, bucket_count: int = 5
) -> EffectivenessMetrics:
    if k <= 0:
        raise ValueError("k must be positive")
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")

    ready = [
        row
        for row in rows
        if row.get("status") == "ready"
        and row.get("score_bp") is not None
        and row.get("return_bp") is not None
    ]
    ready_count = len(ready)
    if not ready:
        return EffectivenessMetrics(0, None, None, None, None, None, None, (), False)

    ranked = sorted(ready, key=lambda row: int(row["score_bp"]), reverse=True)
    top = ranked[: min(k, ready_count)]
    precision_bp = sum(int(row["return_bp"]) > 0 for row in top) * 10000 // len(top)
    gains = [int(row["return_bp"]) for row in ready if int(row["return_bp"]) > 0]
    losses = [-int(row["return_bp"]) for row in ready if int(row["return_bp"]) < 0]
    average_gain = sum(gains) // len(gains) if gains else None
    average_loss = sum(losses) // len(losses) if losses else None
    payoff = (
        average_gain * 10000 // average_loss
        if average_gain is not None and average_loss
        else None
    )
    bucket_returns = _bucket_average_returns(ready, bucket_count)
    monotonic = (
        all(left <= right for left, right in zip(bucket_returns, bucket_returns[1:]))
        if len(bucket_returns) > 1
        else None
    )
    mae_mfe_ready = all(
        row.get("mae_bp") is not None and row.get("mfe_bp") is not None
        for row in ready
    )
    return EffectivenessMetrics(
        ready_count=ready_count,
        precision_at_k_bp=precision_bp,
        hit_rate_bp=len(gains) * 10000 // ready_count,
        average_gain_bp=average_gain,
        average_loss_abs_bp=average_loss,
        payoff_ratio_bp=payoff,
        score_monotonic=monotonic,
        bucket_average_returns_bp=bucket_returns,
        mae_mfe_ready=mae_mfe_ready,
    )


def _bucket_average_returns(
    rows: list[Mapping[str, Any]], bucket_count: int
) -> tuple[int, ...]:
    ordered = sorted(rows, key=lambda row: int(row["score_bp"]))
    actual_bucket_count = min(bucket_count, len(ordered))
    buckets: list[list[int]] = [[] for _ in range(actual_bucket_count)]
    for index, row in enumerate(ordered):
        bucket_index = min(index * actual_bucket_count // len(ordered), actual_bucket_count - 1)
        buckets[bucket_index].append(int(row["return_bp"]))
    return tuple(sum(bucket) // len(bucket) for bucket in buckets)
