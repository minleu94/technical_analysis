from types import SimpleNamespace
from unittest.mock import MagicMock

from ui_qt.views.backtest.walkforward_coordinator import WalkForwardExecutionRequest


def _request(mode: str) -> WalkForwardExecutionRequest:
    return WalkForwardExecutionRequest(
        mode=mode,
        stock_code="2330",
        start_date="2024-01-01",
        end_date="2024-10-02",
        strategy_spec=SimpleNamespace(strategy_id="momentum"),
        train_ratio="0.7",
        train_months=6,
        test_months=3,
        step_months=3,
        capital=1_000_000,
        fee_bps="14.25",
        slippage_bps=5,
        stop_loss_pct="0.05",
        take_profit_pct="0.10",
    )


def test_train_test_request_preserves_result_envelope_and_kwargs() -> None:
    service = MagicMock()
    train, test = object(), object()
    service.train_test_split.return_value = (train, test)

    result = _request("Train-Test Split").execute(service)

    assert result == {"mode": "split", "train_report": train, "test_report": test}
    assert service.train_test_split.call_args.kwargs["train_ratio"] == "0.7"


def test_walkforward_request_preserves_fold_kwargs_and_summary_envelope() -> None:
    service = MagicMock()
    folds = [object()]
    summary = {"total_folds": 1}
    service.walk_forward.return_value = folds
    service.summarize_walkforward.return_value = summary

    result = _request("Walk-forward").execute(service)

    assert result == {"mode": "walkforward", "results": folds, "summary": summary}
    kwargs = service.walk_forward.call_args.kwargs
    assert (kwargs["train_months"], kwargs["test_months"], kwargs["step_months"]) == (6, 3, 3)
