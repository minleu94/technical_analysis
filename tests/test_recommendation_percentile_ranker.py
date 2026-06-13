import pytest
from decision_module.recommendation_percentile_ranker import calculate_score_percentiles

def test_percentiles_use_empirical_cdf_and_keep_ties_equal():
    result = calculate_score_percentiles({
        "1101": 5000,
        "1102": 7000,
        "1103": 7000,
        "1104": 9000,
    })
    assert result["1101"] == 2500
    assert result["1102"] == 7500
    assert result["1103"] == 7500
    assert result["1104"] == 10000

def test_input_order_does_not_affect_percentiles():
    data1 = {"A": 1000, "B": 2000, "C": 3000}
    data2 = {"C": 3000, "A": 1000, "B": 2000}
    assert calculate_score_percentiles(data1) == calculate_score_percentiles(data2)

def test_empty_universe_returns_empty_dict():
    assert calculate_score_percentiles({}) == {}

def test_out_of_bound_scores_raise_value_error():
    with pytest.raises(ValueError, match="score must be between 0 and 10000"):
        calculate_score_percentiles({"A": -1})
    with pytest.raises(ValueError, match="score must be between 0 and 10000"):
        calculate_score_percentiles({"A": 10001})
