from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app_module.paper_trade_import_service import (
    PAPER_TRADE_IMPORT_FIELDS,
    PaperTradeImportService,
)
from app_module.paper_trade_ledger import PaperTradeLedgerRepository


_HEADER = (
    "fill_id,order_id,portfolio_id,event_date,stock_code,side,requested_quantity,"
    "filled_quantity,reference_price,fill_price,commission,tax,slippage_cost,"
    "turnover_bp,execution_gap_bp,status,source_event_id,override_reason\n"
)


def _write_csv(path: Path, rows: str) -> None:
    path.write_text(_HEADER + rows, encoding="utf-8-sig")


def _valid_row(
    *,
    fill_id: str = "fill-1",
    source_event_id: str = "broker-event-1",
    status: str = "filled",
    filled_quantity: str = "1000",
    fill_price: str = "100.08",
) -> str:
    return (
        f"{fill_id},order-1,paper-main,2026-08-27,2330,buy,1000,{filled_quantity},"
        f"100.00,{fill_price},15.00,0.00,8.00,120,8,{status},{source_event_id},\n"
    )


def test_preview_requires_complete_paper_execution_columns_and_is_read_only(tmp_path: Path) -> None:
    source = tmp_path / "paper_fills.csv"
    _write_csv(source, _valid_row())
    ledger = tmp_path / "paper_portfolio" / "paper_trade_ledger.sqlite"

    preview = PaperTradeImportService().preview_csv(source)

    assert preview.ready_to_import is True
    assert preview.encoding == "utf-8-sig"
    assert preview.source_hash
    assert preview.valid_rows[0].fill_id == "fill-1"
    assert not ledger.exists()
    assert not ledger.parent.exists()


def test_build_fills_keeps_decimal_costs_and_source_hash_trace(tmp_path: Path) -> None:
    source = tmp_path / "paper_fills.csv"
    _write_csv(source, _valid_row())
    service = PaperTradeImportService()
    preview = service.preview_csv(source)

    fills = service.build_fills(preview)

    assert len(fills) == 1
    fill = fills[0]
    assert fill.reference_price == Decimal("100.00")
    assert fill.fill_price == Decimal("100.08")
    assert fill.total_cost == Decimal("23.00")
    assert fill.source_type == "paper_trade_import"
    assert fill.source_event_id.startswith(f"paper_csv:{preview.source_hash[:16]}:")
    assert fill.research_only is True
    assert fill.broker_order_allowed is False
    assert fill.auto_rebalance_allowed is False


def test_commit_requires_confirmation_and_rechecks_source_hash(tmp_path: Path) -> None:
    source = tmp_path / "paper_fills.csv"
    ledger = tmp_path / "paper_portfolio" / "paper_trade_ledger.sqlite"
    _write_csv(source, _valid_row())
    service = PaperTradeImportService()
    preview = service.preview_csv(source)

    with pytest.raises(ValueError, match="explicit confirm"):
        service.commit(preview, ledger)
    assert not ledger.exists()

    source.write_text(_HEADER + _valid_row(fill_id="changed"), encoding="utf-8-sig")
    with pytest.raises(ValueError, match="source changed"):
        service.commit(preview, ledger, confirm=True)
    assert not ledger.exists()


def test_confirm_commit_appends_atomic_batch(tmp_path: Path) -> None:
    source = tmp_path / "paper_fills.csv"
    ledger = tmp_path / "paper_portfolio" / "paper_trade_ledger.sqlite"
    _write_csv(source, _valid_row() + _valid_row(fill_id="fill-2", source_event_id="broker-event-2"))
    service = PaperTradeImportService()
    preview = service.preview_csv(source)

    fills = service.commit(preview, ledger, confirm=True)

    assert [item.fill_id for item in fills] == ["fill-1", "fill-2"]
    stored = PaperTradeLedgerRepository(ledger).list()
    assert [item.fill_id for item in stored] == ["fill-1", "fill-2"]


def test_preview_rejects_duplicate_ids_and_invalid_paper_status(tmp_path: Path) -> None:
    source = tmp_path / "paper_fills.csv"
    _write_csv(
        source,
        _valid_row() + _valid_row(fill_id="fill-1", source_event_id="broker-event-2")
        + _valid_row(fill_id="fill-3", source_event_id="broker-event-3", status="filled", filled_quantity="500"),
    )

    preview = PaperTradeImportService().preview_csv(source)

    assert preview.ready_to_import is False
    assert "fill_id_duplicate_in_file" in preview.rows[1].errors
    assert any(error.startswith("paper_fill_invalid:") for error in preview.rows[2].errors)


def test_preview_rejects_missing_required_headers_without_touching_output(tmp_path: Path) -> None:
    source = tmp_path / "incomplete.csv"
    source.write_text("fill_id,stock_code\nfill-1,2330\n", encoding="utf-8")

    with pytest.raises(ValueError, match="columns missing"):
        PaperTradeImportService().preview_csv(source)

    assert list(tmp_path.iterdir()) == [source]


def test_write_template_contains_headers_only_and_refuses_overwrite(tmp_path: Path) -> None:
    template = tmp_path / "paper_fills_template.csv"

    path = PaperTradeImportService.write_template(template)

    assert path == template.resolve()
    assert template.read_text(encoding="utf-8-sig") == ",".join(PAPER_TRADE_IMPORT_FIELDS) + "\n"
    with pytest.raises(FileExistsError, match="already exists"):
        PaperTradeImportService.write_template(template)
    assert not (tmp_path / "ledger.sqlite").exists()
