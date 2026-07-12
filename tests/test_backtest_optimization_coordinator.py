from unittest.mock import MagicMock

from app_module.optimizer_service import ParamRange
from ui_qt.views.backtest.optimization_coordinator import OptimizationExecutionRequest


def test_optimization_request_maps_grid_search_and_progress_contract() -> None:
    service = MagicMock()
    service.grid_search.return_value = [object()]
    progress = []
    cancelled = False
    request = OptimizationExecutionRequest(
        stock_code="2330",
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_id="momentum",
        base_params={"threshold_mode": "fixed"},
        param_ranges={
            "buy_score": ParamRange(
                name="buy_score", type="int", values=[], min=50, max=70, step=10
            )
        },
        capital=1_000_000,
        fee_bps="14.25",
        slippage_bps=5,
        stop_loss_pct="0.05",
        take_profit_pct="0.10",
        objective="sharpe_ratio",
    )

    result = request.execute(
        service,
        progress_callback=lambda message, pct: progress.append((message, pct)),
        check_cancel=lambda: cancelled,
    )
    service.grid_search.call_args.kwargs["progress_callback"](2, 4, "掃描中")

    assert result is service.grid_search.return_value
    kwargs = service.grid_search.call_args.kwargs
    assert kwargs["top_n"] == 20
    assert kwargs["check_cancel"]() is False
    assert progress == [("掃描中\n已完成 2/4 組參數 (50%)", 50)]
