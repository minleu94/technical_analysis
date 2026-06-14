import pytest
import pandas as pd
from app_module.report_export_dtos import (
    ReportMetadata,
    SingleBacktestExportPayload,
    BatchBacktestExportPayload,
    RecommendationReplayExportPayload,
    CurrentRecommendationExportPayload,
)


def test_single_backtest_payload_preserves_traceability_metadata():
    payload = SingleBacktestExportPayload(
        metadata=ReportMetadata(
            report_type="single_backtest",
            generated_at="2026-06-14T12:00:00",
            data_version="sha256:abc",
            strategy_version="baseline_score@1.0",
            regime="Trend",
            benchmark="TAIEX",
            execution_assumption="next_open",
        ),
        run_params={"fee_bps": 14.25, "slippage_bps": 5.0},
        metrics={"total_return": 0.12},
        validation={"status": "PASS", "messages": []},
        trades=pd.DataFrame(),
        equity_curve=pd.DataFrame(),
    )
    assert payload.metadata.data_version == "sha256:abc"
    assert payload.metadata.strategy_version == "baseline_score@1.0"


def test_missing_traceability_fields_are_explicit():
    metadata = ReportMetadata(report_type="current_recommendation")
    missing = metadata.missing_fields()
    assert "data_version" in missing
    assert "strategy_version" in missing
    assert "benchmark" in missing


def test_payload_copies_input_dataframes():
    source = pd.DataFrame([{"equity": 100}])
    payload = SingleBacktestExportPayload(
        metadata=ReportMetadata(report_type="single_backtest"),
        run_params={},
        metrics={},
        validation={},
        trades=pd.DataFrame(),
        equity_curve=source,
    )
    source.loc[0, "equity"] = 0
    # 應為 100，因為有 defensive copy
    assert payload.equity_curve.loc[0, "equity"] == 100
