from typing import Mapping
from bisect import bisect_right

def validate_score_range(scores_by_stock: Mapping[str, int]) -> None:
    for stock_code, score_bp in scores_by_stock.items():
        if score_bp is None or not isinstance(score_bp, int) or score_bp < 0 or score_bp > 10000:
            raise ValueError(f"score must be between 0 and 10000, got {score_bp} for stock {stock_code}")

def calculate_score_percentiles(scores_by_stock: Mapping[str, int]) -> dict[str, int]:
    if not scores_by_stock:
        return {}
    validate_score_range(scores_by_stock)
    sorted_scores = sorted(scores_by_stock.values())
    universe_size = len(sorted_scores)
    return {
        stock_code: (
            bisect_right(sorted_scores, score_bp) * 10000
            + universe_size - 1
        ) // universe_size
        for stock_code, score_bp in scores_by_stock.items()
    }
