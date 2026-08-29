from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from app_module.paper_trade_ledger import PaperTradeFill, PaperTradeLedgerRepository
from app_module.paper_trade_reconciliation import (
    PaperTradeReconciliationService,
    render_markdown,
)
from scripts.inspect_paper_trade_reconciliation import main


_HEADER = (
    "fill_id,order_id,portfolio_id,event_date,stock_code,side,requested_quantity,"
    "filled_quantity,reference_price,fill_price,commission,tax,slippage_cost,"
    "turnover_bp,execution_gap_bp,status,source_event_id,override_reason\n"
)


def _write_csv(
    path: Path,
    *,
    requested_quantity: int = 20,
    filled_quantity: int = 20,
    event_date: str = "2026-08-27",
) -> None:
    path.write_text(
        _HEADER
        + f"fill-1,order-1,paper-main,{event_date},2330,buy,{requested_quantity},{filled_quantity},"
        "100.00,100.08,15.00,0.00,8.00,120,8,filled,broker-event-1,\n",
        encoding="utf-8-sig",
    )


def _snapshot_db(path: Path) -> None:
    repository = PaperPortfolioSnapshotRepository(path)
    repository.append(
        PaperPortfolioSnapshot(
            snapshot_id="snap-start",
            portfolio_id="paper-main",
            decision_date="2026-08-24",
            source_result_id="result-start",
            cash=Decimal("90000.00"),
            total_value=Decimal("100000.00"),
            positions=(
                PaperPortfolioPositionSnapshot(
                    stock_code="2330",
                    quantity=100,
                    mark_price=Decimal("100.00"),
                    market_value=Decimal("10000.00"),
                    weight_bp=1000,
                ),
            ),
        )
    )
    repository.append(
        PaperPortfolioSnapshot(
            snapshot_id="snap-end",
            portfolio_id="paper-main",
            decision_date="2026-08-28",
            source_result_id="result-end",
            cash=Decimal("88000.00"),
            total_value=Decimal("105000.00"),
            positions=(
                PaperPortfolioPositionSnapshot(
                    stock_code="2330",
                    quantity=120,
                    mark_price=Decimal("110.00"),
                    market_value=Decimal("13200.00"),
                    weight_bp=1257,
                ),
            ),
        )
    )


def test_reconciliation_matches_snapshot_quantity_delta_without_writing(tmp_path: Path) -> None:
    state_db = tmp_path / "paper_portfolio.sqlite"
    fills_csv = tmp_path / "fills.csv"
    _snapshot_db(state_db)
    _write_csv(fills_csv)
    before = state_db.read_bytes()

    result = PaperTradeReconciliationService(state_db_path=state_db).inspect(
        fills_csv,
        period_start="2026-08-24",
        period_end="2026-08-28",
    )

    assert result.status == "ready"
    assert result.ledger_append_allowed is True
    assert result.write_performed is False
    assert result.total_cost == Decimal("23.00")
    assert result.quantity_reconciliation[0].status == "matched"
    assert result.quantity_reconciliation[0].observed_delta == 20
    assert state_db.read_bytes() == before
    assert "外部 CSV 是唯一成交來源" in render_markdown(result)


def test_quantity_mismatch_requires_review_and_is_not_rejected_as_bad_csv(tmp_path: Path) -> None:
    state_db = tmp_path / "paper_portfolio.sqlite"
    fills_csv = tmp_path / "fills.csv"
    _snapshot_db(state_db)
    _write_csv(fills_csv, requested_quantity=15, filled_quantity=15)

    result = PaperTradeReconciliationService(state_db_path=state_db).inspect(
        fills_csv,
        period_start="2026-08-24",
        period_end="2026-08-28",
    )

    assert result.status == "needs_review"
    assert "paper_trade_quantity_reconciliation_mismatch" in result.blockers
    assert result.ledger_append_allowed is False
    assert result.quantity_reconciliation[0].expected_delta == 20
    assert result.quantity_reconciliation[0].observed_delta == 15


def test_invalid_input_and_existing_fill_collision_fail_closed(tmp_path: Path) -> None:
    state_db = tmp_path / "paper_portfolio.sqlite"
    fills_csv = tmp_path / "fills.csv"
    ledger_db = tmp_path / "paper_trade_ledger.sqlite"
    _snapshot_db(state_db)
    _write_csv(fills_csv)
    service = PaperTradeReconciliationService(
        state_db_path=state_db,
        existing_ledger_db_path=ledger_db,
    )

    invalid_csv = tmp_path / "invalid.csv"
    invalid_csv.write_text("fill_id,stock_code\nfill-1,2330\n", encoding="utf-8")
    invalid = service.inspect(invalid_csv, period_start="2026-08-24", period_end="2026-08-28")
    assert invalid.status == "rejected"
    assert "paper_trade_input_invalid" in invalid.blockers
    assert not ledger_db.exists()

    # Create an existing ledger only after the invalid-input assertion; the
    # reconciliation reader must detect a collision without appending.
    PaperTradeLedgerRepository(ledger_db).append(
        PaperTradeFill(
            fill_id="fill-1",
            order_id="old-order",
            portfolio_id="paper-main",
            event_date="2026-08-26",
            stock_code="2330",
            side="buy",
            requested_quantity=1,
            filled_quantity=1,
            reference_price=Decimal("100"),
            fill_price=Decimal("100"),
            commission=Decimal("0"),
            tax=Decimal("0"),
            slippage_cost=Decimal("0"),
            turnover_bp=1,
            execution_gap_bp=0,
            status="filled",
            source_event_id="old-event",
        )
    )
    collision = service.inspect(fills_csv, period_start="2026-08-24", period_end="2026-08-28")
    assert collision.status == "rejected"
    assert collision.existing_fill_id_collisions == ("fill-1",)
    assert "paper_trade_fill_id_collision" in collision.blockers
    assert len(PaperTradeLedgerRepository(ledger_db).list()) == 1


def test_missing_state_db_is_not_configured_and_cli_emits_json(tmp_path: Path, capsys) -> None:
    fills_csv = tmp_path / "fills.csv"
    state_db = tmp_path / "missing.sqlite"
    _write_csv(fills_csv)

    assert main(
        [
            "--input-csv",
            str(fills_csv),
            "--state-db",
            str(state_db),
            "--period-start",
            "2026-08-24",
            "--period-end",
            "2026-08-28",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "paper-trade-reconciliation.v1"
    assert payload["status"] == "not_configured"
    assert payload["write_performed"] is False
    assert payload["candidate_only"] is True


def test_derived_period_is_explicitly_review_only(tmp_path: Path) -> None:
    state_db = tmp_path / "paper_portfolio.sqlite"
    fills_csv = tmp_path / "fills.csv"
    _snapshot_db(state_db)
    _write_csv(fills_csv)

    result = PaperTradeReconciliationService(state_db_path=state_db).inspect(fills_csv)

    assert result.status == "needs_review"
    assert "period_start_derived_from_input" in result.warnings
    assert "paper_trade_period_requires_distinct_boundaries" in result.blockers
