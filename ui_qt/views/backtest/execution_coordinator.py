"""BacktestView 單檔執行的不可變 request 與 service mapping。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BacktestExecutionRequest:
    stock_code: str
    start_date: str
    end_date: str
    strategy_id: str
    strategy_spec: Any
    strategy_params: dict[str, Any]
    capital: Any
    fee_bps: Any
    slippage_bps: Any
    execution_price: str
    stop_loss_pct: Any
    take_profit_pct: Any
    stop_loss_atr_mult: Any
    take_profit_atr_mult: Any
    sizing_mode: str
    fixed_amount: Any
    risk_pct: Any
    max_positions: int | None
    position_sizing: str
    allow_pyramid: bool
    allow_reentry: bool
    reentry_cooldown_days: int
    enable_limit: bool
    enable_volume: bool
    max_participation: Any

    def run_params(self) -> dict[str, Any]:
        values = asdict(self)
        values.pop("strategy_spec")
        values["strategy_params"] = dict(self.strategy_params)
        return values

    def execute(self, backtest_service: Any, *, check_cancel: Any = None) -> Any:
        cancel_kwargs = {"check_cancel": check_cancel} if check_cancel is not None else {}
        return backtest_service.run_backtest(
            stock_code=self.stock_code,
            start_date=self.start_date,
            end_date=self.end_date,
            strategy_spec=self.strategy_spec,
            strategy_executor=None,
            capital=self.capital,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            execution_price=self.execution_price,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            stop_loss_atr_mult=self.stop_loss_atr_mult,
            take_profit_atr_mult=self.take_profit_atr_mult,
            sizing_mode=self.sizing_mode,
            fixed_amount=self.fixed_amount,
            risk_pct=self.risk_pct,
            max_positions=self.max_positions,
            position_sizing=self.position_sizing,
            allow_pyramid=self.allow_pyramid,
            allow_reentry=self.allow_reentry,
            reentry_cooldown_days=self.reentry_cooldown_days,
            enable_limit_up_down=self.enable_limit,
            enable_volume_constraint=self.enable_volume,
            max_participation_rate=self.max_participation,
            **cancel_kwargs,
        )


@dataclass(frozen=True)
class BatchBacktestExecutionRequest:
    stock_codes: tuple[str, ...]
    start_date: str
    end_date: str
    strategy_spec: Any
    capital: Any
    fee_bps: Any
    slippage_bps: Any
    execution_price: str
    stop_loss_pct: Any
    take_profit_pct: Any
    stop_loss_atr_mult: Any
    take_profit_atr_mult: Any
    sizing_mode: str
    fixed_amount: Any
    risk_pct: Any
    max_positions: int | None
    position_sizing: str
    allow_pyramid: bool
    allow_reentry: bool
    reentry_cooldown_days: int
    enable_limit: bool
    enable_volume: bool
    max_participation: Any
    parallel_threshold: int | None
    research_mode: str

    def execute(
        self,
        batch_backtest_service: Any,
        *,
        progress_callback: Any,
        check_cancel: Any,
    ) -> Any:
        return batch_backtest_service.run_batch_backtest(
            stock_codes=list(self.stock_codes),
            start_date=self.start_date,
            end_date=self.end_date,
            strategy_spec=self.strategy_spec,
            capital=self.capital,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            execution_price=self.execution_price,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            stop_loss_atr_mult=self.stop_loss_atr_mult,
            take_profit_atr_mult=self.take_profit_atr_mult,
            sizing_mode=self.sizing_mode,
            fixed_amount=self.fixed_amount,
            risk_pct=self.risk_pct,
            max_positions=self.max_positions,
            position_sizing=self.position_sizing,
            allow_pyramid=self.allow_pyramid,
            allow_reentry=self.allow_reentry,
            reentry_cooldown_days=self.reentry_cooldown_days,
            enable_limit_up_down=self.enable_limit,
            enable_volume_constraint=self.enable_volume,
            max_participation_rate=self.max_participation,
            save_runs=True,
            progress_callback=progress_callback,
            check_cancel=check_cancel,
            parallel_threshold=self.parallel_threshold,
            research_mode=self.research_mode,
        )
