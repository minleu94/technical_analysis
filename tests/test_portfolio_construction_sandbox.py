from __future__ import annotations

from decimal import Decimal

from app_module.portfolio_construction_dtos import (
    PortfolioConstructionCandidate,
    PortfolioConstructionRequest,
)
from app_module.portfolio_construction_service import PortfolioConstructionService


def test_equal_weight_allocation_respects_max_weight_and_lot_sizing() -> None:
    candidates = (
        PortfolioConstructionCandidate("2330", "台積電", score_bp=9000, reference_price=Decimal("333")),
        PortfolioConstructionCandidate("2317", "鴻海", score_bp=7000, reference_price=Decimal("100")),
        PortfolioConstructionCandidate("2454", "聯發科", score_bp=6000, reference_price=Decimal("500")),
    )
    request = PortfolioConstructionRequest(
        decision_date="2026-07-05",
        capital_amount=Decimal("1000000"),
        allocation_method="equal_weight",
        candidates=candidates,
        max_position_weight_bp=4000,
        lot_size=1000,
    )

    result = PortfolioConstructionService().construct(request)

    assert result.research_basis is True
    assert result.policy == "research_only_portfolio_construction_v1"
    assert [row.stock_code for row in result.allocations] == ["2330", "2317", "2454"]
    assert all(row.constrained_weight_bp <= 4000 for row in result.allocations)
    assert result.allocations[0].target_weight_bp == 3334
    assert result.allocations[0].executable_shares == 1000
    assert result.allocations[0].executable_amount == Decimal("333000.00")
    assert result.residual_cash == Decimal("367000.00")
    assert "lot_sizing_residual_cash" in result.diagnostics
    assert "research_basis_not_trade_advice" in result.warnings


def test_score_weight_allocation_uses_score_bp_and_is_deterministic() -> None:
    candidates = (
        PortfolioConstructionCandidate("A", "A", score_bp=9000, reference_price=Decimal("100")),
        PortfolioConstructionCandidate("B", "B", score_bp=3000, reference_price=Decimal("100")),
    )
    request = PortfolioConstructionRequest(
        decision_date="2026-07-05",
        capital_amount=Decimal("120000"),
        allocation_method="score_weight",
        candidates=candidates,
    )

    result = PortfolioConstructionService().construct(request)

    assert [row.stock_code for row in result.allocations] == ["A", "B"]
    assert [row.target_weight_bp for row in result.allocations] == [7500, 2500]
    assert [row.target_amount for row in result.allocations] == [Decimal("90000.00"), Decimal("30000.00")]


def test_inverse_volatility_allocation_uses_decision_date_volatility() -> None:
    candidates = (
        PortfolioConstructionCandidate(
            "A",
            "A",
            score_bp=9000,
            reference_price=Decimal("100"),
            volatility_bp=3000,
        ),
        PortfolioConstructionCandidate(
            "B",
            "B",
            score_bp=3000,
            reference_price=Decimal("100"),
            volatility_bp=1000,
        ),
    )
    request = PortfolioConstructionRequest(
        decision_date="2026-07-05",
        capital_amount=Decimal("120000"),
        allocation_method="inverse_volatility",
        candidates=candidates,
    )

    result = PortfolioConstructionService().construct(request)

    assert [row.stock_code for row in result.allocations] == ["A", "B"]
    assert [row.target_weight_bp for row in result.allocations] == [2500, 7500]
    assert result.diagnostics == ()


def test_inverse_volatility_skips_missing_volatility_without_backfilling() -> None:
    candidates = (
        PortfolioConstructionCandidate("A", "A", score_bp=9000, reference_price=Decimal("100"), volatility_bp=None),
        PortfolioConstructionCandidate("B", "B", score_bp=3000, reference_price=Decimal("100"), volatility_bp=1000),
    )
    request = PortfolioConstructionRequest(
        decision_date="2026-07-05",
        capital_amount=Decimal("120000"),
        allocation_method="inverse_volatility",
        candidates=candidates,
    )

    result = PortfolioConstructionService().construct(request)

    assert [row.stock_code for row in result.allocations] == ["B"]
    assert result.allocations[0].target_weight_bp == 10000
    assert "skipped_missing_volatility:A" in result.diagnostics
