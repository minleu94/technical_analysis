from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from app_module.backtest_service import BacktestService
from app_module.dtos import BacktestReportDTO
from app_module.strategy_spec import StrategySpec
from app_module.walkforward_service import WalkForwardService
from app_module.strategies.momentum_aggressive_executor import (
    MomentumAggressiveExecutor,
)
from decision_module.market_regime_detector import MarketRegimeDetector
from scripts.run_walk_forward_comparison import (
    _build_equal_weight_daily_returns,
    _iter_walk_forward_windows,
    _run_walk_forward_with_details,
    _resolve_regime_label,
    build_empirical_conclusion,
)


def _report() -> BacktestReportDTO:
    return BacktestReportDTO(
        total_return=0.0,
        annual_return=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        win_rate=0.0,
        total_trades=0,
        expectancy=0.0,
        details={},
    )


def test_walk_forward_test_fold_uses_training_history_as_signal_context():
    backtest_service = MagicMock()
    backtest_service.run_backtest.return_value = _report()
    service = WalkForwardService(backtest_service)
    strategy_spec = StrategySpec(
        strategy_id="test",
        strategy_version="1.0",
        config={"params": {"threshold_mode": "quantile"}},
    )

    results = service.walk_forward(
        stock_code="2330",
        start_date="2024-01-01",
        end_date="2024-10-02",
        strategy_spec=strategy_spec,
        train_months=6,
        test_months=3,
        step_months=3,
    )

    assert len(results) == 1
    test_call = backtest_service.run_backtest.call_args_list[1]
    assert test_call.kwargs["start_date"] == "2024-07-02"
    assert test_call.kwargs["signal_context_start_date"] == "2024-01-01"


def test_backtest_signal_context_is_excluded_from_execution_metrics():
    config = MagicMock()
    service = BacktestService(config)
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    context_df = pd.DataFrame(
        {
            "開盤價": [100.0] * 10,
            "最高價": [101.0] * 10,
            "最低價": [99.0] * 10,
            "收盤價": [100.0] * 10,
            "成交股數": [1_000_000.0] * 10,
        },
        index=dates,
    )
    signal_frame = context_df.copy()
    signal_frame["score"] = 50.0
    signal_frame["signal"] = 0

    executor = MagicMock()
    executor.generate_signals.return_value = signal_frame
    broker = MagicMock()
    execution_index = dates[5:]
    broker.run.return_value = (
        [],
        pd.DataFrame({"equity": [1_000_000.0] * 5}, index=execution_index),
    )
    strategy_spec = StrategySpec(
        strategy_id="test",
        strategy_version="1.0",
        config={"params": {"threshold_mode": "fixed"}},
    )

    with (
        patch.object(
            service,
            "_load_stock_data",
            return_value=(context_df, "2024-01-01", "2024-01-10"),
        ),
        patch(
            "app_module.backtest_service.StrategyRegistry.get_executor",
            return_value=executor,
        ),
        patch("app_module.backtest_service.BrokerSimulator", return_value=broker),
    ):
        report = service.run_backtest(
            stock_code="2330",
            start_date="2024-01-06",
            end_date="2024-01-10",
            signal_context_start_date="2024-01-01",
            strategy_spec=strategy_spec,
        )

    executor.generate_signals.assert_called_once()
    assert len(executor.generate_signals.call_args.args[0]) == 10
    execution_frame = broker.run.call_args.args[0]
    assert list(execution_frame.index) == list(execution_index)
    assert report.details["start_date"] == "2024-01-06"
    assert report.details["date_adjusted"] is None


def test_empirical_conclusion_is_inconclusive_when_fixed_has_no_trades():
    conclusion = build_empirical_conclusion(
        fixed_total_trades=0,
        quantile_total_trades=12,
        fixed_avg_test_sharpe=0.0,
        quantile_avg_test_sharpe=-1.2,
    )

    assert "不足以判定" in conclusion
    assert "未證明 quantile 改善" in conclusion


