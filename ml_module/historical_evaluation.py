"""Integer persisted metrics for historical ML shadow evaluation."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from math import log2
from typing import Iterable, Sequence


def evaluate_historical_predictions(
    *,
    return_targets_bp: Sequence[int],
    downside_targets: Sequence[int],
    return_predictions_bp: Sequence[int],
    ranking_scores: Sequence[int],
    downside_probabilities_bp: Sequence[int],
    top_k: int,
) -> dict[str, int]:
    count = len(return_targets_bp)
    if not count or any(len(values) != count for values in (
        downside_targets, return_predictions_bp, ranking_scores,
        downside_probabilities_bp,
    )):
        raise ValueError("evaluation inputs must have equal non-zero lengths")
    if top_k <= 0 or top_k > count:
        raise ValueError("top_k is outside evaluation coverage")
    order = sorted(range(count), key=lambda index: (-ranking_scores[index], index))
    top = order[:top_k]
    mae = _mean_int(abs(return_targets_bp[i] - return_predictions_bp[i]) for i in range(count))
    brier = _mean_int(
        (downside_probabilities_bp[i] - downside_targets[i] * 10_000) ** 2
        for i in range(count)
    ) // 10_000
    precision = _ratio_bp(sum(return_targets_bp[i] > 0 for i in top), top_k)
    relevance = [max(0, return_targets_bp[i]) for i in order]
    ideal = sorted((max(0, value) for value in return_targets_bp), reverse=True)
    ndcg = _ndcg_bp(relevance[:top_k], ideal[:top_k])
    monotonic = _rank_monotonicity_bp(ranking_scores, return_targets_bp)
    return {
        "coverage_bp": 10_000,
        "mae_bp": mae,
        "brier_bp": brier,
        "precision_at_k_bp": precision,
        "ndcg_bp": ndcg,
        "bucket_monotonicity_bp": monotonic,
    }


def _mean_int(values: Iterable[int]) -> int:
    materialized: tuple[int, ...] = tuple(values)
    return _round_decimal(Decimal(sum(materialized)) / Decimal(len(materialized)))


def _ratio_bp(numerator: int, denominator: int) -> int:
    return _round_decimal(Decimal(numerator) / Decimal(denominator) * Decimal(10_000))


def _ndcg_bp(actual: Sequence[int], ideal: Sequence[int]) -> int:
    actual_score = sum(Decimal(value) / Decimal(str(log2(index + 2))) for index, value in enumerate(actual))
    ideal_score = sum(Decimal(value) / Decimal(str(log2(index + 2))) for index, value in enumerate(ideal))
    return 0 if ideal_score == 0 else _round_decimal(actual_score / ideal_score * Decimal(10_000))


def _rank_monotonicity_bp(scores: Sequence[int], targets: Sequence[int]) -> int:
    score_order = sorted(range(len(scores)), key=lambda index: (scores[index], index))
    target_order = sorted(range(len(targets)), key=lambda index: (targets[index], index))
    score_rank = {item: rank for rank, item in enumerate(score_order)}
    target_rank = {item: rank for rank, item in enumerate(target_order)}
    squared = sum((score_rank[index] - target_rank[index]) ** 2 for index in range(len(scores)))
    n = len(scores)
    if n < 2:
        return 0
    numerator = Decimal(6 * squared)
    denominator = Decimal(n * (n * n - 1))
    return _round_decimal((Decimal(1) - numerator / denominator) * Decimal(10_000))


def _round_decimal(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
