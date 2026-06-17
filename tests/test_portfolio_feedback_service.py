from dataclasses import dataclass, field

from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.portfolio_feedback_service import (
    FeedbackCategory,
    PortfolioFeedbackService,
)
from app_module.strategy_lifecycle_service import GateStatus, StrategyDriftReport


@dataclass(frozen=True)
class _ConditionResult:
    status: str
    entry_regime: str = ""
    current_regime: str = ""
    reasons: list[str] = field(default_factory=list)


def _position(**overrides) -> PositionDTO:
    values = {
        "position_id": "pos-2330",
        "portfolio_id": "default",
        "stock_code": "2330",
        "stock_name": "台積電",
        "quantity": 1000,
        "average_cost": 102.0,
        "invested_amount": 102000.0,
        "source_type": "backtest_run",
        "source_id": "run-001",
        "source_snapshot_hash": "hash-001",
        "source_summary": {
            "run_id": "run-001",
            "strategy_id": "baseline_score",
            "price": 100.0,
            "regime": "bull",
            "quality": "observed",
        },
    }
    values.update(overrides)
    return PositionDTO.from_dict(values)


def test_position_feedback_marks_clean_thesis_as_pass_with_execution_gap_evidence():
    service = PortfolioFeedbackService()

    report = service.build_position_feedback(
        _position(),
        condition_result=_ConditionResult("valid", entry_regime="bull", current_regime="bull"),
    )

    assert report.thesis_status == GateStatus.PASS
    execution = next(item for item in report.items if item.category == FeedbackCategory.EXECUTION)
    assert execution.status == GateStatus.PASS
    assert execution.evidence["gap_bp"] == 200
    assert "execution:pass" in report.summary_tokens


def test_position_feedback_flags_execution_gap_and_condition_invalid():
    service = PortfolioFeedbackService()

    report = service.build_position_feedback(
        _position(average_cost=107.0),
        condition_result=_ConditionResult(
            "invalid",
            entry_regime="bull",
            current_regime="bear",
            reasons=["Regime 已由 bull 轉為 bear", "評分下降 20 分"],
        ),
    )

    assert report.thesis_status == GateStatus.FAIL
    assert any(
        item.category == FeedbackCategory.EXECUTION
        and item.status == GateStatus.FAIL
        and item.evidence["gap_bp"] == 700
        for item in report.items
    )
    assert any(
        item.category == FeedbackCategory.SIGNAL
        and item.status == GateStatus.FAIL
        for item in report.items
    )
    assert any(
        item.category == FeedbackCategory.MARKET
        and item.status == GateStatus.DEGRADED
        for item in report.items
    )


def test_position_feedback_flags_missing_source_trace_and_data_quality():
    service = PortfolioFeedbackService()

    report = service.build_position_feedback(
        _position(
            source_type="",
            source_id="",
            source_snapshot_hash="",
            source_summary={"data_quality": "degraded"},
        )
    )

    assert report.thesis_status == GateStatus.DEGRADED
    assert any(item.category == FeedbackCategory.SOURCE and item.status == GateStatus.DEGRADED for item in report.items)
    assert any(
        item.category == FeedbackCategory.DATA_QUALITY
        and "source_snapshot_hash_missing" in item.evidence["flags"]
        and "source_quality:degraded" in item.evidence["flags"]
        for item in report.items
    )


def test_position_feedback_uses_strategy_drift_report_as_signal_gap():
    service = PortfolioFeedbackService()
    drift = StrategyDriftReport(
        baseline_run_id="baseline",
        current_run_id="current",
        status=GateStatus.FAIL,
        drift_reasons=("sharpe_ratio_degraded",),
    )

    report = service.build_position_feedback(_position(), drift_report=drift)

    assert report.thesis_status == GateStatus.FAIL
    signal_items = [item for item in report.items if item.category == FeedbackCategory.SIGNAL]
    assert signal_items[0].reason == "strategy drift detected"
    assert signal_items[0].evidence["drift_reasons"] == ("sharpe_ratio_degraded",)


def test_live_research_gap_report_summarizes_position_statuses():
    service = PortfolioFeedbackService()
    positions = [
        _position(stock_code="2330", average_cost=102.0),
        _position(stock_code="2317", average_cost=109.0),
    ]
    conditions = {
        "2330": _ConditionResult("valid", entry_regime="bull", current_regime="bull"),
        "2317": _ConditionResult("warning", entry_regime="bull", current_regime="neutral"),
    }

    report = service.build_live_research_gap_report(
        positions,
        condition_results=conditions,
        portfolio_id="default",
    )

    assert report.total_positions == 2
    assert report.observed_count == 1
    assert report.invalid_count == 1
    assert report.warning_count == 0
    assert report.warnings == ("portfolio_feedback_position_warning:2317",)
