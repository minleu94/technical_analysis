import pytest
import pandas as pd
import numpy as np
from decision_module.score_threshold_policy import (
    quantize_score_to_basis_points,
    ScoreThresholdPolicy,
)

def test_quantize_score_uses_decimal_half_up():
    assert quantize_score_to_basis_points("60.005") == 6001
    assert quantize_score_to_basis_points(0) == 0
    assert quantize_score_to_basis_points(100) == 10000
    assert quantize_score_to_basis_points(np.nan) is None
    assert quantize_score_to_basis_points(None) is None


def test_fixed_mode_preserves_out_of_range_legacy_threshold_comparisons():
    policy = ScoreThresholdPolicy({
        "threshold_mode": "fixed",
        "buy_score": -100,
        "sell_score": -200,
    })

    result = policy.evaluate(pd.Series([-1.0, 0.0, 101.0]))

    assert result.buy_candidate.tolist() == [True, True, True]
    assert result.sell_candidate.tolist() == [False, False, False]

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
        "buy_quantile_bp": 8000,
        "sell_quantile_bp": 4000,
        "quantile_warmup_observations": 60,
        "quantile_method": "nearest_rank"
    }


@pytest.mark.parametrize("overrides", [
    {"buy_quantile_bp": 3000, "sell_quantile_bp": 4000},
    {"quantile_warmup_observations": 59},
    {"quantile_warmup_observations": 61},
    {"buy_quantile_bp": 8000.0},
    {"sell_quantile_bp": True},
])
def test_quantile_contract_rejects_invalid_order_warmup_and_types(overrides):
    params = quantile_params()
    params.update(overrides)

    with pytest.raises(ValueError):
        ScoreThresholdPolicy(params)

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
        "quantile_warmup_observations": 60,
        "quantile_method": "nearest_rank"
    }
    policy = ScoreThresholdPolicy(params)
    scores = pd.Series(list(range(1, 61)) + [61.0])
    result = policy.evaluate(scores)
    
    assert result.buy_threshold_score_bp.iloc[60] == 6000
    assert result.sell_threshold_score_bp.iloc[60] == 100

def test_all_equal_scores():
    params = {
        "threshold_mode": "quantile",
        "buy_quantile_bp": 8000,
        "sell_quantile_bp": 4000,
        "quantile_warmup_observations": 60,
        "quantile_method": "nearest_rank"
    }
    policy = ScoreThresholdPolicy(params)
    scores = pd.Series([50.0] * 61)
    result = policy.evaluate(scores)
    assert result.buy_threshold_score_bp.iloc[60] == 5000
    assert result.sell_threshold_score_bp.iloc[60] == 5000
    assert bool(result.buy_candidate.iloc[60]) is True
    assert bool(result.sell_candidate.iloc[60]) is True

def test_nan_handling():
    params = {
        "threshold_mode": "quantile",
        "buy_quantile_bp": 8000,
        "sell_quantile_bp": 2000,
        "quantile_warmup_observations": 60,
        "quantile_method": "nearest_rank"
    }
    policy = ScoreThresholdPolicy(params)
    scores = pd.Series([10.0] * 30 + [np.nan] + [20.0] * 30 + [40.0])
    result = policy.evaluate(scores)
    
    assert not result.warmup_ready.iloc[:61].any()
    assert result.warmup_ready.iloc[61]
    assert result.buy_threshold_score_bp.iloc[61] == 2000
    assert result.sell_threshold_score_bp.iloc[61] == 1000
