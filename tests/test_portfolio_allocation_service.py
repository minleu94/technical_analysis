from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from app_module.portfolio_allocation_dtos import (
    AllocationWeightContract,
    CausalPortfolioState,
    MLAllocationProposal,
    PortfolioAllocationContextRow,
    PortfolioAllocationRequestV2,
    PromotionAuthorizationReference,
)
from app_module.portfolio_allocation_service import PortfolioAllocationService
from ml_module.allocation_validation import (
    ALPHA_LANES,
    AllocationFoldEvidence,
    AllocationPromotionEvidence,
    AllocationPromotionEvaluator,
    AlphaLaneEvidence,
)
from ml_promotion_test_support import build_promotion_test_custody


def _proposal(
    weights: dict[str, int],
    cash_bp: int,
    *,
    decision_date: str = "2026-07-29",
    model_hash: str = "model-hash",
    dataset_identity_hash: str = "dataset-identity-hash",
    dataset_manifest_file_hash: str = "dataset-manifest-file-hash",
) -> MLAllocationProposal:
    return MLAllocationProposal(
        decision_date=decision_date,
        model_id="allocator-v4",
        dataset_id="dataset-v4",
        universe_id="pit-universe-v4",
        policy_id="balanced-paper-v1",
        requested_weights=AllocationWeightContract(weights, cash_bp),
        model_hash=model_hash,
        dataset_identity_hash=dataset_identity_hash,
        dataset_manifest_file_hash=dataset_manifest_file_hash,
        universe_hash="universe-hash",
        policy_hash="policy-hash",
        coverage_bp=9800,
        missing_family_ids=("flow_chip",),
        reasons=("short_history_pack_shadow",),
    )


def _context(
    stock_code: str,
    current_weight_bp: int | None,
    *,
    sector_id: str | None = "semi",
    health_state: str = "HEALTHY",
    hard_risk_reasons: tuple[str, ...] = (),
    reference_price: Decimal = Decimal("100"),
    current_shares: int | None = 0,
    median_volume_20d_shares: int | None = 200_000,
    market_data_as_of_date: str | None = "2026-07-28",
    trading_days_since_last_trade: int | None = 5,
) -> PortfolioAllocationContextRow:
    return PortfolioAllocationContextRow(
        stock_code=stock_code,
        stock_name=stock_code,
        current_weight_bp=current_weight_bp,
        sector_id=sector_id,
        health_state=health_state,
        hard_risk_reasons=hard_risk_reasons,
        reference_price=reference_price,
        current_shares=current_shares,
        median_volume_20d_shares=median_volume_20d_shares,
        market_data_as_of_date=market_data_as_of_date,
        trading_days_since_last_trade=trading_days_since_last_trade,
    )


def _promotion_evidence() -> AllocationPromotionEvidence:
    replay_hash = "sha256:" + ("a" * 64)
    folds = tuple(
        AllocationFoldEvidence(
            fold_id=f"fold-{index}",
            after_cost_excess_vs_rule_bp=10,
        )
        for index in range(1, 5)
    )
    lanes = tuple(
        AlphaLaneEvidence(
            alpha_bp=alpha_bp,
            pit_violation_count=0,
            constraint_violation_count=0,
            replay_hash_pairs=((replay_hash, replay_hash),),
            folds=folds,
            bootstrap_lower_bound_bp=0,
            calibration_ece_bp=100,
            calibrated_brier_bp=900,
            uncalibrated_brier_bp=1000,
            psi_bp=100,
            core_coverage_bp=9600,
            enriched_coverage_bp=9100,
            feasible_fill_coverage_bp=9600,
            mdd_worsening_vs_rule_bp=0,
            cvar_worsening_vs_rule_bp=0,
            weekly_turnover_bp=1000,
            turnover_increment_vs_rule_bp=100,
            shadow_observed_days=20,
        )
        for alpha_bp in ALPHA_LANES
    )
    return AllocationPromotionEvidence(
        experiment_id="release-v4-prod",
        model_id="allocator-v4",
        dataset_id="dataset-v4",
        model_artifact_hash=replay_hash,
        dataset_identity_hash=replay_hash,
        dataset_manifest_file_hash=replay_hash,
        oof_bundle_hash=replay_hash,
        shadow_evidence_hash=replay_hash,
        lanes=lanes,
    )


