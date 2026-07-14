from __future__ import annotations

from ml_module.historical_evaluation import evaluate_historical_predictions


def test_evaluation_returns_deterministic_integer_metrics() -> None:
    metrics = evaluate_historical_predictions(
        return_targets_bp=(1000, 500, -500, -1000),
        downside_targets=(0, 0, 1, 1),
        return_predictions_bp=(900, 400, -400, -900),
        ranking_scores=(4, 3, 2, 1),
        downside_probabilities_bp=(1000, 2000, 8000, 9000),
        top_k=2,
    )

    assert metrics == {
        "coverage_bp": 10000,
        "mae_bp": 100,
        "brier_bp": 250,
        "precision_at_k_bp": 10000,
        "ndcg_bp": 10000,
        "bucket_monotonicity_bp": 10000,
    }
    assert all(type(value) is int for value in metrics.values())
