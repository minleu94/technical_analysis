from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ml_module.ooc_cross_fitted_calibration import (
    cross_fitted_binned_calibration,
)


def _calibration_counts(
    fold_count: int = 4,
) -> tuple[
    NDArray[np.int64],
    NDArray[np.int64],
    NDArray[np.int64],
    NDArray[np.int64],
]:
    counts = np.zeros((fold_count, 10_001), dtype=np.int64)
    positives = np.zeros_like(counts)
    for fold in range(fold_count):
        counts[fold, 2_000] = 20
        counts[fold, 8_000] = 20
        positives[fold, 2_000] = 2 + fold
        positives[fold, 8_000] = 12 + fold
    return counts, positives, counts.copy(), positives.copy()


def test_calibration_uses_only_prior_oof_blocks() -> None:
    counts, positives, fit_counts, fit_positives = _calibration_counts()
    result = cross_fitted_binned_calibration(
        raw_counts_by_fold=counts,
        raw_positive_counts_by_fold=positives,
        calibration_counts_by_fold=fit_counts,
        calibration_positive_counts_by_fold=fit_positives,
        fold_ids=("fold-0", "fold-1", "fold-2", "fold-3"),
    )

    assert result["cross_fitted_calibration"] is True
    assert result["production_eligible"] is False
    assert result["oof_diagnostic_only"] is True
    assert result["calibration_fold_count"] == 2
    per_fold = result["per_fold"]
    assert isinstance(per_fold, list)
    assert [item["fold_id"] for item in per_fold] == [
        "fold-2",
        "fold-3",
    ]
    assert all(
        isinstance(item["prior_oof_block_count"], int)
        and item["prior_oof_block_count"] >= 2
        for item in per_fold
    )


def test_calibration_requires_two_prior_blocks() -> None:
    counts, positives, fit_counts, fit_positives = _calibration_counts(2)
    result = cross_fitted_binned_calibration(
        raw_counts_by_fold=counts,
        raw_positive_counts_by_fold=positives,
        calibration_counts_by_fold=fit_counts,
        calibration_positive_counts_by_fold=fit_positives,
        fold_ids=("fold-0", "fold-1"),
    )

    assert result["status"] == "not_evaluable"
    assert result["cross_fitted_calibration"] is False
    assert result["production_eligible"] is False


def test_calibration_rejects_positive_count_overflow() -> None:
    counts, positives, fit_counts, fit_positives = _calibration_counts()
    positives[0, 2_000] = counts[0, 2_000] + 1
    try:
        cross_fitted_binned_calibration(
            raw_counts_by_fold=counts,
            raw_positive_counts_by_fold=positives,
            calibration_counts_by_fold=fit_counts,
            calibration_positive_counts_by_fold=fit_positives,
            fold_ids=("fold-0", "fold-1", "fold-2", "fold-3"),
        )
    except ValueError as exc:
        assert "within its count matrix" in str(exc)
    else:
        raise AssertionError("invalid positive count must be rejected")