def _request(
    *,
    requested: dict[str, int],
    requested_cash_bp: int,
    contexts: tuple[PortfolioAllocationContextRow, ...],
    current_cash_bp: int,
    alpha_bp: int = 3500,
    capital_amount: Decimal = Decimal("1000000"),
    weekly_turnover_used_bp: int = 0,
    promotion_authorization: PromotionAuthorizationReference | None = None,
) -> PortfolioAllocationRequestV2:
    causal_state: CausalPortfolioState | None = None
    if all(context.current_weight_bp is not None for context in contexts):
        current_weights = {
            context.stock_code: context.current_weight_bp
            for context in contexts
            if context.current_weight_bp is not None
            and context.current_weight_bp > 0
        }
        if sum(current_weights.values()) + current_cash_bp == 10_000:
            causal_state = CausalPortfolioState.create(
                as_of_date="2026-07-28",
                current_weights=AllocationWeightContract(
                    current_weights,
                    current_cash_bp,
                ),
            )
    return PortfolioAllocationRequestV2(
        decision_date="2026-07-29",
        capital_amount=capital_amount,
        rule_requested_weights=AllocationWeightContract(requested, requested_cash_bp),
        ml_proposal=_proposal(requested, requested_cash_bp),
        alpha_bp=alpha_bp,
        contexts=contexts,
        current_cash_bp=current_cash_bp,
        weekly_turnover_used_bp=weekly_turnover_used_bp,
        rule_policy_hash="rule-policy-hash",
        promotion_authorization=promotion_authorization,
        causal_portfolio_state=causal_state,
    )


def test_weight_contract_rejects_non_integer_duplicate_and_non_conserving_weights() -> None:
    with pytest.raises(ValueError, match="integer"):
        AllocationWeightContract({"2330": True}, 10_000)  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="integer"):
        AllocationWeightContract({"2330": 1000.0}, 9000)  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="duplicate"):
        AllocationWeightContract(
            (("2330", 500), ("2330", 500)),  # type: ignore[arg-type]
            9000,
        )
    with pytest.raises(ValueError, match="equal 10000"):
        AllocationWeightContract({"2330": 1000}, 8999)

    assert AllocationWeightContract.cash_only().to_dict()["total_weight_bp"] == 10_000


def test_low_level_blend_cannot_self_authorize_nonzero_alpha() -> None:
    rule = AllocationWeightContract({"2317": 3333, "2330": 3333}, 3334)
    ml = AllocationWeightContract({"2317": 3333, "2330": 3334}, 3333)

    blended = PortfolioAllocationService().blend_weights(
        rule_weights=rule,
        ml_weights=ml,
        alpha_bp=5000,
    )

    assert blended == rule
    assert sum(blended.symbol_weights_bp.values()) + blended.cash_weight_bp == 10_000


def test_project_reverifies_promotion_and_atomically_falls_back_without_trust(
    tmp_path: Path,
) -> None:
    evaluator = AllocationPromotionEvaluator()
    custody = build_promotion_test_custody(
        tmp_path,
        evidence=_promotion_evidence(),
        evaluator=evaluator,
        authorized_alpha_bp=2000,
    )
    rule = AllocationWeightContract({"A": 1000}, 9000)
    ml = AllocationWeightContract({"B": 1000}, 9000)
    proposal = _proposal(
        {"B": 1000},
        9000,
        model_hash=custody.evidence.model_artifact_hash,
        dataset_identity_hash=custody.evidence.dataset_identity_hash,
        dataset_manifest_file_hash=(
            custody.evidence.dataset_manifest_file_hash
        ),
    )
    request = PortfolioAllocationRequestV2(
        decision_date="2026-07-29",
        capital_amount=Decimal("1000000"),
        rule_requested_weights=rule,
        ml_proposal=proposal,
        alpha_bp=2000,
        contexts=(
            _context("A", 0, sector_id="a"),
            _context("B", 0, sector_id="b"),
        ),
        current_cash_bp=10_000,
        rule_policy_hash="rule-policy-hash",
        promotion_authorization=custody.reference(),
        causal_portfolio_state=CausalPortfolioState.create(
            as_of_date="2026-07-28",
            current_weights=AllocationWeightContract.cash_only(),
        ),
    )

    unauthorized = PortfolioAllocationService().project(request)
    authorized = PortfolioAllocationService(
        promotion_authorization_verifier=custody.verifier,
        promotion_evaluator=evaluator,
    ).project(request)

    assert unauthorized.alpha_bp == 0
    assert unauthorized.blended_weights == rule
    assert "promotion_authority_not_configured_rule_only" in unauthorized.reasons
    assert authorized.alpha_bp == 2000
    assert dict(authorized.blended_weights.symbol_weights_bp) == {
        "A": 800,
        "B": 200,
    }
    assert authorized.blended_weights.cash_weight_bp == 9000


