"""BacktestView Walk-forward / Train-Test service request。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WalkForwardExecutionRequest:
    mode: str
    stock_code: str
    start_date: str
    end_date: str
    strategy_spec: Any
    train_ratio: Any
    train_months: int
    test_months: int
    step_months: int
    capital: Any
    fee_bps: Any
    slippage_bps: Any
    stop_loss_pct: Any
    take_profit_pct: Any

    def execute(self, walkforward_service: Any) -> dict[str, Any]:
        common = {
            "stock_code": self.stock_code,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "strategy_spec": self.strategy_spec,
            "capital": self.capital,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }
        if self.mode == "Train-Test Split":
            train_report, test_report = walkforward_service.train_test_split(
                **common,
                train_ratio=self.train_ratio,
            )
            return {
                "mode": "split",
                "train_report": train_report,
                "test_report": test_report,
            }
        results = walkforward_service.walk_forward(
            **common,
            train_months=self.train_months,
            test_months=self.test_months,
            step_months=self.step_months,
        )
        return {
            "mode": "walkforward",
            "results": results,
            "summary": walkforward_service.summarize_walkforward(results),
        }
