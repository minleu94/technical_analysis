import numpy as np

from ml_module.boosted_challengers import BoostedShadowChallengerTrainer


def _data() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.asarray([[index, index % 3] for index in range(40)], dtype=float)
    returns = np.asarray([index * 10 - 150 for index in range(40)], dtype=float)
    downside = np.asarray([1 if value < 0 else 0 for value in returns], dtype=int)
    return x, returns, downside


def test_trainer_builds_regression_ranking_and_downside_challengers() -> None:
    x, returns, downside = _data()
    bundle = BoostedShadowChallengerTrainer(random_state=7).fit(
        dataset_id="dataset-v1",
        feature_names=("score_bp", "regime_code"),
        x=x,
        return_target_bp=returns,
        downside_target=downside,
    )

    prediction = bundle.predict(x[:3])
    assert prediction.return_prediction_bp.shape == (3,)
    assert prediction.ranking_score.shape == (3,)
    assert prediction.downside_probability.shape == (3,)
    assert np.all((prediction.downside_probability >= 0) & (prediction.downside_probability <= 1))
    assert bundle.model_family == "hist_gradient_boosting"
    assert bundle.shadow_only is True
    assert bundle.production_eligible is False


def test_training_is_deterministic_for_same_config() -> None:
    x, returns, downside = _data()
    trainer = BoostedShadowChallengerTrainer(random_state=11)
    first = trainer.fit(
        dataset_id="d", feature_names=("a", "b"), x=x, return_target_bp=returns, downside_target=downside
    )
    second = trainer.fit(
        dataset_id="d", feature_names=("a", "b"), x=x, return_target_bp=returns, downside_target=downside
    )

    assert first.model_id == second.model_id
    np.testing.assert_allclose(first.predict(x).return_prediction_bp, second.predict(x).return_prediction_bp)


def test_trainer_rejects_single_class_downside_target() -> None:
    x, returns, _ = _data()
    try:
        BoostedShadowChallengerTrainer().fit(
            dataset_id="d",
            feature_names=("a", "b"),
            x=x,
            return_target_bp=returns,
            downside_target=np.zeros(len(x), dtype=int),
        )
    except ValueError as exc:
        assert "two classes" in str(exc)
    else:
        raise AssertionError("single-class classifier training should fail")


def test_feature_count_mismatch_is_rejected() -> None:
    x, returns, downside = _data()
    try:
        BoostedShadowChallengerTrainer().fit(
            dataset_id="d",
            feature_names=("only_one",),
            x=x,
            return_target_bp=returns,
            downside_target=downside,
        )
    except ValueError as exc:
        assert "feature_names" in str(exc)
    else:
        raise AssertionError("feature mismatch should fail")
