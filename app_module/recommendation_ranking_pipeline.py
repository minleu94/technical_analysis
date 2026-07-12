"""RecommendationService final ranking 的純 decision plan。"""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app_module.recommendation_errors import RecommendationUniverseTooSmallError
from decision_module.recommendation_percentile_ranker import calculate_score_percentiles
from decision_module.score_threshold_policy import quantize_score_to_basis_points


@dataclass(frozen=True)
class RecommendationRankingPlan:
    mode: str
    ordered_codes: tuple[str, ...]
    selected_codes: tuple[str, ...]
    percentiles_bp: Mapping[str, int]
    eligible_universe_size: int
    eligible_universe_date: str
    ranking_method: str
    minimum_percentile_bp: int | None


def build_ranking_plan(
    candidates: Sequence[tuple[str, Any]],
    *,
    mode: str,
    top_n: int,
    ranking_config: Mapping[str, Any],
    eligible_universe_date: str,
) -> RecommendationRankingPlan:
    """只以候選 code/score 建立排序與門檻決策，不突變 DTO 或 matrix。"""
    actual_size = len(candidates)
    if mode == "fixed":
        ordered = sorted(candidates, key=lambda item: item[1], reverse=True)
        ordered_codes = tuple(code for code, _ in ordered)
        return RecommendationRankingPlan(
            mode=mode,
            ordered_codes=ordered_codes,
            selected_codes=ordered_codes[:top_n],
            percentiles_bp={},
            eligible_universe_size=actual_size,
            eligible_universe_date=eligible_universe_date,
            ranking_method="fixed",
            minimum_percentile_bp=None,
        )

    minimum = int(ranking_config["recommendation_min_percentile_bp"])
    minimum_size = int(ranking_config["recommendation_min_universe_size"])
    method = str(ranking_config["recommendation_ranking_method"])
    if actual_size < minimum_size:
        raise RecommendationUniverseTooSmallError(actual_size, minimum_size)
    scores_by_stock: dict[str, int] = {}
    for code, score in candidates:
        score_bp = quantize_score_to_basis_points(score)
        if score_bp is None:
            raise ValueError(f"cannot quantize total score for stock {code}: score={score}")
        scores_by_stock[code] = score_bp
    percentiles = calculate_score_percentiles(scores_by_stock)
    eligible = [item for item in candidates if percentiles.get(item[0], 0) >= minimum]
    eligible.sort(key=lambda item: item[0])
    eligible.sort(key=lambda item: item[1], reverse=True)
    ordered_codes = tuple(code for code, _ in eligible)
    return RecommendationRankingPlan(
        mode=mode,
        ordered_codes=ordered_codes,
        selected_codes=ordered_codes[:top_n],
        percentiles_bp=percentiles,
        eligible_universe_size=actual_size,
        eligible_universe_date=eligible_universe_date,
        ranking_method=method,
        minimum_percentile_bp=minimum,
    )
