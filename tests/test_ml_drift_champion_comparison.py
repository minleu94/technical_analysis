import numpy as np

from ml_module.drift_champion_comparison import (
    ChampionComparisonRow,
    MLChampionComparisonService,
    MLFeatureDriftService,
)


def test_feature_drift_uses_baseline_bins_and_flags_large_shift() -> None:
    baseline = np.linspace(0, 1, 100)
    stable = baseline.copy()
    shifted = np.linspace(3, 4, 100)

    stable_result = MLFeatureDriftService().compare("score", baseline, stable)
    shifted_result = MLFeatureDriftService().compare("score", baseline, shifted)

    assert stable_result.psi < 0.01
    assert stable_result.status == "stable"
    assert shifted_result.psi > 0.25
    assert shifted_result.status == "major_drift"
    assert shifted_result.retrain_automatically is False


def test_challenger_comparison_uses_same_matured_sample_set() -> None:
    rows = tuple(
        ChampionComparisonRow(
            sample_id=f"s{i}",
            actual_return_bp=100 if i < 3 else -100,
            actual_downside=0 if i < 3 else 1,
            champion_score=6 - i,
            challenger_score=6 - i,
            challenger_return_prediction_bp=100 if i < 3 else -100,
            challenger_downside_probability=0.1 if i < 3 else 0.9,
        )
        for i in range(6)
    )

    result = MLChampionComparisonService().compare(rows=rows, k=3)

    assert result.sample_count == 6
    assert result.champion_precision_at_k_bp == 10000
    assert result.challenger_precision_at_k_bp == 10000
    assert result.challenger_return_mae_bp == 0
    assert result.challenger_downside_brier_bp == 100
    assert result.auto_promotion_allowed is False


def test_duplicate_sample_ids_are_rejected() -> None:
    row = ChampionComparisonRow("same", 100, 0, 1.0, 1.0, 100.0, 0.1)
    try:
        MLChampionComparisonService().compare(rows=(row, row), k=1)
    except ValueError as exc:
        assert "sample_id" in str(exc)
    else:
        raise AssertionError("duplicate comparison samples should fail")


def test_comparison_requires_positive_k_within_sample_count() -> None:
    row = ChampionComparisonRow("s", 100, 0, 1.0, 1.0, 100.0, 0.1)
    try:
        MLChampionComparisonService().compare(rows=(row,), k=2)
    except ValueError as exc:
        assert "k" in str(exc)
    else:
        raise AssertionError("oversized k should fail")
