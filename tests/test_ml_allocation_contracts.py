from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from ml_module.allocation_contracts import (
    AllocationTargets,
    AllocationWeightContract,
    CausalPortfolioState,
    MLAllocationPrediction,
    MLAllocationProposal,
    PITFeatureValue,
    PortfolioMLDatasetRow,
)


_HASH = "sha256:" + "a" * 64
_OTHER_HASH = "sha256:" + "b" * 64


def _feature(**overrides: object) -> PITFeatureValue:
    values: dict[str, object] = {
        "feature_id": "return_20d_bp",
        "family_id": "price_liquidity_technical",
        "source_id": "sqlite.daily_prices",
        "value_int": 125,
        "scale": 1,
        "event_at": "2026-01-02",
        "available_at": "2026-01-02",
        "revision_id": "daily_prices:2026-01-02:v1",
        "quality": "observed",
        "content_hash": _HASH,
        "observed": True,
    }
    values.update(overrides)
    return PITFeatureValue(**values)  # type: ignore[arg-type]


def _state() -> CausalPortfolioState:
    return CausalPortfolioState.create(
        as_of_date="2026-01-02",
        weights=AllocationWeightContract(
            positions_bp=(("2330", 500),),
            cash_bp=9500,
        ),
        weekly_turnover_used_bp=0,
    )


def _targets(**overrides: object) -> AllocationTargets:
    values: dict[str, object] = {
        "decision_date": "2026-01-03",
        "horizon_end_date": "2026-02-02",
        "available_at": "2026-02-02",
        "target_weights": AllocationWeightContract(
            positions_bp=(("2330", 1000),),
            cash_bp=9000,
        ),
        "delta_weights_bp": (("2330", 500),),
        "risk_contributions_bp": (("2330", 1000),),
        "risky_budget_bp": 1000,
        "cash_bp": 9000,
        "rebalance_worthwhile": True,
    }
    values.update(overrides)
    return AllocationTargets(**values)  # type: ignore[arg-type]


def test_weight_contract_is_frozen_integer_only_and_conservative() -> None:
    weights = AllocationWeightContract(
        positions_bp=(("2330", 1500), ("2317", 1000)),
        cash_bp=7500,
    )

    assert weights.invested_bp == 2500
    assert dict(weights.as_mapping()) == {"2330": 1500, "2317": 1000}
    with pytest.raises(FrozenInstanceError):
        weights.cash_bp = 7000  # type: ignore[misc]
    with pytest.raises(TypeError, match="integer"):
        AllocationWeightContract(
            positions_bp=(("2330", 1500.0),),  # type: ignore[arg-type]
            cash_bp=8500,
        )
    with pytest.raises(ValueError, match="equal 10000"):
        AllocationWeightContract(positions_bp=(("2330", 1500),), cash_bp=8499)


def test_pit_feature_keeps_missing_distinct_from_zero_and_rejects_float() -> None:
    missing = _feature(
        value_int=None,
        quality="missing",
        observed=False,
    )

    assert missing.value_int is None
    with pytest.raises(TypeError, match="value_int"):
        _feature(value_int=1.5)
    with pytest.raises(ValueError, match="requires value_int"):
        _feature(value_int=None)
    with pytest.raises(ValueError, match="must be missing"):
        _feature(value_int=0, quality="missing", observed=False)


def test_dataset_row_enforces_t_minus_one_feature_and_portfolio_state() -> None:
    row = PortfolioMLDatasetRow(
        row_id="2026-01-03:2330",
        decision_at="2026-01-03T08:30:00+08:00",
        symbol="2330",
        features=(_feature(),),
        missing_family_ids=(),
        portfolio_state=_state(),
        dataset_identity_hash=_HASH,
        feature_registry_hash=_OTHER_HASH,
        source_manifest_hashes=(("sqlite.daily_prices", _HASH),),
        targets=_targets(),
    )

    assert row.targets is not None
    assert row.targets.delta_weight_bp["2330"] == 500
    with pytest.raises(ValueError, match="available_at.*decision_at"):
        replace(
            row,
            features=(_feature(available_at="2026-01-03"),),
        )
    with pytest.raises(ValueError, match="T-1"):
        replace(
            row,
            portfolio_state=CausalPortfolioState.create(
                as_of_date="2026-01-03",
                weights=_state().weights,
                weekly_turnover_used_bp=0,
            ),
        )


def test_causal_portfolio_state_recomputes_canonical_content_hash() -> None:
    state = _state()

    assert state.state_hash == CausalPortfolioState.compute_state_hash(
        as_of_date=state.as_of_date,
        weights=state.weights,
        weekly_turnover_used_bp=state.weekly_turnover_used_bp,
    )
    with pytest.raises(ValueError, match="state hash mismatch"):
        replace(state, weekly_turnover_used_bp=1)


def test_dataset_row_rejects_future_realized_event_even_if_available_at_is_old() -> None:
    with pytest.raises(ValueError, match="event_at.*decision_at"):
        PortfolioMLDatasetRow(
            row_id="2026-01-03:2330:poison",
            decision_at="2026-01-03T08:30:00+08:00",
            symbol="2330",
            features=(
                _feature(
                    event_at="2099-01-01",
                    available_at="2020-01-01",
                ),
            ),
            missing_family_ids=(),
            portfolio_state=_state(),
            dataset_identity_hash=_HASH,
            feature_registry_hash=_OTHER_HASH,
            source_manifest_hashes=(("sqlite.daily_prices", _HASH),),
        )