def test_blend_rejects_bool_float_and_unapproved_alpha() -> None:
    weights = AllocationWeightContract.cash_only()
    service = PortfolioAllocationService()

    for invalid in (True, 2000.0, 1000):
        with pytest.raises(ValueError, match="alpha_bp"):
            service.blend_weights(
                rule_weights=weights,
                ml_weights=weights,
                alpha_bp=invalid,  # type: ignore[arg-type]
            )


def test_health_and_hard_risk_cannot_be_cancelled_by_ml() -> None:
    contexts = (
        _context("WATCH", 500, health_state="WATCH", current_shares=5000),
        _context("REDUCE", 800, health_state="REDUCE_CANDIDATE", current_shares=8000),
        _context(
            "EXIT",
            1000,
            hard_risk_reasons=("price_limit_risk",),
            current_shares=1000,
        ),
    )
    result = PortfolioAllocationService().project(
        _request(
            requested={"WATCH": 1500, "REDUCE": 1200, "EXIT": 1000},
            requested_cash_bp=6300,
            contexts=contexts,
            current_cash_bp=7700,
        )
    )

    assert result.target_weights.weight_for("WATCH") == 500
    assert result.target_weights.weight_for("REDUCE") == 800
    assert result.target_weights.weight_for("EXIT") == 0
    assert result.advice_action == "EXIT_CANDIDATE"
    assert result.broker_order_allowed is False
    assert result.apply_rebalance is False


def test_joint_projection_enforces_max_positions_single_sector_and_cash_caps() -> None:
    symbols = tuple(f"S{i:02d}" for i in range(10))
    requested = {symbol: 900 for symbol in symbols}
    contexts = tuple(
        _context(
            symbol,
            0,
            sector_id="shared" if index < 4 else f"sector-{index}",
            reference_price=Decimal("10"),
            current_shares=0,
        )
        for index, symbol in enumerate(symbols)
    )

    result = PortfolioAllocationService().project(
        _request(
            requested=requested,
            requested_cash_bp=1000,
            contexts=contexts,
            current_cash_bp=10_000,
        )
    )

    positive = {
        symbol: weight
        for symbol, weight in result.target_weights.symbol_weights_bp.items()
        if weight > 0
    }
    shared_weight = sum(positive.get(symbol, 0) for symbol in symbols[:4])
    assert len(positive) <= 8
    assert max(positive.values()) <= 1500
    assert shared_weight <= 3000
    assert result.target_weights.cash_weight_bp >= 2000


def test_unknown_or_same_day_liquidity_data_blocks_new_position() -> None:
    for as_of_date in (None, "2026-07-29"):
        result = PortfolioAllocationService().project(
            _request(
                requested={"2330": 1500},
                requested_cash_bp=8500,
                contexts=(
                    _context(
                        "2330",
                        0,
                        market_data_as_of_date=as_of_date,
                        current_shares=0,
                    ),
                ),
                current_cash_bp=10_000,
            )
        )

        assert result.target_weights.weight_for("2330") == 0
        assert result.executable_weights == AllocationWeightContract.cash_only()
        assert result.advice_action == "NO_NEW_POSITION"
        assert "cash_only_fallback" in result.reasons
        assert "pit_market_data_unavailable_no_new_position" in result.rows[0].diagnostics


def test_liquidity_participation_uses_t1_twenty_day_median_volume() -> None:
    result = PortfolioAllocationService().project(
        _request(
            requested={"2330": 1500},
            requested_cash_bp=8500,
            contexts=(
                _context(
                    "2330",
                    0,
                    reference_price=Decimal("100"),
                    current_shares=0,
                    median_volume_20d_shares=20_000,
                ),
            ),
            current_cash_bp=10_000,
        )
    )

    assert result.target_weights.weight_for("2330") == 1000
    assert "liquidity_5pct_participation_cap_applied" in result.rows[0].diagnostics


def test_current_weight_unknown_is_not_treated_as_zero() -> None:
    result = PortfolioAllocationService().project(
        _request(
            requested={"2330": 1000},
            requested_cash_bp=9000,
            contexts=(_context("2330", None, current_shares=None),),
            current_cash_bp=9000,
        )
    )

    assert result.rows[0].current_weight_bp is None
    assert result.rows[0].gap_weight_bp is None
    assert result.rows[0].executable_weight_bp is None
    assert result.executable_weights is None
    assert result.advice_action == "NO_NEW_POSITION"
    assert "current_portfolio_state_incomplete_no_execution" in result.reasons


