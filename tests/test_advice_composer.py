from __future__ import annotations

from datetime import date
from decimal import Decimal

from app_module.advice_dtos import AdviceAction, AdviceMode
from app_module.advice_policy import AdvicePolicy
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.portfolio_construction_dtos import (
    PortfolioAllocationRow,
    PortfolioConstructionResult,
)


def _recommendation_result() -> RecommendationResultDTO:
    return RecommendationResultDTO(
        result_id="rec-20260712-001",
        result_name="平衡型推薦",
        config={
            "strategy_status": "promoted",
            "strategy_version": "v2.1",
            "execution_feasible": True,
            "risk_budget_available": True,
        },
        recommendations=[
            RecommendationDTO(
                stock_code="2330",
                stock_name="台積電",
                close_price=Decimal("1000"),
                price_change=Decimal("1.2"),
                total_score=Decimal("90"),
                indicator_score=Decimal("30"),
                pattern_score=Decimal("30"),
                volume_score=Decimal("30"),
                recommendation_reasons="技術型態完整；量能支持",
                industry="半導體",
                regime_match=True,
            )
        ],
        regime="Trend",
        created_at="2026-07-12T09:00:00",
    )


def _portfolio_result() -> PortfolioConstructionResult:
    return PortfolioConstructionResult(
        decision_date="2026-07-12",
        allocation_method="equal_weight",
        capital_amount=Decimal("1000000"),
        allocations=(
            PortfolioAllocationRow(
                stock_code="2330",
                stock_name="台積電",
                target_weight_bp=1500,
                constrained_weight_bp=1500,
                target_amount=Decimal("150000"),
                constrained_amount=Decimal("150000"),
                executable_amount=Decimal("150000"),
                reference_price=Decimal("1000"),
                executable_shares=150,
                diagnostics=("lot_size_applied",),
            ),
        ),
        residual_cash=Decimal("300000"),
    )


def test_composer_preserves_dates_and_returns_no_new_position_for_missing_evidence() -> None:
    from app_module.advice_composer import AdviceComposer

    result = AdviceComposer(AdvicePolicy()).compose(
        recommendations=(),
        portfolio_result=None,
        evidence_quality="MISSING",
        decision_date=date(2026, 7, 12),
        data_as_of_date=date(2026, 7, 12),
        mode=AdviceMode.GUIDED,
    )

    assert result.decision_date == "2026-07-12"
    assert result.data_as_of_date == "2026-07-12"
    assert result.recommendations[0].advice_action is AdviceAction.NO_NEW_POSITION
    assert result.recommendations[0].source_trace == ("RecommendationResultDTO",)
    assert result.recommendations[0].refusal_reasons == ("evidence_quality_missing",)


def test_composer_uses_injected_payloads_and_integer_bp_portfolio_gap() -> None:
    from app_module.advice_composer import AdviceComposer

    result = AdviceComposer(AdvicePolicy()).compose(
        recommendations=_recommendation_result(),
        portfolio_result=_portfolio_result(),
        evidence_quality="OBSERVED",
        evidence_warnings=("evidence_freshness_review_required",),
        decision_date=date(2026, 7, 12),
        data_as_of_date=date(2026, 7, 11),
        mode=AdviceMode.GUIDED,
        current_weights_bp={"2330": 500},
    )

    recommendation = result.recommendations[0]
    portfolio = result.portfolio_rows[0]
    assert recommendation.advice_action is AdviceAction.ADD_CANDIDATE
    assert recommendation.source_trace == ("RecommendationResultDTO", "rec-20260712-001")
    assert recommendation.decision_date == "2026-07-12"
    assert recommendation.data_as_of_date == "2026-07-11"
    assert portfolio.target_weight_bp == 1500
    assert portfolio.current_weight_bp == 500
    assert portfolio.weight_gap_bp == 1000
    assert portfolio.source_trace == ("PortfolioConstructionResult", "rec-20260712-001")
    assert result.warnings == ("evidence_freshness_review_required",)


def test_composer_keeps_missing_current_weight_as_diagnostic_without_inventing_position() -> None:
    from app_module.advice_composer import AdviceComposer

    result = AdviceComposer(AdvicePolicy()).compose(
        recommendations=_recommendation_result(),
        portfolio_result=_portfolio_result(),
        evidence_quality="OBSERVED",
        decision_date=date(2026, 7, 12),
        data_as_of_date=date(2026, 7, 12),
        mode=AdviceMode.GUIDED,
    )

    portfolio = result.portfolio_rows[0]
    assert portfolio.current_weight_bp == 0
    assert portfolio.weight_gap_bp == 1500
    assert portfolio.diagnostics == ("lot_size_applied", "current_weight_missing")
