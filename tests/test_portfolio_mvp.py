from pathlib import Path

import pytest

from app_module.journal_service import JournalService
from app_module.portfolio_service import PortfolioService
from data_module.config import TWStockConfig
from portfolio_module import PortfolioValidationError, Trade, rebuild_positions


def make_trade(
    trade_id,
    side,
    quantity,
    price,
    trade_date="2026-01-02",
    stock_code="2330",
):
    return Trade(
        trade_id=trade_id,
        portfolio_id="default",
        stock_code=stock_code,
        stock_name="TSMC",
        side=side,
        quantity=quantity,
        price=price,
        trade_date=trade_date,
        created_at=f"{trade_date}T09:00:00",
    )


def make_config(tmp_path):
    return TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="unit",
    )


def test_rebuild_positions_is_deterministic_for_add_and_reduce():
    trades = [
        make_trade("t3", "sell", 4, 130, "2026-01-04"),
        make_trade("t1", "buy", 10, 100, "2026-01-02"),
        make_trade("t2", "buy", 10, 120, "2026-01-03"),
    ]

    first = rebuild_positions(trades)
    second = rebuild_positions(list(reversed(trades)))

    assert [position.to_dict() for position in first] == [
        position.to_dict() for position in second
    ]
    assert len(first) == 1
    assert first[0].quantity == 16
    assert first[0].average_cost == 110
    assert first[0].realized_pnl == 80
    assert first[0].trade_ids == ["t1", "t2", "t3"]


def test_rebuild_rejects_sell_without_open_position():
    with pytest.raises(PortfolioValidationError):
        rebuild_positions([make_trade("t1", "sell", 1, 100)])


def test_portfolio_service_records_append_only_trades_and_derives_positions(tmp_path):
    service = PortfolioService(make_config(tmp_path))

    first_trade = service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=10,
        price=100,
        trade_date="2026-01-02",
        source_type="recommendation",
        source_id="rec_001",
        source_snapshot_hash="abc123",
        trade_id="trade_001",
    )
    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="sell",
        quantity=4,
        price=125,
        trade_date="2026-01-03",
        trade_id="trade_002",
    )

    trades_file = Path(tmp_path / "output" / "portfolio" / "trades.jsonl")
    assert trades_file.exists()
    assert len(trades_file.read_text(encoding="utf-8").strip().splitlines()) == 2

    positions = service.list_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 6
    assert positions[0].average_cost == 100
    assert positions[0].source_type == "recommendation"
    assert positions[0].source_id == "rec_001"
    assert positions[0].source_snapshot_hash == "abc123"
    assert first_trade.trade_id == "trade_001"


def test_journal_service_appends_and_filters_entries(tmp_path):
    service = JournalService(make_config(tmp_path))

    service.add_journal_entry(
        title="Entry thesis",
        body="Bought because the original recommendation still holds.",
        stock_code="2330",
        linked_type="trade",
        linked_id="trade_001",
        source_type="recommendation",
        source_id="rec_001",
        journal_id="journal_001",
    )
    service.add_journal_entry(
        title="Other",
        body="Different stock note.",
        stock_code="2317",
        journal_id="journal_002",
    )

    entries = service.list_journal_entries(stock_code="2330")
    assert len(entries) == 1
    assert entries[0].journal_id == "journal_001"
    assert entries[0].linked_id == "trade_001"


def test_portfolio_service_preserves_source_summary_on_trade_and_position(tmp_path):
    service = PortfolioService(make_config(tmp_path))

    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=10,
        price=100,
        trade_date="2026-01-02",
        source_type="recommendation_result",
        source_id="rec_001",
        source_snapshot_hash="hash001",
        source_summary={"profile_id": "aggressive_short", "total_score": 82.5},
        trade_id="trade_001",
    )

    trades = service.list_trades()
    assert trades[0].source_summary["profile_id"] == "aggressive_short"

    positions = service.list_positions()
    assert positions[0].source_type == "recommendation_result"
    assert positions[0].source_id == "rec_001"
    assert positions[0].source_snapshot_hash == "hash001"
    assert positions[0].source_summary["total_score"] == 82.5
