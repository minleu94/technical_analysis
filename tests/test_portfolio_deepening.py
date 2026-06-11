import os
import sys
from pathlib import Path
import pytest
from decimal import Decimal
from unittest.mock import MagicMock

# 確保 Qt offscreen 運行
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

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


def test_portfolio_view_resolves_strategy_version_from_backtest_run(tmp_path):
    # 確保有 QApplication
    q_app = QApplication.instance()
    if q_app is None:
        q_app = QApplication(sys.argv)

    config = make_config(tmp_path)

    # Mock Services
    mock_portfolio_service = MagicMock()
    mock_portfolio_service.config = config
    mock_journal_service = MagicMock()

    # 建立 PortfolioView
    from ui_qt.views.portfolio_view import PortfolioView
    from app_module.strategy_version_service import StrategyVersion

    view = PortfolioView(
        portfolio_service=mock_portfolio_service,
        journal_service=mock_journal_service,
    )

    # 建立 Mock 的 strategy_version_service
    mock_sv_service = MagicMock()
    view.strategy_version_service = mock_sv_service

    # 模擬當前選取的 stock 為 2330
    view.selected_stock_code = "2330"

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
        "source_id": "run_123",
        "source_summary": {
            "run_name": "台積電 MACD 回測",
            "strategy_id": "macd_strategy",
            "validation_status": "validated",
        },
        "current_price": 100.0,
        "unrealized_pnl": 0.0,
        "unrealized_pnl_pct": 0.0,
    })

    mock_portfolio_service.list_positions.return_value = [pos]
    mock_portfolio_service.get_current_price.return_value = 100.0

    # 模擬 StrategyVersion 對象
    fake_version = StrategyVersion(
        version_id="version_001",
        strategy_id="macd_strategy",
        strategy_version="1.0.2",
        source_run_id="run_123",
        promoted_at="2026-06-11T12:00:00",
        params={"buy_score": 80},
        config={},
        backtest_summary={"total_return": 0.25, "sharpe_ratio": 1.8, "max_drawdown": 0.1},
        regime=["trend"],
        validation_status="validated",
    )

    # ================= 測試第一層防禦 (source_summary 內建 promoted_version_id) =================
    pos.source_summary["promoted_version_id"] = "version_001"
    mock_sv_service.get_version.return_value = fake_version

    view._update_monitoring_tab()

    # 驗證 UI label 顯示了對應的正式版本資訊
    assert "macd_strategy" in view.lbl_strat_id.text()
    assert "version_001" in view.lbl_strat_id.text()
    assert "版本: 1.0.2" in view.lbl_strat_version.text()
    assert "buy_score: 80" in view.lbl_strat_params.text()
    assert "總報酬: +25.0%" in view.lbl_strat_perf.text()

    # ================= 測試第二層防禦 (從 BacktestRunRepository 讀取) =================
    pos.source_summary["promoted_version_id"] = None  # 清空第一層

    # 寫入 SQLite DB
    from app_module.backtest_repository import BacktestRunRepository, BacktestRun
    from app_module.dtos import BacktestReportDTO

    run_repo = BacktestRunRepository(config)
    report = BacktestReportDTO(
        total_return=0.25,
        annual_return=0.20,
        sharpe_ratio=1.8,
        max_drawdown=0.1,
        win_rate=0.6,
        total_trades=15,
        expectancy=1.5,
        details={"profit_factor": 2.0},
    )
    # 保存 run
    run_repo.save_run(
        run_name="台積電 MACD 回測",
        stock_code="2330",
        start_date="2026-01-01",
        end_date="2026-06-01",
        strategy_id="macd_strategy",
        strategy_params={"buy_score": 80},
        capital=100000.0,
        fee_bps=14.25,
        slippage_bps=5.0,
        stop_loss_pct=None,
        take_profit_pct=None,
        report=report,
        run_id="run_123",
    )
    # 標記為已推廣
    run_repo.mark_as_promoted("run_123", "version_002")

    # 調整 mock 以反映不同版本
    fake_version.version_id = "version_002"
    fake_version.strategy_version = "1.0.3"

    def get_version_side_effect(vid):
        if vid == "version_002":
            return fake_version
        return None
    mock_sv_service.get_version.side_effect = get_version_side_effect

    view._update_monitoring_tab()

    assert "version_002" in view.lbl_strat_id.text()
    assert "版本: 1.0.3" in view.lbl_strat_version.text()

    # ================= 測試第三層防禦 (遍歷 StrategyVersionService.list_versions) =================
    # 將 DB 中標記清空 (透過 save_run overwrite)
    run_repo.save_run(
        run_name="台積電 MACD 回測",
        stock_code="2330",
        start_date="2026-01-01",
        end_date="2026-06-01",
        strategy_id="macd_strategy",
        strategy_params={"buy_score": 80},
        capital=100000.0,
        fee_bps=14.25,
        slippage_bps=5.0,
        stop_loss_pct=None,
        take_profit_pct=None,
        report=report,
        run_id="run_123",
    )

    # 讓 list_versions 返回含有 source_run_id == "run_123" 的版本
    mock_sv_service.list_versions.return_value = [
        {
            "version_id": "version_003",
            "strategy_id": "macd_strategy",
            "strategy_version": "1.0.4",
            "source_run_id": "run_123",
        }
    ]

    fake_version.version_id = "version_003"
    fake_version.strategy_version = "1.0.4"

    def get_version_side_effect_3(vid):
        if vid == "version_003":
            return fake_version
        return None
    mock_sv_service.get_version.side_effect = get_version_side_effect_3

    view._update_monitoring_tab()

    assert "version_003" in view.lbl_strat_id.text()
    assert "版本: 1.0.4" in view.lbl_strat_version.text()
