from __future__ import annotations

from pathlib import Path

import pytest

from app_module.portfolio_service import PortfolioService
from app_module.trade_import_service import TradeImportService
from data_module.config import TWStockConfig


def _write_csv(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8-sig")


def test_preview_infers_taiwan_headers_and_normalizes_values(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    _write_csv(
        path,
        "證券代號,證券名稱,買賣,股數,成交價,交易日期,手續費,稅金,備註\n"
        "2330,台積電,買入,\"1,000\",100.00,2026/08/20,143,0,first buy\n"
        "2317,鴻海,賣出,500,150,20260821,100,225,trim\n",
    )

    preview = TradeImportService().preview_csv(path)

    assert preview.ready_to_import is True
    assert preview.encoding == "utf-8-sig"
    assert len(preview.valid_rows) == 2
    assert preview.valid_rows[0].side == "buy"
    assert preview.valid_rows[0].quantity == 1000
    assert preview.valid_rows[0].trade_date == "2026-08-20"
    assert preview.valid_rows[1].side == "sell"
    assert preview.valid_rows[1].trade_date == "2026-08-21"
    assert preview.to_dict()["source_hash"].startswith("sha256:")


def test_invalid_preview_is_fail_closed_and_does_not_build_dtos(tmp_path: Path) -> None:
    path = tmp_path / "invalid.csv"
    _write_csv(
        path,
        "stock_code,side,quantity,price,trade_date\n"
        "2330,BUY,0,not-a-number,2026-08-20\n",
    )

    preview = TradeImportService().preview_csv(path)

    assert preview.ready_to_import is False
    assert preview.invalid_rows[0].errors
    with pytest.raises(ValueError, match="not ready_to_import"):
        TradeImportService().build_trade_dtos(preview)


def test_existing_id_is_reported_as_duplicate_before_commit(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    _write_csv(path, "stock_code,side,quantity,price,trade_date\n2330,buy,1000,100,2026-08-20\n")
    service = TradeImportService()
    first = service.preview_csv(path)
    duplicate = service.preview_csv(path, existing_trade_ids=(first.valid_rows[0].trade_id,))

    assert duplicate.ready_to_import is False
    assert "trade_id_already_exists" in duplicate.invalid_rows[0].errors


def test_commit_requires_confirmation_and_writes_only_after_valid_preview(tmp_path: Path) -> None:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    portfolio_service = PortfolioService(config)
    path = tmp_path / "trades.csv"
    _write_csv(path, "stock_code,side,quantity,price,trade_date\n2330,buy,1000,100,2026-08-20\n")
    service = TradeImportService()
    preview = service.preview_csv(path)

    with pytest.raises(ValueError, match="explicit confirm"):
        service.commit(preview, portfolio_service)
    assert portfolio_service.list_trades() == []

    imported = service.commit(preview, portfolio_service, confirm=True)

    assert len(imported) == 1
    assert imported[0].source_type == "broker_csv"
    assert imported[0].source_id.startswith("sha256:")
    assert [item.trade_id for item in portfolio_service.list_trades()] == [imported[0].trade_id]


def test_commit_rejects_source_changed_after_preview(tmp_path: Path) -> None:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    portfolio_service = PortfolioService(config)
    path = tmp_path / "trades.csv"
    _write_csv(path, "stock_code,side,quantity,price,trade_date\n2330,buy,1000,100,2026-08-20\n")
    service = TradeImportService()
    preview = service.preview_csv(path)
    _write_csv(path, "stock_code,side,quantity,price,trade_date\n2330,buy,1000,101,2026-08-20\n")

    with pytest.raises(ValueError, match="source changed"):
        service.commit(preview, portfolio_service, confirm=True)
    assert portfolio_service.list_trades() == []
