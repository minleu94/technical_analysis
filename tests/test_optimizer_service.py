import logging
from concurrent.futures import Future
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app_module.exceptions import BacktestCancelledError
from app_module.optimizer_service import OptimizerService, ParamRange


def test_estimate_param_grid_size_counts_int_float_and_list_ranges():
    service = OptimizerService(MagicMock(), max_workers=2)
    param_ranges = {
        "short_window": ParamRange(
            name="short_window",
            type="int",
            values=[],
            min=5,
            max=15,
            step=5,
        ),
        "threshold": ParamRange(
            name="threshold",
            type="float",
            values=[],
            min=0.1,
            max=0.3,
            step=0.1,
        ),
        "mode": ParamRange(
            name="mode",
            type="list",
            values=["a", "b"],
        ),
    }

    assert service.estimate_param_grid_size(param_ranges) == 18


def test_estimate_param_grid_size_handles_empty_ranges_as_one_fixed_value():
    service = OptimizerService(MagicMock(), max_workers=2)

    assert service.estimate_param_grid_size({}) == 1


def test_generate_param_grid_matches_estimated_size():
    service = OptimizerService(MagicMock(), max_workers=2)
    param_ranges = {
        "fast": ParamRange("fast", "int", [], min=5, max=7, step=1),
        "slow": ParamRange("slow", "int", [], min=20, max=24, step=2),
    }

    grid = service.generate_param_grid(param_ranges)

    assert len(grid) == service.estimate_param_grid_size(param_ranges)


def test_grid_search_cancellation_does_not_submit_entire_grid_or_log_empty_errors(
    monkeypatch,
    caplog,
):
    backtest_service = MagicMock()
    backtest_service._load_stock_data.return_value = (
        pd.DataFrame({"日期": ["2026-01-02"], "收盤價": [100]}),
        "2026-01-02",
        "2026-01-02",
    )
    service = OptimizerService(backtest_service, max_workers=2)

    class RecordingExecutor:
        instances = []

        def __init__(self, max_workers):
            self.max_workers = max_workers
            self.submitted = 0
            self.futures = []
            self.shutdown_calls = []
            RecordingExecutor.instances.append(self)

        def submit(self, _fn, *_args, **_kwargs):
            self.submitted += 1
            future = Future()
            self.futures.append(future)
            return future

        def shutdown(self, wait=True, cancel_futures=False):
            self.shutdown_calls.append(
                {"wait": wait, "cancel_futures": cancel_futures}
            )

    monkeypatch.setattr(
        "app_module.optimizer_service.ThreadPoolExecutor",
        RecordingExecutor,
    )
    monkeypatch.setattr(
        "app_module.optimizer_service.wait",
        lambda pending, timeout, return_when: (set(pending), set()),
    )
    caplog.set_level(logging.ERROR)

    with pytest.raises(BacktestCancelledError):
        service.grid_search(
            stock_code="2330",
            start_date="2026-01-02",
            end_date="2026-01-02",
            strategy_id="baseline_score_v1",
            base_params={},
            param_ranges={
                "param": ParamRange("param", "int", [], min=1, max=20, step=1),
            },
            check_cancel=lambda: True,
        )

    assert RecordingExecutor.instances
    assert RecordingExecutor.instances[0].submitted <= service.max_workers * 2
    assert "最佳化子任務" not in caplog.text
    assert "異常:" not in caplog.text
