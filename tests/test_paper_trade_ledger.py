from decimal import Decimal
from pathlib import Path

import pytest

from app_module.paper_trade_ledger import (
    PaperTradeFill,
    PaperTradeLedgerRepository,
)


def _fill(
    fill_id: str = "fill-1",
    *,
    status: str = "filled",
    requested: int = 1000,
    filled: int = 1000,
    turnover_bp: int | None = 120,
    execution_gap_bp: int | None = 8,
) -> PaperTradeFill:
    return PaperTradeFill(
        fill_id=fill_id,
        order_id="order-1",
        portfolio_id="paper-main",
        event_date="2026-08-27",
        stock_code="2330",
        side="buy",
        requested_quantity=requested,
        filled_quantity=filled,
        reference_price=Decimal("100.00"),
        fill_price=Decimal("100.08") if filled else None,
        commission=Decimal("15.00"),
        tax=Decimal("0.00"),
        slippage_cost=Decimal("8.00"),
        turnover_bp=turnover_bp,
        execution_gap_bp=execution_gap_bp,
        status=status,
        source_event_id=f"event-{fill_id}",
    )


def test_paper_fill_is_decimal_and_roundtrips_append_only(tmp_path: Path) -> None:
    repository = PaperTradeLedgerRepository(tmp_path / "paper_trade.sqlite")
    fill = _fill()

    repository.append(fill)
    loaded = repository.list()

    assert loaded == (fill,)
    assert loaded[0].total_cost == Decimal("23.00")
    assert loaded[0].cash_settlement_cost == Decimal("15.00")
    assert loaded[0].gross_amount == Decimal("100080.00")
    assert loaded[0].cost_record_ready is True
    assert loaded[0].to_dict()["research_only"] is True
    # 新的現金語意是 property，不改既有 payload/hash 欄位。
    assert "cash_settlement_cost" not in loaded[0].to_dict()


def test_partial_fill_requires_partial_quantity_and_gap() -> None:
    partial = _fill(
        status="partially_filled",
        requested=1000,
        filled=400,
        execution_gap_bp=12,
    )
    assert partial.filled_quantity == 400

    with pytest.raises(ValueError, match="partially_filled status"):
        _fill(status="partially_filled", requested=1000, filled=1000)
    with pytest.raises(ValueError, match="execution_gap_bp"):
        _fill(status="filled", execution_gap_bp=None)
    assert _fill(execution_gap_bp=-12).execution_gap_bp == -12
    with pytest.raises(ValueError, match="execution_gap_bp"):
        _fill(execution_gap_bp=True)  # type: ignore[arg-type]


def test_rejected_event_has_no_fill_price_or_filled_quantity() -> None:
    rejected = PaperTradeFill(
        fill_id="fill-rejected",
        order_id="order-rejected",
        portfolio_id="paper-main",
        event_date="2026-08-27",
        stock_code="2330",
        side="buy",
        requested_quantity=1000,
        filled_quantity=0,
        reference_price=Decimal("100.00"),
        fill_price=None,
        commission=Decimal("0"),
        tax=Decimal("0"),
        slippage_cost=Decimal("0"),
        turnover_bp=0,
        execution_gap_bp=None,
        status="rejected",
        source_event_id="event-rejected",
    )
    assert rejected.gross_amount == Decimal("0.00")


def test_append_many_is_atomic_when_duplicate_fill_id_is_present(tmp_path: Path) -> None:
    repository = PaperTradeLedgerRepository(tmp_path / "paper_trade.sqlite")

    with pytest.raises(ValueError, match="already exists"):
        repository.append_many((_fill("fill-1"), _fill("fill-1")))

    assert repository.list() == ()
