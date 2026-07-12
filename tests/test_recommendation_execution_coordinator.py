from unittest.mock import MagicMock

from ui_qt.views.recommendation.execution_coordinator import (
    RecommendationExecutionRequest,
)


def _config(patterns=None, indicators=None):
    return {
        "patterns": {"selected": ["W底"] if patterns is None else patterns},
        "signals": {
            "technical_indicators": ["trend"] if indicators is None else indicators
        },
        "filters": {"price_change_min": "2.50"},
        "regime": "Trend",
    }


def test_recommendation_request_validates_required_pattern_and_indicator() -> None:
    assert RecommendationExecutionRequest(_config(patterns=[])).validation_error() == (
        "請至少選擇一個圖形模式"
    )
    assert RecommendationExecutionRequest(_config(indicators=[])).validation_error() == (
        "請至少選擇一個技術指標"
    )
    assert RecommendationExecutionRequest(_config()).validation_error() is None


def test_recommendation_request_owns_service_kwargs_and_progress_contract() -> None:
    service = MagicMock()
    service.run_recommendation.return_value = [object()]
    progress = []
    request = RecommendationExecutionRequest(_config())

    result = request.execute(
        service, progress_callback=lambda message, pct: progress.append((message, pct))
    )

    assert result is service.run_recommendation.return_value
    assert service.run_recommendation.call_args.kwargs == {
        "config": request.config,
        "max_stocks": 200,
        "top_n": 50,
    }
    assert progress == [("讀取股票數據...", 10), ("分析完成", 100)]
