from __future__ import annotations

import pytest

from ml_module.experiment_preregistration import (
    ExperimentPreregistration,
    ExperimentPreregistrationRegistry,
    ExperimentPreregistrationValidator,
)


HASH = "sha256:" + "a" * 64


def _preregistration(**overrides: object) -> ExperimentPreregistration:
    payload: dict[str, object] = {
        "experiment_id": "experiment:rule-vs-hgb-v1",
        "generation_id": "generation:2026-07-13",
        "created_at": "2026-07-13T09:00:00+08:00",
        "hypothesis": "固定 challenger 的預先註冊研究假說",
        "champion_snapshot_family_id": "champion:rule-v1",
        "challenger_model_id": "model:hgb-core-v1",
        "k_policy_hash": HASH,
        "cost_policy_hash": HASH,
        "sample_policy_hash": HASH,
        "bootstrap_policy_hash": HASH,
        "search_budget_hash": HASH,
        "multiple_testing_policy_hash": HASH,
        "failure_policy_hash": HASH,
        "point_in_time_universe_id": "universe:tw-equity-20260713",
        "point_in_time_universe_hash": HASH,
        "dataset_manifest_hash": HASH,
        "model_manifest_hash": HASH,
        "rule_champion_content_hash": HASH,
        "oos_custody_report_id": None,
        "oos_custody_status": None,
        "minimum_material_effect_bp": None,
        "downside_noninferiority_margin_bp": None,
        "quant_validation_owner": None,
        "risk_owner": None,
        "independent_experiment_reviewer": None,
        "owner_decision_timestamp": None,
        "owner_signature_artifact_ids": (),
    }
    payload.update(overrides)
    return ExperimentPreregistration(**payload)  # type: ignore[arg-type]


def test_first_experiment_has_exact_primary_guardrail_and_non_applying_flags() -> None:
    preregistration = _preregistration()

    assert preregistration.primary_label_id == "relative_return_20d_bp"
    assert preregistration.primary_horizon_trading_days == 20
    assert preregistration.downside_guardrail_id == "downside_20d_flag"
    assert preregistration.downside_threshold_bp == -500
    assert preregistration.sensitivity_horizons_trading_days == (5, 10)
    assert preregistration.diagnostic_horizons_trading_days == (60,)
    assert preregistration.decision_time_policy == "decision_time_available_data_only"
    assert preregistration.execution_semantics == "same_point_in_time_top_k_after_cost"
    assert preregistration.metric_family == "after_cost_paired_effect_and_downside_guardrail"
    assert preregistration.production_blend_alpha_bp == 0
    assert preregistration.formal_oos_allowed is False


def test_missing_human_bp_reviewer_or_ev3_custody_is_needs_human_decision() -> None:
    decision = ExperimentPreregistrationValidator().validate(_preregistration())

    assert decision.status == "needs_human_decision"
    assert "minimum_material_effect_bp" in decision.blockers
    assert "downside_noninferiority_margin_bp" in decision.blockers
    assert "independent_experiment_reviewer" in decision.blockers
    assert "ev3_custody_result" in decision.blockers
    assert decision.formal_oos_allowed is False
    assert decision.production_blend_alpha_bp == 0


def test_validated_freeze_remains_pending_external_gate_without_unblind() -> None:
    preregistration = _preregistration(
        oos_custody_report_id="custody:2025-v1",
        oos_custody_status="custody_verified_unopened",
        minimum_material_effect_bp=25,
        downside_noninferiority_margin_bp=100,
        quant_validation_owner="quant.validation@example.test",
        risk_owner="risk.owner@example.test",
        independent_experiment_reviewer="reviewer@example.test",
        owner_decision_timestamp="2026-07-13T10:00:00+08:00",
        owner_signature_artifact_ids=("signature:quant-1", "signature:risk-1"),
        frozen=True,
    )

    decision = ExperimentPreregistrationValidator().validate(preregistration)

    assert decision.status == "preregistration_frozen_pending_external_gate"
    assert decision.formal_oos_allowed is False
    assert decision.unblind_allowed is False
    assert "formal_oos_allowed=false" in decision.blockers


def test_rejects_unblind_or_mutable_primary_policy() -> None:
    with pytest.raises(ValueError, match="unblinded_at_freeze"):
        _preregistration(unblinded_at_freeze=True)
    with pytest.raises(ValueError, match="primary_label_id"):
        _preregistration(primary_label_id="another_label")
    with pytest.raises(ValueError, match="decision_time_policy"):
        _preregistration(decision_time_policy="post_decision_recalculation")


def test_same_experiment_id_is_idempotent_only_for_identical_canonical_content() -> None:
    registry = ExperimentPreregistrationRegistry()
    first = _preregistration()

    assert registry.register(first) is first
    assert registry.register(_preregistration()) is first
    with pytest.raises(ValueError, match="new experiment_id"):
        registry.register(_preregistration(hypothesis="變更後假說"))
