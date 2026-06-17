from typing import Any

from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.strategy_lifecycle_service import (
    GateStatus,
    LifecycleAction,
    LifecyclePolicy,
    StrategyLifecycleService,
)


def _metadata(run_id: str = "run-life-001", **overrides: Any) -> ResearchRunMetadataDTO:
    values: dict[str, Any] = {
        "run_id": run_id,
        "run_name": run_id,
        "run_type": "single_backtest",
        "strategy_id": "baseline_score",
        "strategy_version": "1.0.0",
        "parameter_contract_version": "v1",
        "normalized_params": {"buy_score": 70, "sell_score": 40},
        "universe": ["2330", "2317"],
        "start_date": "2026-01-02",
        "end_date": "2026-05-29",
        "data_cutoff_date": "2026-05-29",
        "data_fingerprint": "sha256:data",
        "capital_cents": 1_000_000_00,
        "fee_bp_x100": 1425,
        "slippage_bp_x100": 500,
        "execution_price": "next_open",
        "sizing_mode": "fixed_amount",
        "metrics": {
            "total_return": "0.12",
            "sharpe_ratio": "0.88",
            "max_drawdown": "0.18",
            "win_rate": "0.56",
            "total_trades": 24,
        },
        "regime_breakdown": {
            "bull": {"trades": 16},
            "neutral": {"trades": 8},
        },
        "benchmark_results": {
            "taiex": {
                "total_return_bp": 500,
                "excess_return_bp": 700,
            }
        },
        "data_manifest": {
            "factor_snapshot": {
                "records": [
                    {"factor_name": "technical.total_score", "quality": "observed"},
                    {"factor_name": "broker.net_buy", "quality": "observed"},
                    {"factor_name": "fundamental.revenue_yoy", "quality": "degraded"},
                ]
            },
            "factor_contributions": {
                "technical.total_score": {"accepted_count": 2},
            },
        },
        "payload_hash": f"sha256:{run_id}",
        "created_at": "2026-06-17T12:00:00",
    }
    values.update(overrides)
    return ResearchRunMetadataDTO(**values)


def test_lifecycle_promotes_only_when_all_saved_metadata_gates_pass():
    service = StrategyLifecycleService()

    decision = service.evaluate_run(_metadata(), expected_regimes=["bull", "neutral"])

    assert decision.action == LifecycleAction.PROMOTE
    assert decision.status == GateStatus.PASS
    assert decision.reasons == ("所有 lifecycle gates 通過，可進入 promote 候選",)
    assert {gate.gate_name for gate in decision.gates} == {
        "total_trades",
        "total_return",
        "sharpe_ratio",
        "max_drawdown",
        "win_rate",
        "excess_return",
        "factor_quality",
    }


def test_lifecycle_holds_when_trade_count_or_benchmark_evidence_is_missing():
    service = StrategyLifecycleService()
    run = _metadata(
        metrics={
            "total_return": "0.20",
            "sharpe_ratio": "1.10",
            "max_drawdown": "0.12",
            "win_rate": "0.61",
            "total_trades": 6,
        },
        benchmark_results={},
    )

    decision = service.evaluate_run(run, expected_regimes=["bull", "neutral"])

    assert decision.action == LifecycleAction.HOLD
    assert any(gate.gate_name == "total_trades" and gate.status == GateStatus.FAIL for gate in decision.gates)
    assert any(gate.gate_name == "excess_return" and gate.status == GateStatus.DEGRADED for gate in decision.gates)


def test_lifecycle_demotes_or_retires_from_saved_risk_metrics_without_recomputing():
    service = StrategyLifecycleService(
        LifecyclePolicy(demote_drawdown_bp=3500, retire_drawdown_bp=5500)
    )

    demote = service.evaluate_run(
        _metadata(
            "drawdown-demote",
            metrics={
                "total_return": "0.03",
                "sharpe_ratio": "0.70",
                "max_drawdown": "0.42",
                "win_rate": "0.52",
                "total_trades": 30,
            },
        )
    )
    retire = service.evaluate_run(
        _metadata(
            "drawdown-retire",
            metrics={
                "total_return": "-0.12",
                "sharpe_ratio": "-0.20",
                "max_drawdown": "0.62",
                "win_rate": "0.35",
                "total_trades": 30,
            },
        )
    )

    assert demote.action == LifecycleAction.DEMOTE
    assert retire.action == LifecycleAction.RETIRE


def test_regime_compatibility_fails_when_expected_regime_coverage_is_low():
    service = StrategyLifecycleService(LifecyclePolicy(required_regime_coverage_bp=7000))

    result = service.evaluate_regime_compatibility(
        _metadata(),
        expected_regimes=["bull"],
    )

    assert result.status == GateStatus.FAIL
    assert result.coverage_bp == 6667
    assert result.compatible_regimes == ("bull",)
    assert result.incompatible_regimes == ("neutral",)


def test_drift_detector_reads_two_saved_runs_and_reports_metric_or_factor_drift():
    service = StrategyLifecycleService()
    baseline = _metadata("baseline")
    current = _metadata(
        "current",
        metrics={
            "total_return": "0.02",
            "sharpe_ratio": "0.50",
            "max_drawdown": "0.31",
            "win_rate": "0.49",
            "total_trades": 24,
        },
        data_manifest={
            "factor_snapshot": {
                "records": [
                    {"factor_name": "technical.total_score", "quality": "observed"},
                ]
            },
            "factor_contributions": {},
        },
    )

    report = service.detect_drift(baseline, current)

    assert report.status == GateStatus.FAIL
    assert report.metric_changes["sharpe_ratio_delta"] == "-0.3800"
    assert report.metric_changes["max_drawdown_delta_bp"] == "1300"
    assert report.drift_reasons == (
        "sharpe_ratio_degraded",
        "drawdown_worsened",
        "factor_set_changed",
        "factor_contributions_missing",
    )
