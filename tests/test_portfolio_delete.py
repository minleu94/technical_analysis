import pytest
from pathlib import Path

from app_module.journal_service import JournalService
from app_module.portfolio_service import PortfolioService
from data_module.config import TWStockConfig
from portfolio_module import PortfolioValidationError


def make_config(tmp_path):
    return TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="unit",
    )


def test_portfolio_service_deletes_trade_and_rebuilds_correctly(tmp_path):
    service = PortfolioService(make_config(tmp_path))

    # 1. 寫入兩筆買入，一筆賣出
    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=10,
        price=100,
        trade_date="2026-01-02",
        trade_id="trade_001",
    )
    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=10,
        price=120,
        trade_date="2026-01-03",
        trade_id="trade_002",
    )
    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="sell",
        quantity=5,
        price=130,
        trade_date="2026-01-04",
        trade_id="trade_003",
    )

    # 驗證初始持倉
    positions = service.list_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 15
    assert positions[0].average_cost == 110.0

    # 2. 刪除第二筆買入交易 (trade_002)
    # 此時剩下 trade_001 (買入10) 與 trade_003 (賣出5)，持倉應為 5，均成本 100
    success = service.delete_trade("trade_002")
    assert success is True

    # 驗證持倉已重算
    positions = service.list_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 5
    assert positions[0].average_cost == 100.0

    # 驗證實體檔案已被重寫
    trades_file = Path(tmp_path / "output" / "portfolio" / "trades.jsonl")
    assert trades_file.exists()
    lines = trades_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_portfolio_service_delete_rejects_unsold_reduction(tmp_path):
    service = PortfolioService(make_config(tmp_path))

    # 寫入一買一賣
    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=10,
        price=100,
        trade_date="2026-01-02",
        trade_id="trade_001",
    )
    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="sell",
        quantity=5,
        price=120,
        trade_date="2026-01-03",
        trade_id="trade_002",
    )

    # 若刪除買入交易 trade_001，則只剩下賣出交易 trade_002，會導致庫存變為負數 (超賣)
    # 這應該會觸發 PortfolioValidationError
    with pytest.raises(PortfolioValidationError) as exc_info:
        service.delete_trade("trade_001")
    
    assert "不合法" in str(exc_info.value)

    # 確保資料庫中交易仍存在（未被重寫刪除）
    trades = service.list_trades()
    assert len(trades) == 2


def test_portfolio_service_clear_all_data(tmp_path):
    service = PortfolioService(make_config(tmp_path))
    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=10,
        price=100,
        trade_date="2026-01-02",
        trade_id="trade_001",
    )

    trades = service.list_trades()
    assert len(trades) == 1

    service.clear_all_data()
    trades = service.list_trades()
    assert len(trades) == 0


def test_journal_service_deletes_and_clears_correctly(tmp_path):
    service = JournalService(make_config(tmp_path))

    service.add_journal_entry(
        title="Note 1",
        body="Body 1",
        stock_code="2330",
        journal_id="j_001",
    )
    service.add_journal_entry(
        title="Note 2",
        body="Body 2",
        stock_code="2317",
        journal_id="j_002",
    )

    # 驗證初始加載
    entries = service.list_journal_entries()
    assert len(entries) == 2

    # 1. 刪除首個日記
    success = service.delete_journal_entry("j_001")
    assert success is True

    entries = service.list_journal_entries()
    assert len(entries) == 1
    assert entries[0].journal_id == "j_002"

    # 2. 清空日記
    service.clear_all_journals()
    entries = service.list_journal_entries()
    assert len(entries) == 0