def test_causal_portfolio_state_prevents_omitted_holding_from_becoming_zero() -> None:
    state = CausalPortfolioState.create(
        as_of_date="2026-07-28",
        current_weights=AllocationWeightContract({"HIDDEN": 1000}, 9000),
    )
    request = PortfolioAllocationRequestV2(
        decision_date="2026-07-29",
        capital_amount=Decimal("1000000"),
        rule_requested_weights=AllocationWeightContract({"NEW": 1000}, 9000),
        ml_proposal=_proposal({"NEW": 1000}, 9000),
        alpha_bp=0,
        contexts=(_context("NEW", 0, sector_id="new"),),
        current_cash_bp=9000,
        causal_portfolio_state=state,
    )

    result = PortfolioAllocationService().project(request)
    hidden = next(row for row in result.rows if row.stock_code == "HIDDEN")

    assert hidden.current_weight_bp is None
    assert hidden.executable_weight_bp is None
    assert "causal_portfolio_symbol_context_missing" in hidden.diagnostics
    assert result.executable_weights is None
    assert result.advice_action == "NO_NEW_POSITION"
    assert result.causal_portfolio_state_hash == state.state_hash


def test_causal_portfolio_state_hash_is_not_self_declared() -> None:
    state = CausalPortfolioState.create(
        as_of_date="2026-07-28",
        current_weights=AllocationWeightContract({"2330": 1000}, 9000),
    )

    with pytest.raises(ValueError, match="state hash mismatch"):
        replace(state, state_hash="sha256:" + ("f" * 64))


@pytest.mark.parametrize(
    ("context_weight_bp", "request_cash_bp", "expected_diagnostic"),
    [
        (500, 9000, "causal_portfolio_context_weight_mismatch"),
        (1000, 8000, "causal_portfolio_cash_mismatch"),
    ],
)
def test_causal_portfolio_context_and_cash_mismatch_fail_closed(
    context_weight_bp: int,
    request_cash_bp: int,
    expected_diagnostic: str,
) -> None:
    state = CausalPortfolioState.create(
        as_of_date="2026-07-28",
        current_weights=AllocationWeightContract({"2330": 1000}, 9000),
    )
    request = PortfolioAllocationRequestV2(
        decision_date="2026-07-29",
        capital_amount=Decimal("1000000"),
        rule_requested_weights=AllocationWeightContract({"2330": 1000}, 9000),
        ml_proposal=_proposal({"2330": 1000}, 9000),
        alpha_bp=0,
        contexts=(_context("2330", context_weight_bp, current_shares=1000),),
        current_cash_bp=request_cash_bp,
        causal_portfolio_state=state,
    )

    result = PortfolioAllocationService().project(request)

    assert result.executable_weights is None
    assert result.advice_action == "NO_NEW_POSITION"
    assert expected_diagnostic in result.rows[0].diagnostics


def test_lot_sizing_and_buy_cost_are_decimal_and_research_only() -> None:
    contexts = (
        _context("A", 1000, sector_id="a", current_shares=1000),
        _context("B", 0, sector_id="b", current_shares=0),
    )
    result = PortfolioAllocationService().project(
        _request(
            requested={"A": 1000, "B": 1500},
            requested_cash_bp=7500,
            contexts=contexts,
            current_cash_bp=9000,
        )
    )

    row_b = next(row for row in result.rows if row.stock_code == "B")
    assert row_b.executable_shares == 1000
    assert row_b.executable_weight_bp == 1000
    assert row_b.estimated_cost == Decimal("250.00")
    assert result.post_cost_cash_amount == Decimal("799750.00")
    assert result.total_estimated_cost == Decimal("250.00")
    assert result.to_dict()["post_cost_cash_amount"] == "799750.00"
    assert result.to_dict()["cash"] == {
        "rule_requested_weight_bp": 7500,
        "ml_requested_weight_bp": 7500,
        "blended_weight_bp": 7500,
        "target_weight_bp": 7500,
        "current_weight_bp": 9000,
        "gap_weight_bp": -1500,
        "executable_weight_bp": 8000,
        "post_cost_amount": "799750.00",
    }
    assert result.to_dict()["broker_order_allowed"] is False


def test_only_net_sale_proceeds_can_fund_buy_and_post_cost_cash_keeps_floor() -> None:
    symbols = tuple("ABCDEFGH")
    current = {symbol: 1000 for symbol in symbols}
    target = dict(current)
    target["A"] = 1500
    target["B"] = 500
    contexts = tuple(
        _context(
            symbol,
            current[symbol],
            sector_id=f"sector-{symbol}",
            reference_price=Decimal("10"),
            current_shares=10_000,
        )
        for symbol in symbols
    )

    result = PortfolioAllocationService().project(
        _request(
            requested=target,
            requested_cash_bp=2000,
            contexts=contexts,
            current_cash_bp=2000,
        )
    )

    row_a = next(row for row in result.rows if row.stock_code == "A")
    row_b = next(row for row in result.rows if row.stock_code == "B")
    assert row_b.executable_weight_bp == 500
    assert row_b.estimated_cost == Decimal("275.00")
    assert row_a.executable_weight_bp == 1400
    assert row_a.estimated_cost == Decimal("100.00")
    assert result.post_cost_cash_amount == Decimal("209625.00")
    assert result.post_cost_cash_amount >= Decimal("200000.00")
    assert result.executable_weights is not None
    assert result.executable_weights.cash_weight_bp == 2100


