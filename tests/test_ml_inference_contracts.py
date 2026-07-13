from dataclasses import replace

import pytest

from ml_module.inference_contracts import (
    ShadowInferenceRequest,
    ShadowInferenceResult,
    ShadowPredictionIdentity,
    prediction_id_for,
)


def _request() -> ShadowInferenceRequest:
    return ShadowInferenceRequest(
        model_id="model-1",
        dataset_id="dataset-1",
        decision_date="2025-01-03",
        feature_snapshot_hash="sha256:snapshot",
        feature_registry_hash="sha256:features",
        source_versions={"daily_prices": "v1"},
        feature_max_available_date="2025-01-02",
    )


def test_request_requires_complete_identity_and_t_minus_one_features() -> None:
    with pytest.raises(ValueError, match="model_id"):
        replace(_request(), model_id="")
    with pytest.raises(ValueError, match="T-1"):
        replace(_request(), feature_max_available_date="2025-01-03")


def test_prediction_identity_is_deterministic_and_snapshot_sensitive() -> None:
    request = _request()
    first = prediction_id_for(request, "2330")

    assert first == prediction_id_for(request, "2330")
    assert first != prediction_id_for(replace(request, feature_snapshot_hash="sha256:new"), "2330")


def test_result_is_permanently_shadow_only_and_production_blend_is_zero() -> None:
    prediction = ShadowPredictionIdentity(
        prediction_id=prediction_id_for(_request(), "2330"),
        symbol="2330",
        return_prediction_bp=125,
        ranking_score_bp=6400,
        downside_probability_bp=1800,
        uncertainty_bp=250,
    )
    result = ShadowInferenceResult.available(_request(), predictions=(prediction,))

    assert result.production_blend_alpha_bp == 0
    assert result.formal_rule_unchanged is True
    assert result.production_action_allowed is False
    with pytest.raises(ValueError, match="production_blend_alpha_bp"):
        replace(result, production_blend_alpha_bp=1)


def test_fail_closed_result_is_typed_and_contains_no_fake_prediction() -> None:
    result = ShadowInferenceResult.unavailable(_request(), blocker="artifact_hash_mismatch")

    assert result.status == "shadow_unavailable"
    assert result.predictions == ()
    assert result.blockers == ("artifact_hash_mismatch",)
