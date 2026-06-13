import pytest
import pandas as pd
from decimal import Decimal
from decision_module.score_threshold_policy import (
    quantize_score_to_basis_points,
    ScoreThresholdPolicy,
    ScoreThresholdResult
)

def test_quantize_score_uses_decimal_half_up():
    assert quantize_score_to_basis_points("60.005") == 6001
    assert quantize_score_to_basis_points(0) == 0
    assert quantize_score_to_basis_points(100) == 10000

@pytest.mark.parametrize("params", [
    {"threshold_mode": "bad"},
    # Invalid missing parameters for quantile
    {"threshold_mode": "quantile", "buy_quantile_bp": 4000,
     "sell_quantile_bp": 4000, "quantile_warmup_observations": 60},
])
def test_invalid_threshold_params_are_rejected(params):
    with pytest.raises(ValueError):
        ScoreThresholdPolicy(params)

def quantile_params():
    return {
        "threshold_mode": "quantile",
        "buy_quantile_bp": 1000,  # 10%
        "sell_quantile_bp": 9000,  # 90%
        "quantile_warmup_observations": 60,
        "quantile_method": "nearest_rank"
    }

def test_quantile_threshold_uses_only_prior_valid_observations():
    scores = pd.Series([10] * 59 + [90, 95], index=pd.date_range("2026-01-01", periods=61))
    result = ScoreThresholdPolicy(quantile_params()).evaluate(scores)
    assert not result.warmup_ready.iloc[:60].any()
    assert result.warmup_ready.iloc[60]
    assert result.buy_threshold_score_bp.iloc[60] == 1000

def test_appending_future_scores_does_not_change_existing_thresholds():
    original = pd.Series(range(61), index=pd.date_range("2026-01-01", periods=61))
    extended = pd.concat([original, pd.Series([100, 0], index=pd.date_range("2026-03-03", periods=2))])
    policy = ScoreThresholdPolicy(quantile_params())
    pd.testing.assert_frame_equal(
        policy.evaluate(original).to_frame(),
        policy.evaluate(extended).to_frame().iloc[:len(original)],
    )
