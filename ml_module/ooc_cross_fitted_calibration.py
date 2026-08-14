"""OOC classifier calibration helpers using integer basis points.

這個模組只處理 OOC 的 shadow calibration 診斷。它不授予 production
eligibility，也不把 calibration 結果直接寫回模型權重；所有 probability
輸入均已量化為 0..10,000 bp，讓 calibration gate 不需要新增裸 float。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Sequence, cast

import numpy as np
from numpy.typing import NDArray


PROBABILITY_MAX_BP = 10_000
CALIBRATION_BIN_COUNT = 10
MINIMUM_PRIOR_BLOCKS = 2


def cross_fitted_binned_calibration(
    *,
    raw_counts_by_fold: NDArray[np.int64],
    raw_positive_counts_by_fold: NDArray[np.int64],
    calibration_counts_by_fold: NDArray[np.int64],
    calibration_positive_counts_by_fold: NDArray[np.int64],
    fold_ids: Sequence[str],
    minimum_prior_blocks: int = MINIMUM_PRIOR_BLOCKS,
) -> dict[str, object]:
    """以 expanding prior OOF blocks 評估整數 bp isotonic calibration。

    ``calibration_*`` 只應包含在下一個 outer fold 開始前已成熟的 label。
    對每個 target fold，calibrator 僅使用更早的 blocks；target fold 自身
    的 label 永遠不會參與該 fold 的 calibration fit。這個函式只產生
    shadow 診斷與 conservative metrics，不會回傳可直接授權 production
    inference 的 calibrator。
    """

    raw_counts = _validated_count_matrix(
        raw_counts_by_fold,
        "raw_counts_by_fold",
    )
    raw_positive = _validated_positive_matrix(
        raw_positive_counts_by_fold,
        raw_counts,
        "raw_positive_counts_by_fold",
    )
    calibration_counts = _validated_count_matrix(
        calibration_counts_by_fold,
        "calibration_counts_by_fold",
    )
    calibration_positive = _validated_positive_matrix(
        calibration_positive_counts_by_fold,
        calibration_counts,
        "calibration_positive_counts_by_fold",
    )
    if (
        raw_counts.shape != raw_positive.shape
        or raw_counts.shape != calibration_counts.shape
        or raw_counts.shape != calibration_positive.shape
    ):
        raise ValueError("calibration count matrices must have equal shapes")
    if len(fold_ids) != raw_counts.shape[0]:
        raise ValueError("fold_ids must match calibration fold count")
    if (
        isinstance(minimum_prior_blocks, bool)
        or not isinstance(minimum_prior_blocks, int)
        or minimum_prior_blocks < 2
    ):
        raise ValueError("minimum_prior_blocks must be an integer >= 2")

    per_fold: list[dict[str, int | str]] = []
    for target_index in range(raw_counts.shape[0]):
        prior_block_count = sum(
            int(np.sum(calibration_counts[index])) > 0
            for index in range(target_index)
        )
        if prior_block_count < minimum_prior_blocks:
            continue
        fit_counts: NDArray[np.int64] = np.asarray(
            np.sum(
                calibration_counts[:target_index],
                axis=0,
                dtype=np.int64,
            ),
            dtype=np.int64,
        )
        fit_positive: NDArray[np.int64] = np.asarray(
            np.sum(
                calibration_positive[:target_index],
                axis=0,
                dtype=np.int64,
            ),
            dtype=np.int64,
        )
        if int(np.sum(fit_positive)) == 0 or int(
            np.sum(fit_counts - fit_positive)
        ) == 0:
            continue
        mapping = _fit_isotonic_mapping_bp(fit_counts, fit_positive)
        raw_metrics = _calibration_metrics_bp(
            raw_counts[target_index],
            raw_positive[target_index],
        )
        calibrated_metrics = _calibration_metrics_bp(
            raw_counts[target_index],
            raw_positive[target_index],
            mapping,
        )
        if raw_metrics["sample_count"] == 0:
            continue
        per_fold.append(
            {
                "fold_id": str(fold_ids[target_index]),
                "prior_oof_block_count": prior_block_count,
                "sample_count": raw_metrics["sample_count"],
                "ece_bp": calibrated_metrics["ece_bp"],
                "brier_score_bp": calibrated_metrics["brier_score_bp"],
                "uncalibrated_ece_bp": raw_metrics["ece_bp"],
                "uncalibrated_brier_score_bp": raw_metrics[
                    "brier_score_bp"
                ],
            }
        )

    if not per_fold:
        return {
            "status": "not_evaluable",
            "reason": "insufficient_prior_oof_blocks_or_two_label_classes",
            "ece_bp": None,
            "brier_score_bp": None,
            "uncalibrated_ece_bp": None,
            "uncalibrated_brier_score_bp": None,
            "threshold_ece_bp": 500,
            "cross_fitted_calibration": False,
            "production_eligible": False,
            "oof_diagnostic_only": True,
            "calibration_fold_count": 0,
            "per_fold": [],
        }

    calibrated_ece = max(
        _integer_field(item["ece_bp"], "ece_bp") for item in per_fold
    )
    calibrated_brier = max(
        _integer_field(item["brier_score_bp"], "brier_score_bp")
        for item in per_fold
    )
    raw_ece = max(
        _integer_field(item["uncalibrated_ece_bp"], "uncalibrated_ece_bp")
        for item in per_fold
    )
    raw_brier = max(
        _integer_field(
            item["uncalibrated_brier_score_bp"],
            "uncalibrated_brier_score_bp",
        )
        for item in per_fold
    )
    return {
        "status": "measured_cross_fitted_oof",
        "ece_bp": calibrated_ece,
        "brier_score_bp": calibrated_brier,
        "calibrated_brier_score_bp": calibrated_brier,
        "uncalibrated_ece_bp": raw_ece,
        "uncalibrated_brier_score_bp": raw_brier,
        "threshold_ece_bp": 500,
        "cross_fitted_calibration": True,
        "production_eligible": False,
        "oof_diagnostic_only": True,
        "calibration_fold_count": len(per_fold),
        "minimum_prior_oof_block_count": min(
            _integer_field(
                item["prior_oof_block_count"],
                "prior_oof_block_count",
            )
            for item in per_fold
        ),
        "sample_count": sum(
            _integer_field(item["sample_count"], "sample_count")
            for item in per_fold
        ),
        "quality_pass": calibrated_ece <= 500
        and calibrated_brier <= raw_brier,
        "per_fold": per_fold,
    }


def _validated_count_matrix(
    value: NDArray[np.int64],
    field_name: str,
) -> NDArray[np.int64]:
    matrix = np.asarray(value, dtype=np.int64)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != PROBABILITY_MAX_BP + 1
        or np.any(matrix < 0)
    ):
        raise ValueError(
            f"{field_name} must be non-negative [fold, probability_bp]"
        )
    return matrix


def _validated_positive_matrix(
    value: NDArray[np.int64],
    counts: NDArray[np.int64],
    field_name: str,
) -> NDArray[np.int64]:
    matrix = np.asarray(value, dtype=np.int64)
    if matrix.shape != counts.shape or np.any(matrix < 0) or np.any(matrix > counts):
        raise ValueError(f"{field_name} must be within its count matrix")
    return matrix


def _fit_isotonic_mapping_bp(
    counts: NDArray[np.int64],
    positive_counts: NDArray[np.int64],
) -> NDArray[np.int64]:
    """以 weighted PAV fit isotonic mapping，輸出 0..10,000 bp。"""

    if int(np.sum(counts)) == 0:
        raise ValueError("isotonic calibration requires samples")
    blocks: list[list[int]] = []
    for probability_bp in np.flatnonzero(counts):
        index = int(probability_bp)
        blocks.append(
            [
                index,
                index,
                int(counts[index]),
                int(positive_counts[index]),
            ]
        )
        while len(blocks) >= 2:
            left = blocks[-2]
            right = blocks[-1]
            if left[3] * right[2] <= right[3] * left[2]:
                break
            blocks[-2:] = [
                [
                    left[0],
                    right[1],
                    left[2] + right[2],
                    left[3] + right[3],
                ]
            ]
    mapping = np.empty(PROBABILITY_MAX_BP + 1, dtype=np.int64)
    block_values: list[int] = []
    for start, stop, count, positive in blocks:
        value = _round_bp(positive * PROBABILITY_MAX_BP, count)
        block_values.append(value)
        mapping[start : stop + 1] = value
    for index in range(len(blocks) - 1):
        mapping[blocks[index][1] + 1 : blocks[index + 1][0]] = block_values[
            index
        ]
    mapping[: blocks[0][0]] = mapping[blocks[0][0]]
    mapping[blocks[-1][1] + 1 :] = mapping[blocks[-1][1]]
    return mapping


def _calibration_metrics_bp(
    counts: NDArray[np.int64],
    positive_counts: NDArray[np.int64],
    mapping: NDArray[np.int64] | None = None,
) -> dict[str, int]:
    total = int(np.sum(counts))
    if total == 0:
        return {"ece_bp": 0, "brier_score_bp": 0, "sample_count": 0}
    if mapping is None:
        values = np.arange(PROBABILITY_MAX_BP + 1, dtype=np.int64)
    else:
        values = np.asarray(mapping, dtype=np.int64)
        if values.shape != (PROBABILITY_MAX_BP + 1,) or np.any(
            (values < 0) | (values > PROBABILITY_MAX_BP)
        ):
            raise ValueError("calibration mapping is outside integer bp range")
    predicted_by_bin = [0] * CALIBRATION_BIN_COUNT
    observed_by_bin = [0] * CALIBRATION_BIN_COUNT
    brier_numerator = 0
    for probability_bp in np.flatnonzero(counts):
        index = int(probability_bp)
        count = int(counts[index])
        positive = int(positive_counts[index])
        value = int(values[index])
        ece_bin = min(CALIBRATION_BIN_COUNT - 1, value // 1_000)
        predicted_by_bin[ece_bin] += value * count
        observed_by_bin[ece_bin] += positive * PROBABILITY_MAX_BP
        brier_numerator += (
            value * value * (count - positive)
            + (PROBABILITY_MAX_BP - value)
            * (PROBABILITY_MAX_BP - value)
            * positive
        )
    ece_numerator = sum(
        abs(predicted_by_bin[index] - observed_by_bin[index])
        for index in range(CALIBRATION_BIN_COUNT)
    )
    return {
        "ece_bp": _round_bp(ece_numerator, total),
        "brier_score_bp": _round_bp(
            brier_numerator,
            total * PROBABILITY_MAX_BP,
        ),
        "sample_count": total,
    }


def _round_bp(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("bp ratio denominator must be positive")
    return int(
        (
            Decimal(numerator) / Decimal(denominator)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    )


def _integer_field(value: object, field_name: str) -> int:
    result = cast(int, value)
    if isinstance(result, bool) or not isinstance(result, int):
        raise TypeError(f"{field_name} must be an integer")
    return result
