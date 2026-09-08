from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from io import BytesIO
from zoneinfo import ZoneInfo

import joblib
import pytest

from app_module.ml_allocation_inference_service import (
    MLAllocationInferenceService,
    _ExpertOutput,
    _expert_vector,
)
from ml_module.allocation_contracts import (
    AllocationTargets,
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
    post_freeze_shadow_decision_scope,
)
from tests.test_ml_allocation_training_service import (  # noqa: F401
    _sample,
    folds,
    samples,
    training_result,
)


_TAIPEI = ZoneInfo("Asia/Taipei")
_HASH = "sha256:" + ("a" * 64)
_POLICY_HASH = "sha256:" + ("d" * 64)


def _inference_rows(
    *,
    missing_all: bool = False,
) -> tuple[PortfolioMLDatasetRow, ...]:
    decision_date = date(2027, 1, 4)
    decision_at = datetime.combine(
        decision_date,
        time(8, 30),
        tzinfo=_TAIPEI,
    ).isoformat()
    state = CausalPortfolioState.create(
        as_of_date="2027-01-03",
        weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
        weekly_turnover_used_bp=0,
    )
    rows: list[PortfolioMLDatasetRow] = []
    for index, symbol in ((1, "2317"), (2, "2330")):
        source = _sample(index)
        features: list[PITFeatureValue] = []
        for feature in source.row.features:
            features.append(
                replace(
                    feature,
                    value_int=None if missing_all else feature.value_int,
                    event_at="2027-01-03",
                    available_at="2027-01-03T16:00:00+08:00",
                    revision_id=f"inference:{symbol}:{feature.feature_id}",
                    quality="missing" if missing_all else feature.quality,
                    observed=False if missing_all else feature.observed,
                )
            )
        rows.append(
            PortfolioMLDatasetRow(
                row_id=f"2027-01-04:{symbol}",
                decision_at=decision_at,
                symbol=symbol,
                features=tuple(features),
                missing_family_ids=("price",) if missing_all else (),
                portfolio_state=state,
                dataset_identity_hash=source.row.dataset_identity_hash,
                feature_registry_hash=source.row.feature_registry_hash,
                source_manifest_hashes=source.row.source_manifest_hashes,
                targets=None,
            )
        )
    return tuple(rows)


def _service(training_result) -> MLAllocationInferenceService:
    return MLAllocationInferenceService(
        artifact_bytes=training_result.artifact_bytes,
        expected_artifact_hash=training_result.artifact_hash,
        expected_dataset_id=training_result.dataset_id,
    )


def _research_rows() -> tuple[PortfolioMLDatasetRow, ...]:
    """建立保留實際 capture timestamp 的 target-free research rows。"""

    decision_at = "2027-01-04T18:00:00+08:00"
    with post_freeze_shadow_decision_scope():
        return tuple(
            replace(
                row,
                row_id=f"row:post-freeze-shadow:2027-01-04:{row.symbol}",
                decision_at=decision_at,
            )
            for row in _inference_rows()
        )


def _nonempty_target() -> AllocationTargets:
    weights = AllocationWeightContract(
        positions_bp=(("2317", 1_000),),
        cash_bp=9_000,
    )
    return AllocationTargets(
        decision_date="2027-01-04",
        horizon_end_date="2027-01-24",
        available_at="2027-01-25T18:00:00+08:00",
        target_weights=weights,
        delta_weights_bp=(("2317", 1_000),),
        risk_contributions_bp=(("2317", 1_000),),
        risky_budget_bp=1_000,
        cash_bp=9_000,
        rebalance_worthwhile=True,
    )


def _infer(service: MLAllocationInferenceService, rows):
    return service.infer(
        rows=rows,
        model_id="allocator-v4-test",
        universe_id="pit-universe-test",
        policy_id="balanced-v1",
        policy_hash=_POLICY_HASH,
    )


def test_artifact_hash_is_verified_before_joblib_deserialization(
    training_result,
) -> None:
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        MLAllocationInferenceService(
            artifact_bytes=training_result.artifact_bytes + b"tampered",
            expected_artifact_hash=training_result.artifact_hash,
            expected_dataset_id=training_result.dataset_id,
        )


