import pytest

from data_module.fubon_shadow_authorization import FubonShadowComputationAuthorization


def test_fubon_shadow_authorization_defaults_and_validation() -> None:
    auth = FubonShadowComputationAuthorization()
    assert auth.formal_decision_influence_allowed is False
    assert auth.formal_evidence_credit_authorized is False
    assert auth.formal_oos_allowed is False
    assert auth.production_blend_alpha_bp == 0
    assert auth.rule_only_formal_path is True
    assert auth.content_hash.startswith("sha256:")


def test_fubon_shadow_authorization_rejects_unsafe_overrides() -> None:
    with pytest.raises(ValueError, match="formal_decision_influence_allowed"):
        FubonShadowComputationAuthorization.from_dict({"formal_decision_influence_allowed": True})

    with pytest.raises(ValueError, match="formal_evidence_credit_authorized"):
        FubonShadowComputationAuthorization.from_dict({"formal_evidence_credit_authorized": True})

    with pytest.raises(ValueError, match="production_blend_alpha_bp"):
        FubonShadowComputationAuthorization.from_dict({"production_blend_alpha_bp": 100})


def test_fubon_shadow_authorization_json_roundtrip() -> None:
    auth = FubonShadowComputationAuthorization(
        authorization_revision_id="rev-test-123",
        authorized_at="2026-07-26T12:00:00+00:00",
    )
    d = auth.to_dict()
    restored = FubonShadowComputationAuthorization.from_dict(d)
    assert restored.authorization_revision_id == "rev-test-123"
    assert restored.content_hash == auth.content_hash


def test_fubon_shadow_authorization_rejects_string_boolean_and_hash_tamper() -> None:
    with pytest.raises(ValueError, match="historical_pit_allowed must be a boolean"):
        FubonShadowComputationAuthorization.from_dict(
            {"historical_pit_allowed": "false"}
        )

    payload = FubonShadowComputationAuthorization().to_dict()
    payload["owner_role"] = "tampered"
    with pytest.raises(ValueError, match="content_hash mismatch"):
        FubonShadowComputationAuthorization.from_dict(payload)
