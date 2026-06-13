import pytest
import pandas as pd
import numpy as np
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
    assert quantize_score_to_basis_points(np.nan) is None
    assert quantize_score_to_basis_points(None) is None

@pytest.mark.parametrize("params", [
    {"threshold_mode": "bad"},
    # Invalid missing parameters for quantile
    {"threshold_mode": "quantile", "buy_quantile_bp": 4000,
     "sell_quantile_bp": 4000, "quantile_warmup_observations": 60},
    # buy_quantile_bp == sell_quantile_bp
    {"threshold_mode": "quantile", "buy_quantile_bp": 4000,
     "sell_quantile_bp": 4000, "quantile_warmup_observations": 60,
     "quantile_method": "nearest_rank"},
    # Invalid range bp
    {"threshold_mode": "quantile", "buy_quantile_bp": 12000,
     "sell_quantile_bp": 4000, "quantile_warmup_observations": 60,
     "quantile_method": "nearest_rank"},
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

def test_edge_case_basis_points():
    # Test 0 bp and 10000 bp
    params = {
        "threshold_mode": "quantile",
        "buy_quantile_bp": 10000,
        "sell_quantile_bp": 0,
        "quantile_warmup_observations": 5,
        "quantile_method": "nearest_rank"
    }
    policy = ScoreThresholdPolicy(params)
    scores = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    result = policy.evaluate(scores)
    
    # At index 5: history of prior scores is [1000, 2000, 3000, 4000, 5000]
    # buy_threshold (10000 bp / 100% quantile) should be 5000 (max)
    # sell_threshold (0 bp / 0% quantile) should be 1000 (min)
    assert result.buy_threshold_score_bp.iloc[5] == 5000
    assert result.sell_threshold_score_bp.iloc[5] == 1000

def test_all_equal_scores():
    params = {
        "threshold_mode": "quantile",
        "buy_quantile_bp": 8000,
        "sell_quantile_bp": 4000,
        "quantile_warmup_observations": 5,
        "quantile_method": "nearest_rank"
    }
    policy = ScoreThresholdPolicy(params)
    scores = pd.Series([50.0] * 10)
    result = policy.evaluate(scores)
    # At index 5, history is [5000, 5000, 5000, 5000, 5000]
    # thresholds should be 5000
    assert result.buy_threshold_score_bp.iloc[5] == 5000
    assert result.sell_threshold_score_bp.iloc[5] == 5000
    assert bool(result.buy_candidate.iloc[5]) is True
    assert bool(result.sell_candidate.iloc[5]) is True

def test_nan_handling():
    params = {
        "threshold_mode": "quantile",
        "buy_quantile_bp": 8000,
        "sell_quantile_bp": 2000,
        "quantile_warmup_observations": 3,
        "quantile_method": "nearest_rank"
    }
    policy = ScoreThresholdPolicy(params)
    # 5 scores where index 2 is NaN
    scores = pd.Series([10.0, 20.0, np.nan, 30.0, 40.0])
    result = policy.evaluate(scores)
    
    # warmup_ready should only be True once we have 3 non-NaN values in history
    # index 0: history=[] (len=0) -> warmup=False
    # index 1: history=[10.0] (len=1) -> warmup=False
    # index 2: raw_score is NaN -> current_bp is None -> skipped -> warmup=False
    # index 3: history=[10.0, 20.0] (len=2) -> warmup=False (warmup needs 3)
    # index 4: history=[10.0, 20.0, 30.0] (len=3) -> warmup=True
    assert not result.warmup_ready.iloc[:4].any()
    assert result.warmup_ready.iloc[4]
    
    # history for index 4 is [1000, 2000, 3000]
    # buy_threshold (8000 bp): rank = max(1, (3 * 8000 + 9999)//10000) = max(1, 33999//10000) = 3 -> 3000
    # sell_threshold (2000 bp): rank = max(1, (3 * 2000 + 9999)//10000) = max(1, 15999//10000) = 1 -> 1000
    assert result.buy_threshold_score_bp.iloc[4] == 3000
    assert result.sell_threshold_score_bp.iloc[4] == 1000