def test_legacy_artifact_keeps_calibrated_meta_probability_input(
    training_result,
) -> None:
    service = _service(training_result)
    output = _ExpertOutput(
        expected_excess_return_bp=1,
        expected_sector_excess_return_bp=2,
        downside_probability_bp=111,
        uncalibrated_downside_probability_bp=999,
        predicted_mae_bp=3,
        predicted_mfe_bp=4,
        predicted_realized_volatility_bp=5,
        predicted_max_drawdown_bp=6,
        predicted_tail_loss_bp=7,
        fill_feasibility_probability_bp=8,
        rank_bp=9,
        missing_head_ids=(),
        neutral_fallback=False,
    )

    # 舊版 direct artifact 沒有新 metadata，parser 會保留原本的
    # calibrated meta 輸入；raw_oof 只允許明確綁定的 minimal OOC release。
    assert service._artifact.meta_probability_input == "calibrated"
    assert _expert_vector(output)[7] == 111
    assert _expert_vector(
        output,
        meta_probability_input="raw_oof",
    )[7] == 999


def test_artifact_cannot_smuggle_production_authority(training_result) -> None:
    payload = joblib.load(BytesIO(training_result.artifact_bytes))
    payload["production_action_allowed"] = True
    buffer = BytesIO()
    joblib.dump(payload, buffer, compress=0)
    tampered = buffer.getvalue()
    from hashlib import sha256

    with pytest.raises(
        ValueError,
        match="production_action_allowed must be false",
    ):
        MLAllocationInferenceService(
            artifact_bytes=tampered,
            expected_artifact_hash=f"sha256:{sha256(tampered).hexdigest()}",
            expected_dataset_id=training_result.dataset_id,
        )


def test_inference_rejects_manifest_mismatch(training_result) -> None:
    rows = _inference_rows()
    poisoned = replace(
        rows[0],
        feature_registry_hash="sha256:" + ("f" * 64),
    )
    with pytest.raises(ValueError, match="feature registry hash mismatch"):
        _infer(_service(training_result), (poisoned, rows[1]))


def test_inference_rechecks_future_feature_even_after_contract_tamper(
    training_result,
) -> None:
    rows = _inference_rows()
    poisoned_feature = rows[0].features[0]
    object.__setattr__(
        poisoned_feature,
        "available_at",
        "2027-01-04T08:31:00+08:00",
    )

    with pytest.raises(ValueError, match="future feature available_at"):
        _infer(_service(training_result), rows)


def test_research_shadow_accepts_actual_capture_but_daily_keeps_0830_gate(
    training_result,
) -> None:
    service = _service(training_result)
    rows = _research_rows()

    with pytest.raises(ValueError, match="08:30"):
        _infer(service, rows)

    result = service.infer(
        rows=rows,
        model_id="allocator-v4-test",
        universe_id="pit-universe-test",
        policy_id="balanced-v1",
        policy_hash=_POLICY_HASH,
        allow_research_shadow=True,
    )
    audit = result.audit_payload()
    assert audit["decision_at"] == "2027-01-04T18:00:00+08:00"
    assert audit["inference_readback_mode"] == "post_freeze_research_shadow"
    assert all(
        row["row_id"].startswith("row:post-freeze-shadow:")
        for row in audit["row_audits"]
    )
    assert result.proposal.formal_oos_allowed is False
    assert result.proposal.production_action_allowed is False
    assert result.proposal.production_blend_alpha_bp == 0
    assert result.proposal.broker_order_allowed is False


def test_research_shadow_rejects_targets_future_features_and_mixed_clocks(
    training_result,
) -> None:
    service = _service(training_result)
    rows = _research_rows()

    # A target-bearing row is never an inference input, even if its row id is
    # marked as a post-freeze research row.
    target = _nonempty_target()
    target_row = replace(
        _inference_rows()[0],
        row_id="row:post-freeze-shadow:2027-01-04:2317",
        targets=target,
    )
    same_clock_shadow_row = replace(
        _inference_rows()[1],
        row_id="row:post-freeze-shadow:2027-01-04:2330",
    )
    with pytest.raises(ValueError, match="must not contain supervised"):
        service.infer(
            rows=(target_row, same_clock_shadow_row),
            model_id="allocator-v4-test",
            universe_id="pit-universe-test",
            policy_id="balanced-v1",
            policy_hash=_POLICY_HASH,
            allow_research_shadow=True,
        )

    # Bypass only the row constructor's early contract check to emulate a
    # tampered persisted row; the consumer must still recheck available_at.
    future_feature = rows[0].features[0]
    object.__setattr__(
        future_feature,
        "available_at",
        "2027-01-04T18:01:00+08:00",
    )
    with pytest.raises(ValueError, match="future feature available_at"):
        service.infer(
            rows=rows,
            model_id="allocator-v4-test",
            universe_id="pit-universe-test",
            policy_id="balanced-v1",
            policy_hash=_POLICY_HASH,
            allow_research_shadow=True,
        )

    with post_freeze_shadow_decision_scope():
        mixed_rows = (
            rows[0],
            replace(
                rows[1],
                decision_at="2027-01-04T18:01:00+08:00",
            ),
        )
    with pytest.raises(ValueError, match="share one decision_at"):
        service.infer(
            rows=mixed_rows,
            model_id="allocator-v4-test",
            universe_id="pit-universe-test",
            policy_id="balanced-v1",
            policy_hash=_POLICY_HASH,
            allow_research_shadow=True,
        )


