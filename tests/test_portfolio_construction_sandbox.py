from __future__ import annotations

from decimal import Decimal

from app_module.portfolio_construction_dtos import (
    PortfolioConstructionCandidate,
    PortfolioConstructionRequest,
)
from app_module.portfolio_construction_service import PortfolioConstructionService
from app_module.portfolio_execution_trace_service import PortfolioExecutionTraceService


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


def test_virtual_execution_trace_marks_research_only_lifecycle() -> None:
    result = PortfolioConstructionService().construct(
        PortfolioConstructionRequest(
            decision_date="2026-07-05",
            capital_amount=Decimal("100000"),
            allocation_method="equal_weight",
            candidates=(
                PortfolioConstructionCandidate("2330", "台積電", score_bp=9000, reference_price=Decimal("100")),
            ),
            lot_size=1000,
        )
    )

    events = PortfolioExecutionTraceService().build_trace(result)

    assert [event.event_type for event in events] == ["created", "submitted", "filled"]
    assert [event.stock_code for event in events] == ["2330", "2330", "2330"]
    assert all(event.research_only for event in events)
    assert {event.source_type for event in events} == {"portfolio_sandbox"}
    assert events[-1].filled_quantity == 1000
    assert events[-1].reason_code == "research_full_fill"


def test_virtual_execution_trace_can_partial_fill_and_reject() -> None:
    result = PortfolioConstructionService().construct(
        PortfolioConstructionRequest(
            decision_date="2026-07-05",
            capital_amount=Decimal("300000"),
            allocation_method="equal_weight",
            candidates=(
                PortfolioConstructionCandidate("2330", "台積電", score_bp=9000, reference_price=Decimal("100")),
                PortfolioConstructionCandidate("2317", "鴻海", score_bp=7000, reference_price=Decimal("50")),
            ),
            lot_size=1000,
        )
    )

    events = PortfolioExecutionTraceService().build_trace(
        result,
        partial_fill_bp_by_symbol={"2330": 5000},
        rejected_symbols={"2317": "price_limit_lock"},
    )

    event_types = {(event.stock_code, event.event_type) for event in events}
    assert ("2330", "partially_filled") in event_types
    assert ("2330", "filled") in event_types
    assert ("2317", "rejected") in event_types
    rejected = [event for event in events if event.stock_code == "2317" and event.event_type == "rejected"][0]
    assert rejected.reason_code == "price_limit_lock"
    partial = [event for event in events if event.stock_code == "2330" and event.event_type == "partially_filled"][0]
    assert partial.filled_quantity == 500
