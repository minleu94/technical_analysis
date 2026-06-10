import pytest

from app_module.portfolio_service import PortfolioService
from data_module.config import TWStockConfig
from portfolio_module import PortfolioValidationError, Trade, rebuild_positions


def make_config(tmp_path):
    return TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="unit",
    )


def test_rebuild_positions_quantizes_average_cost_to_cents():
    positions = rebuild_positions(
        [
            Trade(
                trade_id="buy-1",
                portfolio_id="default",
                stock_code="2330",
                stock_name="台積電",
                side="buy",
                quantity=1000,
                price=10.10,
                trade_date="2026-06-01",
            ),
            Trade(
                trade_id="buy-2",
                portfolio_id="default",
                stock_code="2330",
                stock_name="台積電",
                side="buy",
                quantity=1000,
                price=10.20,
                trade_date="2026-06-02",
            ),
        ]
    )

    assert positions[0].average_cost == 10.15


def test_rebuild_positions_quantizes_realized_pnl_to_cents():
    positions = rebuild_positions(
        [
            Trade(
                trade_id="buy-1",
                portfolio_id="default",
                stock_code="2330",
                stock_name="台積電",
                side="buy",
                quantity=1000,
                price=10.10,
                trade_date="2026-06-01",
            ),
            Trade(
                trade_id="sell-1",
                portfolio_id="default",
                stock_code="2330",
                stock_name="台積電",
                side="sell",
                quantity=500,
                price=10.30,
                trade_date="2026-06-02",
            ),
        ]
    )

    assert positions[0].realized_pnl == 100.00


def test_rebuild_positions_rejects_fractional_share_quantity():
    with pytest.raises(PortfolioValidationError, match="quantity must be whole shares"):
        rebuild_positions(
            [
                Trade(
                    trade_id="buy-1",
                    portfolio_id="default",
                    stock_code="2330",
                    stock_name="台積電",
                    side="buy",
                    quantity=1000.5,
                    price=10.10,
                    trade_date="2026-06-01",
                )
            ]
        )


def test_portfolio_service_summary_quantizes_realized_pnl_sum(tmp_path):
    service = PortfolioService(make_config(tmp_path))
    service.record_trade("2330", "TSMC", "buy", 2, 10.10, "2026-06-01", trade_id="a-buy")
    service.record_trade("2330", "TSMC", "sell", 1, 10.20, "2026-06-02", trade_id="a-sell")
    service.record_trade("2317", "Hon Hai", "buy", 2, 20.10, "2026-06-01", trade_id="b-buy")
    service.record_trade("2317", "Hon Hai", "sell", 1, 20.30, "2026-06-02", trade_id="b-sell")

    portfolio = service.get_portfolio()

    assert portfolio.total_realized_pnl == 0.30
