import numpy as np

from ml_module.probability_calibration import ShadowProbabilityCalibrator


def _calibration_data() -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
    raw = np.linspace(0.05, 0.95, 40)
    labels = np.asarray([0] * 18 + [1] * 22, dtype=int)
    folds = tuple("fold-1" if index < 20 else "fold-2" for index in range(40))
    return raw, labels, folds


def test_isotonic_calibrator_returns_bounded_monotonic_probabilities() -> None:
    raw, labels, folds = _calibration_data()
    calibrator = ShadowProbabilityCalibrator(minimum_samples=20).fit(
        model_id="gate7-model",
        raw_probabilities=raw,
        labels=labels,
        fold_ids=folds,
    )

    calibrated = calibrator.predict(np.asarray([0.1, 0.5, 0.9]))
    assert np.all((calibrated >= 0) & (calibrated <= 1))
    assert np.all(np.diff(calibrated) >= 0)
    assert calibrator.method == "isotonic_oof"
    assert calibrator.shadow_only is True
    assert calibrator.production_eligible is False


def test_calibration_requires_multiple_out_of_fold_blocks() -> None:
    raw, labels, _ = _calibration_data()
    try:
        ShadowProbabilityCalibrator().fit(
            model_id="m", raw_probabilities=raw, labels=labels, fold_ids=("same",) * len(raw)
        )
    except ValueError as exc:
        assert "two out-of-fold" in str(exc)
    else:
        raise AssertionError("single-fold calibration should fail")


def test_calibration_requires_two_label_classes() -> None:
    raw, _, folds = _calibration_data()
    try:
        ShadowProbabilityCalibrator().fit(
            model_id="m", raw_probabilities=raw, labels=np.zeros(len(raw), dtype=int), fold_ids=folds
        )
    except ValueError as exc:
        assert "two classes" in str(exc)
    else:
        raise AssertionError("single-class calibration should fail")


def test_calibration_rejects_probability_outside_unit_interval() -> None:
    raw, labels, folds = _calibration_data()
    raw[0] = 1.1
    try:
        ShadowProbabilityCalibrator().fit(
            model_id="m", raw_probabilities=raw, labels=labels, fold_ids=folds
        )
    except ValueError as exc:
        assert "0..1" in str(exc)
    else:
        raise AssertionError("invalid probability should fail")
