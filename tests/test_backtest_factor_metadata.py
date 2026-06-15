from __future__ import annotations

import pandas as pd

from app_module.backtest_service import BacktestService
from app_module.strategy_spec import StrategySpec
from data_module.config import TWStockConfig


class _ScoreOnlyExecutor:
    def generate_signals(
        self,
        df: pd.DataFrame,
        spec: StrategySpec,
        execution_start_date: str | None = None,
    ) -> pd.DataFrame:
        del spec, execution_start_date
        signal_frame = df.copy()
        signal_frame["signal"] = [1, 0, -1]
        signal_frame["score"] = [82.35, 75.0, 40.0]
        return signal_frame


def test_single_backtest_report_includes_factor_records_from_signal_scores(tmp_path):
    service = BacktestService(
        TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    )
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    preloaded = pd.DataFrame(
        {
            "開盤價": [100.0, 101.0, 102.0],
            "最高價": [101.0, 102.0, 103.0],
            "最低價": [99.0, 100.0, 101.0],
            "收盤價": [100.0, 101.0, 102.0],
            "成交股數": [1_000_000.0, 1_000_000.0, 1_000_000.0],
        },
        index=dates,
    )
    spec = StrategySpec(
        strategy_id="baseline_score",
        strategy_version="1.0",
        default_params={"buy_score": 60, "sell_score": 40},
        config={"params": {"threshold_mode": "fixed", "buy_score": 60, "sell_score": 40}},
    )

    report = service.run_backtest(
        stock_code="2330",
        start_date="2026-01-05",
        end_date="2026-01-07",
        strategy_spec=spec,
        strategy_executor=_ScoreOnlyExecutor(),
        preloaded_data=preloaded,
        capital=1_000_000,
        fee_bps=0,
        slippage_bps=0,
        enable_volume_constraint=False,
        enable_overfitting_risk=False,
    )

    records = report.details["factor_records"]
    assert report.details["factor_decision_date"].isoformat() == "2026-01-07"
    assert [record.factor_name for record in records] == [
        "technical.total_score",
        "technical.total_score",
        "technical.total_score",
    ]
    assert [record.stock_code for record in records] == ["2330", "2330", "2330"]
    assert records[0].score_bp == 8235
    assert records[0].as_of_date.isoformat() == "2026-01-05"
    assert records[0].available_date == records[0].as_of_date
