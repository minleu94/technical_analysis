from types import SimpleNamespace
from unittest.mock import MagicMock

from ui_qt.views.backtest.execution_coordinator import (
    BacktestExecutionRequest,
    BatchBacktestExecutionRequest,
)


def _request() -> BacktestExecutionRequest:
    return BacktestExecutionRequest(
        stock_code="2330",
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_id="momentum",
        strategy_spec=SimpleNamespace(strategy_id="momentum"),
        strategy_params={"buy_score": 70},
        capital=1_000_000,
        fee_bps="14.25",
        slippage_bps=5,
        execution_price="next_open",
        stop_loss_pct="0.05",
        take_profit_pct="0.10",
        stop_loss_atr_mult=None,
        take_profit_atr_mult=None,
        sizing_mode="all_in",
        fixed_amount=None,
        risk_pct=None,
        max_positions=3,
        position_sizing="equal_weight",
        allow_pyramid=False,
        allow_reentry=True,
        reentry_cooldown_days=2,
        enable_limit=True,
        enable_volume=True,
        max_participation="0.05",
    )


def test_single_backtest_request_keeps_persistence_payload_contract() -> None:
    request = _request()

    assert request.run_params() == {
        "stock_code": "2330",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "strategy_id": "momentum",
        "strategy_params": {"buy_score": 70},
        "capital": 1_000_000,
        "fee_bps": "14.25",
        "slippage_bps": 5,
        "execution_price": "next_open",
        "stop_loss_pct": "0.05",
        "take_profit_pct": "0.10",
        "stop_loss_atr_mult": None,
        "take_profit_atr_mult": None,
        "sizing_mode": "all_in",
        "fixed_amount": None,
        "risk_pct": None,
        "max_positions": 3,
        "position_sizing": "equal_weight",
        "allow_pyramid": False,
        "allow_reentry": True,
        "reentry_cooldown_days": 2,
        "enable_limit": True,
        "enable_volume": True,
        "max_participation": "0.05",
    }


def test_single_backtest_request_maps_market_constraint_names_to_service_contract() -> None:
    request = _request()
    service = MagicMock()
    service.run_backtest.return_value = object()

    result = request.execute(service)

    assert result is service.run_backtest.return_value
    kwargs = service.run_backtest.call_args.kwargs
    assert kwargs["enable_limit_up_down"] is True
    assert kwargs["enable_volume_constraint"] is True
    assert kwargs["max_participation_rate"] == "0.05"
    assert kwargs["strategy_executor"] is None


def test_batch_request_preserves_research_parallel_progress_and_cancel_contract() -> None:
    service = MagicMock()
    request = BatchBacktestExecutionRequest(
        stock_codes=("2330", "2317"),
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_spec=SimpleNamespace(strategy_id="momentum"),
        capital=1_000_000,
        fee_bps="14.25",
        slippage_bps=5,
        execution_price="next_open",
        stop_loss_pct=None,
        take_profit_pct=None,
        stop_loss_atr_mult=2,
        take_profit_atr_mult=3,
        sizing_mode="all_in",
        fixed_amount=None,
        risk_pct=None,
        max_positions=2,
        position_sizing="equal_weight",
        allow_pyramid=False,
        allow_reentry=True,
        reentry_cooldown_days=0,
        enable_limit=True,
        enable_volume=True,
        max_participation="0.05",
        parallel_threshold=2,
        research_mode="batch_stock",
    )
    progress = MagicMock()
    cancel = MagicMock(return_value=False)

    request.execute(service, progress_callback=progress, check_cancel=cancel)

    kwargs = service.run_batch_backtest.call_args.kwargs
    assert kwargs["stock_codes"] == ["2330", "2317"]
    assert kwargs["save_runs"] is True
    assert kwargs["progress_callback"] is progress
    assert kwargs["check_cancel"] is cancel
    assert kwargs["parallel_threshold"] == 2
    assert kwargs["research_mode"] == "batch_stock"