def test_dataset_row_allows_explicitly_announced_future_corporate_event() -> None:
    feature = _feature(
        feature_id="cash_dividend_effective_event",
        family_id="corporate_microstructure",
        source_id="official.corporate_action",
        event_at="2026-02-01",
        available_at="2026-01-02T16:00:00+08:00",
        event_time_semantics="announced_future_event",
    )
    row = PortfolioMLDatasetRow(
        row_id="2026-01-03:2330:announced",
        decision_at="2026-01-03T08:30:00+08:00",
        symbol="2330",
        features=(feature,),
        missing_family_ids=(),
        portfolio_state=_state(),
        dataset_identity_hash=_HASH,
        feature_registry_hash=_OTHER_HASH,
        source_manifest_hashes=(("official.corporate_action", _HASH),),
    )

    assert row.features[0].event_time_semantics == "announced_future_event"


def test_announced_future_event_cannot_be_used_as_generic_bypass() -> None:
    with pytest.raises(ValueError, match="restricted to corporate_microstructure"):
        _feature(event_time_semantics="announced_future_event")


def test_dataset_row_rejects_target_delta_not_derived_from_causal_state() -> None:
    with pytest.raises(ValueError, match="delta weights"):
        PortfolioMLDatasetRow(
            row_id="2026-01-03:2330",
            decision_at="2026-01-03T08:30:00+08:00",
            symbol="2330",
            features=(_feature(),),
            missing_family_ids=(),
            portfolio_state=_state(),
            dataset_identity_hash=_HASH,
            feature_registry_hash=_OTHER_HASH,
            source_manifest_hashes=(("sqlite.daily_prices", _HASH),),
            targets=_targets(delta_weights_bp=(("2330", 400),)),
        )


def test_dataset_row_requires_missing_masks_and_source_lineage() -> None:
    missing_feature = _feature(
        value_int=None,
        quality="missing",
        observed=False,
    )
    common = {
        "row_id": "2026-01-03:2330",
        "decision_at": "2026-01-03T08:30:00+08:00",
        "symbol": "2330",
        "features": (missing_feature,),
        "portfolio_state": _state(),
        "dataset_identity_hash": _HASH,
        "feature_registry_hash": _OTHER_HASH,
        "source_manifest_hashes": (("sqlite.daily_prices", _HASH),),
    }
    with pytest.raises(ValueError, match="missing-family masks"):
        PortfolioMLDatasetRow(
            **common,
            missing_family_ids=(),
        )
    with pytest.raises(ValueError, match="source manifest"):
        PortfolioMLDatasetRow(
            **{
                **common,
                "source_manifest_hashes": (("different.source", _HASH),),
            },
            missing_family_ids=("price_liquidity_technical",),
        )


def test_allocation_targets_enforce_budget_and_maturity() -> None:
    targets = _targets()

    assert targets.target_weight_bp["2330"] == 1000
    assert targets.risk_contribution_bp["2330"] == 1000
    assert targets.is_fit_eligible(training_as_of="2026-02-02") is True
    assert targets.is_fit_eligible(training_as_of="2026-02-01") is False
    with pytest.raises(ValueError, match="risky_budget_bp"):
        _targets(risky_budget_bp=999)
    with pytest.raises(ValueError, match="risk contributions"):
        _targets(risk_contributions_bp=(("2330", 999),))


def test_ml_proposal_is_decimal_first_and_does_not_authorize_production() -> None:
    prediction = MLAllocationPrediction(
        prediction_id="prediction:2330",
        decision_at="2026-01-03T08:30:00+08:00",
        symbol="2330",
        expected_excess_return_bp=125,
        downside_probability_bp=1800,
        predicted_mae_bp=300,
        rank_bp=9000,
        confidence_bp=8000,
        feature_snapshot_hash=_HASH,
    )
    proposal = MLAllocationProposal(
        proposal_id="proposal:2026-01-03",
        decision_at="2026-01-03T08:30:00+08:00",
        model_id="model:v4",
        dataset_id="dataset:v4",
        universe_id="pit-universe:v4",
        policy_id="balanced:v1",
        model_artifact_hash=_HASH,
        dataset_identity_hash=_OTHER_HASH,
        dataset_manifest_file_hash=_HASH,
        policy_hash=_HASH,
        requested_weights=AllocationWeightContract(
            positions_bp=(("2330", 1500),),
            cash_bp=8500,
        ),
        predictions=(prediction,),
        feature_family_weights_bp=(
            ("price_liquidity_technical", 6000),
            ("fundamental_growth_quality", 4000),
        ),
        estimated_turnover_bp=1500,
        estimated_transaction_cost=Decimal("375.00"),
        calibration_ece_bp=300,
        drift_psi_bp=1200,
        coverage_bp=9800,
    )

    assert proposal.requested_weights.cash_bp == 8500
    assert not hasattr(proposal, "formal_oos_allowed")
    assert not hasattr(proposal, "production_blend_alpha_bp")
    with pytest.raises(TypeError, match="Decimal"):
        replace(
            proposal,
            estimated_transaction_cost=375.0,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="family weights"):
        replace(
            proposal,
            feature_family_weights_bp=(
                ("price_liquidity_technical", 5999),
                ("fundamental_growth_quality", 4000),
            ),
        )
