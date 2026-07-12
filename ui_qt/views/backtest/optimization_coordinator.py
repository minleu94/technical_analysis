"""BacktestView 參數掃描的不可變 service request。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app_module.optimizer_service import ParamRange


@dataclass(frozen=True)
class OptimizationExecutionRequest:
    stock_code: str
    start_date: str
    end_date: str
    strategy_id: str
    base_params: dict[str, Any]
    param_ranges: dict[str, ParamRange]
    capital: Any
    fee_bps: Any
    slippage_bps: Any
    stop_loss_pct: Any
    take_profit_pct: Any
    objective: str
    top_n: int = 20

    def execute(
        self,
        optimizer_service: Any,
        *,
        progress_callback: Callable[[str, int], None] | None,
        check_cancel: Callable[[], bool],
    ) -> Any:
        def wrapped_callback(current: int, total: int, message: str) -> None:
            if progress_callback:
                percentage = int(current / total * 100) if total > 0 else 0
                progress_callback(
                    f"{message}\n已完成 {current}/{total} 組參數 ({percentage}%)",
                    percentage,
                )

        return optimizer_service.grid_search(
            stock_code=self.stock_code,
            start_date=self.start_date,
            end_date=self.end_date,
            strategy_id=self.strategy_id,
            base_params=self.base_params,
            param_ranges=self.param_ranges,
            capital=self.capital,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            objective=self.objective,
            top_n=self.top_n,
            progress_callback=wrapped_callback,
            check_cancel=check_cancel,
        )