def test_oos_signal_generation_resets_position_state_at_execution_start():
    executor = object.__new__(MomentumAggressiveExecutor)
    executor.buy_confirm_days = 1
    executor.sell_confirm_days = 1
    executor.cooldown_days = 0
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    frame = pd.DataFrame(index=dates)
    buy_candidate = pd.Series([True, False, False, False], index=dates)
    sell_candidate = pd.Series([False, False, True, False], index=dates)

    signals = executor._generate_signals(
        df=frame,
        buy_candidate=buy_candidate,
        sell_candidate=sell_candidate,
        execution_start_date="2024-01-03",
    )

    assert signals.tolist() == [0, 0, 0, 0]


def test_walk_forward_windows_are_precomputed_independently_of_fold_execution():
    windows = list(
        _iter_walk_forward_windows(
            start_date="2024-01-01",
            end_date="2025-01-02",
            train_months=6,
            test_months=3,
            step_months=3,
        )
    )

    assert [window.fold for window in windows] == [1, 2]
    assert windows[0].test_start == "2024-07-02"
    assert windows[1].train_start == "2024-04-01"


def test_missing_regime_label_is_unavailable_instead_of_reversion():
    label, observed = _resolve_regime_label({}, "2026-06-01")

    assert label == "unavailable"
    assert observed is False


def test_regime_label_uses_latest_observation_available_on_decision_date():
    label, observed = _resolve_regime_label(
        {
            "2026-05-29": "Trend",
            "2026-06-02": "Breakout",
        },
        "2026-06-01",
    )

    assert label == "Trend"
    assert observed is True


def test_equal_weight_daily_returns_aggregate_stocks_before_regime_stats():
    records = [
        {"stock": "2330", "date": "2026-06-01", "return": 0.10, "regime": "Trend"},
        {"stock": "2317", "date": "2026-06-01", "return": -0.10, "regime": "Trend"},
        {"stock": "2330", "date": "2026-06-02", "return": 0.20, "regime": "Trend"},
    ]

    aggregated = _build_equal_weight_daily_returns(records)

    assert aggregated == [
        {"date": "2026-06-01", "return": 0.0, "regime": "Trend"},
        {"date": "2026-06-02", "return": 0.2, "regime": "Trend"},
    ]


def test_isolated_regime_detector_does_not_load_or_write_persistent_history(
    tmp_path: Path,
):
    history_path = tmp_path / "regime_history.json"
    history_path.write_text(
        '{"2099-01-01": {"regime": "Trend", "timestamp": "future"}}',
        encoding="utf-8",
    )
    config = SimpleNamespace(resolve_output_path=lambda _: tmp_path)
    detector = MarketRegimeDetector(config, use_persistent_history=False)

    detector._save_regime_history("2026-06-01", "Breakout")

    assert detector.regime_history == {
        "2026-06-01": {"regime": "Breakout", "timestamp": detector.regime_history["2026-06-01"]["timestamp"]}
    }
    assert "2099-01-01" not in detector.regime_history
    assert history_path.read_text(encoding="utf-8").startswith('{"2099-01-01"')


def test_failed_fold_does_not_prevent_later_walk_forward_windows():
    backtest_service = MagicMock()
    backtest_service.run_backtest.side_effect = [
        RuntimeError("first fold failed"),
        *[_report() for _ in range(14)],
    ]

    results, trades, returns = _run_walk_forward_with_details(
        backtest_service,
        "2330",
        "fixed",
        {},
    )

    assert len(results) == 7
    assert results[0].test_period == ("2024-10-02", "2025-01-02")
    assert backtest_service.run_backtest.call_count == 15
    assert trades == []
    assert returns == []


def test_regime_hysteresis_ignores_history_after_target_date(tmp_path: Path):
    config = SimpleNamespace(resolve_output_path=lambda _: tmp_path)
    detector = MarketRegimeDetector(config, use_persistent_history=False)
    detector.regime_history = {
        "2026-05-31": {"regime": "Reversion", "timestamp": "past"},
        "2099-01-01": {"regime": "Trend", "timestamp": "future"},
    }

    regime = detector._apply_regime_hysteresis("Trend", "2026-06-01")

    assert regime == "Reversion"
