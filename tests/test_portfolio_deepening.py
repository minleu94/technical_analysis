from pathlib import Path
import pytest
from decimal import Decimal

from app_module.portfolio_service import PortfolioService
from app_module.portfolio_condition_monitor import (
    PortfolioConditionMonitor,
    PortfolioCurrentSnapshot,
)
from app_module.dtos.portfolio_dtos import PositionDTO
from data_module.config import TWStockConfig


def make_config(tmp_path):
    return TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="unit",
    )


def test_portfolio_service_gets_current_price_from_csv(tmp_path):
    config = make_config(tmp_path)
    # 建立 CSV 降級價格數據
    daily_price_dir = config.daily_price_dir
    daily_price_dir.mkdir(parents=True, exist_ok=True)
    
    csv_file = daily_price_dir / "2026-06-11.csv"
    csv_file.write_text(
        "證券代號,證券名稱,收盤價\n2330,台積電,920.0\n2317,鴻海,180.0\n",
        encoding="utf-8"
    )

    service = PortfolioService(config)
    
    # 測試 get_current_price
    price_2330 = service.get_current_price("2330")
    assert price_2330 == 920.0
    
    price_2317 = service.get_current_price("2317")
    assert price_2317 == 180.0
    
    price_unknown = service.get_current_price("9999")
    assert price_unknown is None


def test_portfolio_service_dto_calculates_unrealized_pnl(tmp_path):
    config = make_config(tmp_path)
    daily_price_dir = config.daily_price_dir
    daily_price_dir.mkdir(parents=True, exist_ok=True)
    
    # 寫入最新價格 120.0
    csv_file = daily_price_dir / "2026-06-11.csv"
    csv_file.write_text(
        "證券代號,證券名稱,收盤價\n2330,台積電,120.0\n",
        encoding="utf-8"
    )

    service = PortfolioService(config)
    
    # 記錄一筆買入交易，建立持倉
    service.record_trade(
        stock_code="2330",
        stock_name="台積電",
        side="buy",
        quantity=1000,
        price=100.0,
        trade_date="2026-06-10",
        trade_id="trade_001",
    )
    
    positions = service.list_positions()
    assert len(positions) == 1
    pos = positions[0]
    
    assert pos.current_price == 120.0
    # unrealized_pnl = (120 - 100) * 1000 = 20000
    assert pos.unrealized_pnl == 20000.0
    # unrealized_pnl_pct = 20000 / (100 * 1000) = 0.20
    assert pos.unrealized_pnl_pct == 0.20


def test_portfolio_condition_monitor_stop_loss_and_take_profit():
    monitor = PortfolioConditionMonitor(score_warning_points=10)
    
    # 準備 PositionDTO
    pos = PositionDTO.from_dict({
        "position_id": "pos_001",
        "portfolio_id": "default",
        "stock_code": "2330",
        "stock_name": "台積電",
        "quantity": 1000,
        "average_cost": 100.0,
        "invested_amount": 100000.0,
        "realized_pnl": 0.0,
        "source_type": "backtest_run",
        "source_id": "run_001",
        "source_summary": {
            "stop_loss_pct": 0.07,  # 7% 停損
            "take_profit_pct": 15.0,  # 15% 停利 (以 100 為基準之百分比)
            "regime": "trend",
            "total_score": 85.0,
        },
        "current_price": 100.0,
    })
    
    # 1. 未觸發任何停損/停利且 regime/score 無變化
    snapshot_normal = PortfolioCurrentSnapshot(
        current_regime="trend",
        current_total_score=85.0,
        current_price=100.0,
    )
    res = monitor.evaluate(pos, snapshot_normal)
    assert res.status == "valid"
    assert res.label == "仍符合"
    assert "未觸發停損點 (-7.0%)" in res.reasons
    assert "未觸發停利點 (15.0%)" in res.reasons

    # 2. 觸發停損 (跌至 92.5，跌幅 7.5% > 7%)
    snapshot_sl = PortfolioCurrentSnapshot(
        current_regime="trend",
        current_total_score=85.0,
        current_price=92.5,
    )
    res_sl = monitor.evaluate(pos, snapshot_sl)
    assert res_sl.status == "invalid"
    assert res_sl.label == "假設失效"
    assert any("已觸發停損點" in r for r in res_sl.reasons)
    assert res_sl.details["stop_loss_triggered"] is True

    # 3. 觸發停利 (漲至 116.0，漲幅 16.0% > 15%)
    snapshot_tp = PortfolioCurrentSnapshot(
        current_regime="trend",
        current_total_score=85.0,
        current_price=116.0,
    )
    res_tp = monitor.evaluate(pos, snapshot_tp)
    assert res_tp.status == "invalid"
    assert res_tp.label == "假設失效"
    assert any("已觸發停利點" in r for r in res_tp.reasons)
    assert res_tp.details["take_profit_triggered"] is True

    # 4. 複合警告：Regime 改變 (warning)
    snapshot_regime = PortfolioCurrentSnapshot(
        current_regime="range",
        current_total_score=85.0,
        current_price=100.0,
    )
    res_regime = monitor.evaluate(pos, snapshot_regime)
    assert res_regime.status == "warning"
    assert res_regime.label == "需要留意"
    assert any("Regime 已由 trend 轉為 range" in r for r in res_regime.reasons)