def test_rebalance_band_cooldown_and_weekly_turnover_are_jointly_deterministic() -> None:
    contexts = (
        _context(
            "A",
            1000,
            sector_id="a",
            reference_price=Decimal("10"),
            current_shares=10_000,
        ),
        _context(
            "B",
            1000,
            sector_id="b",
            reference_price=Decimal("10"),
            current_shares=10_000,
            trading_days_since_last_trade=4,
        ),
        _context(
            "C",
            1000,
            sector_id="c",
            reference_price=Decimal("10"),
            current_shares=10_000,
        ),
    )
    result = PortfolioAllocationService().project(
        _request(
            requested={"A": 1200, "B": 1500},
            requested_cash_bp=7300,
            contexts=contexts,
            current_cash_bp=7000,
            weekly_turnover_used_bp=1500,
        )
    )

    rows = {row.stock_code: row for row in result.rows}
    assert rows["A"].executable_weight_bp == 1000
    assert "within_rebalance_band" in rows["A"].diagnostics
    assert rows["B"].executable_weight_bp == 1000
    assert "same_symbol_cooldown_active" in rows["B"].diagnostics
    assert rows["C"].executable_weight_bp == 500
    assert "weekly_turnover_cap_partial" in rows["C"].diagnostics


def test_existing_hard_cap_repair_overrides_cooldown_and_turnover_cap() -> None:
    result = PortfolioAllocationService().project(
        _request(
            requested={"A": 1500},
            requested_cash_bp=8500,
            contexts=(
                _context(
                    "A",
                    2500,
                    sector_id="a",
                    reference_price=Decimal("100"),
                    current_shares=2500,
                    trading_days_since_last_trade=0,
                ),
            ),
            current_cash_bp=7500,
            weekly_turnover_used_bp=2000,
        )
    )

    row = result.rows[0]
    assert row.target_weight_bp == 1500
    assert row.executable_weight_bp == 1500
    assert (
        "hard_constraint_repair_overrides_rebalance_controls"
        in row.diagnostics
    )
    assert result.executable_weights is not None
    assert result.executable_weights.weight_for("A") == 1500


def test_hard_exit_same_day_price_is_not_used_as_pit_execution_price() -> None:
    result = PortfolioAllocationService().project(
        _request(
            requested={},
            requested_cash_bp=10_000,
            contexts=(
                _context(
                    "EXIT",
                    1000,
                    hard_risk_reasons=("thesis_invalidated",),
                    current_shares=1000,
                    market_data_as_of_date="2026-07-29",
                ),
            ),
            current_cash_bp=9000,
        )
    )

    row = result.rows[0]
    assert row.target_weight_bp == 0
    assert row.executable_weight_bp is None
    assert "sell_pit_reference_unavailable" in row.diagnostics
    assert "hard_constraint_exit_weight_nonzero:EXIT" in row.diagnostics
    assert result.executable_weights is None
    assert result.advice_action == "EXIT_CANDIDATE"


def test_projection_is_deterministic_for_identical_inputs() -> None:
    request = _request(
        requested={"2330": 1200, "2317": 800},
        requested_cash_bp=8000,
        contexts=(
            _context("2330", 0, sector_id="semi", current_shares=0),
            _context("2317", 0, sector_id="electronics", current_shares=0),
        ),
        current_cash_bp=10_000,
    )
    service = PortfolioAllocationService()

    first = service.project(request).to_dict()
    second = service.project(request).to_dict()

    assert first == second


def test_ml_proposal_cannot_enable_broker_orders() -> None:
    with pytest.raises(ValueError, match="broker orders"):
        MLAllocationProposal(
            decision_date="2026-07-29",
            model_id="m",
            dataset_id="d",
            universe_id="u",
            policy_id="p",
            requested_weights=AllocationWeightContract.cash_only(),
            model_hash="mh",
            dataset_identity_hash="dih",
            dataset_manifest_file_hash="dmfh",
            universe_hash="uh",
            policy_hash="ph",
            coverage_bp=10_000,
            broker_order_allowed=True,
        )