def test_missing_pack_uses_explicit_cash_only_fallback(training_result) -> None:
    result = _infer(_service(training_result), _inference_rows(missing_all=True))

    assert result.proposal.requested_weights.cash_weight_bp == 10_000
    assert result.proposal.coverage_bp == 0
    assert result.proposal.fallback_reason == "all_feature_packs_missing_cash_only"
    assert result.proposal.missing_family_ids == ("price",)
    assert all(signal.confidence_bp == 0 for signal in result.proposal.signals)
    assert all(
        set(signal.missing_head_ids)
        == {
            "expected_excess_return_bp",
            "expected_sector_excess_return_bp",
            "predicted_mae_bp",
            "predicted_mfe_bp",
            "predicted_realized_volatility_bp",
            "predicted_max_drawdown_bp",
            "predicted_tail_loss_bp",
            "downside_probability_bp",
            "fill_feasibility_probability_bp",
        }
        for signal in result.proposal.signals
    )
    assert all(
        "feature_pack_missing_neutral_fallback:price" in signal.reasons
        for signal in result.proposal.signals
    )


def test_inference_outputs_integer_conserving_proposal_and_family_weights(
    training_result,
) -> None:
    result = _infer(_service(training_result), _inference_rows())
    proposal = result.proposal

    assert len(proposal.signals) == 2
    assert {signal.stock_code for signal in proposal.signals} == {"2317", "2330"}
    assert all(
        isinstance(signal.expected_excess_return_bp, int)
        and isinstance(signal.downside_probability_bp, int)
        and isinstance(signal.predicted_mae_bp, int)
        and isinstance(signal.predicted_mfe_bp, int)
        and isinstance(signal.predicted_realized_volatility_bp, int)
        and isinstance(signal.predicted_max_drawdown_bp, int)
        and isinstance(signal.predicted_tail_loss_bp, int)
        and isinstance(signal.fill_feasibility_probability_bp, int)
        and isinstance(signal.rank_bp, int)
        and isinstance(signal.confidence_bp, int)
        for signal in proposal.signals
    )
    assert (
        sum(proposal.requested_weights.symbol_weights_bp.values())
        + proposal.requested_weights.cash_weight_bp
        == 10_000
    )
    assert sum(proposal.feature_family_weights_bp.values()) == 10_000
    assert proposal.formal_oos_allowed is False
    assert proposal.production_action_allowed is False
    assert proposal.production_blend_alpha_bp == 0
    assert proposal.broker_order_allowed is False
    audit = result.audit_payload()
    assert audit["schema_version"] == "ml-allocation-inference-audit-v3"
    for row_audit in audit["row_audits"]:
        probability_by_horizon = row_audit[
            "downside_probability_by_horizon_bp"
        ]
        assert set(probability_by_horizon) == {"5", "10", "20", "60"}
        assert all(
            isinstance(values["calibrated_downside_probability_bp"], int)
            and isinstance(
                values["uncalibrated_downside_probability_bp"],
                int,
            )
            for values in probability_by_horizon.values()
        )
        for expert_output in row_audit["base_expert_outputs"].values():
            assert isinstance(
                expert_output[
                    "uncalibrated_downside_probability_bp"
                ],
                int,
            )
            assert isinstance(expert_output["predicted_mfe_bp"], int)
            assert isinstance(
                expert_output["predicted_realized_volatility_bp"],
                int,
            )
            assert isinstance(
                expert_output["fill_feasibility_probability_bp"],
                int,
            )


def test_identical_inputs_have_identical_proposal_and_replay_hash(
    training_result,
) -> None:
    service = _service(training_result)
    rows = _inference_rows()

    first = _infer(service, rows)
    second = _infer(service, rows)

    assert first.proposal.to_dict() == second.proposal.to_dict()
    assert first.proposal_hash == second.proposal_hash
    assert first.replay_hash == second.replay_hash
    assert first.audit_json == second.audit_json
