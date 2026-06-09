from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.portfolio_condition_monitor import (
    PortfolioConditionMonitor,
    PortfolioCurrentSnapshot,
)


def make_position(
    source_type="recommendation_result",
    source_id="rec_001",
    source_summary=None,
):
    return PositionDTO(
        position_id="default:2330",
        portfolio_id="default",
        stock_code="2330",
        stock_name="台積電",
        quantity=1000,
        average_cost=900,
        invested_amount=900000,
        source_type=source_type,
        source_id=source_id,
        source_summary=dict(source_summary or {}),
        trade_ids=["trade_001"],
    )


def test_condition_monitor_marks_position_valid_when_regime_and_score_still_hold():
    monitor = PortfolioConditionMonitor(score_warning_points=10)
    position = make_position(
        source_summary={
            "profile_id": "aggressive_short",
            "regime": "trend",
            "total_score": 85.0,
        }
    )

    result = monitor.evaluate(
        position,
        PortfolioCurrentSnapshot(
            current_regime="trend",
            current_total_score=80.0,
        ),
    )

    assert result.status == "valid"
    assert result.label == "仍符合"
    assert result.source_label == "推薦：aggressive_short"
    assert result.entry_total_score == "85.0"
    assert result.current_total_score == "80.0"
    assert result.details["score_change"] == "-5.0"
    assert result.reasons == ["Regime 仍為 trend", "評分變化 -5.0 分，未超過 10 分門檻"]


def test_condition_monitor_warns_when_score_degrades_beyond_threshold():
    monitor = PortfolioConditionMonitor(score_warning_points=10)
    position = make_position(
        source_summary={
            "profile_id": "stable_long",
            "regime": "trend",
            "total_score": 78.0,
        }
    )

    result = monitor.evaluate(
        position,
        PortfolioCurrentSnapshot(
            current_regime="trend",
            current_total_score=62.0,
        ),
    )

    assert result.status == "warning"
    assert result.label == "需要留意"
    assert "評分下降 16.0 分" in result.reasons
    assert result.details["score_degraded"] is True


def test_condition_monitor_marks_invalid_when_regime_changes_and_score_degrades():
    monitor = PortfolioConditionMonitor(score_warning_points=10)
    position = make_position(
        source_type="backtest_run",
        source_id="run_001",
        source_summary={
            "strategy_id": "momentum_aggressive_v1",
            "regime": "trend",
            "total_score": 82.0,
        }
    )

    result = monitor.evaluate(
        position,
        PortfolioCurrentSnapshot(
            current_regime="range",
            current_total_score=60.0,
        ),
    )

    assert result.status == "invalid"
    assert result.label == "假設失效"
    assert result.source_label == "回測：momentum_aggressive_v1"
    assert "Regime 已由 trend 轉為 range" in result.reasons
    assert "評分下降 22.0 分" in result.reasons


def test_condition_monitor_warns_when_position_has_no_traceable_source():
    monitor = PortfolioConditionMonitor(score_warning_points=10)
    position = make_position(source_type="", source_id="", source_summary={})

    result = monitor.evaluate(position)

    assert result.status == "warning"
    assert result.label == "來源不足"
    assert result.source_label == "手動"
    assert result.reasons == ["缺少推薦、回測或策略版本來源，無法對照進場假設"]
