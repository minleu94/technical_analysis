from dataclasses import dataclass
from typing import Any

from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.portfolio_review_service import PortfolioReviewService
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.strategy_lifecycle_service import GateStatus, StrategyDriftReport


@dataclass
class _PortfolioProvider:
    positions: list[PositionDTO]

    def list_positions(self, portfolio_id: str = "default"):
        return self.positions


def _run(run_id: str, **overrides: Any) -> ResearchRunMetadataDTO:
    values: dict[str, Any] = {
        "run_id": run_id,
        "run_name": run_id,
        "run_type": "single_backtest",
        "strategy_id": "baseline_score",
        "metrics": {
            "total_return": "0.12",
            "sharpe_ratio": "0.90",
            "max_drawdown": "0.18",
            "win_rate": "0.56",
            "total_trades": 24,
        },
        "regime_breakdown": {"bull": {"trades": 24}},
        "benchmark_results": {"taiex": {"excess_return_bp": 700}},
        "data_manifest": {
            "factor_snapshot": {
                "records": [
                    {"factor_name": "technical.total_score", "quality": "observed"},
                    {"factor_name": "broker.net_buy", "quality": "observed"},
                ]
            }
        },
        "payload_hash": f"sha256:{run_id}",
        "created_at": "2026-06-17T12:00:00",
    }
    values.update(overrides)
    return ResearchRunMetadataDTO(**values)


def _position(stock_code: str, average_cost: float) -> PositionDTO:
    return PositionDTO.from_dict(
        {
            "position_id": f"pos-{stock_code}",
            "portfolio_id": "default",
            "stock_code": stock_code,
            "stock_name": stock_code,
            "quantity": 1000,
            "average_cost": average_cost,
            "invested_amount": average_cost * 1000,
            "source_type": "backtest_run",
            "source_id": f"run-{stock_code}",
            "source_snapshot_hash": f"hash-{stock_code}",
            "source_summary": {"price": 100.0, "quality": "observed"},
        }
    )


def test_portfolio_review_snapshot_aggregates_lifecycle_and_gap_report():
    service = PortfolioReviewService()
    portfolio = _PortfolioProvider([_position("2330", 102.0)])

    snapshot = service.build_snapshot(
        portfolio_provider=portfolio,
        candidate_runs=[_run("candidate")],
        expected_regimes_by_strategy={"baseline_score": ["bull"]},
    )

    assert snapshot.quality == GateStatus.PASS
    assert snapshot.lifecycle_summary.total_runs == 1
    assert snapshot.lifecycle_summary.promote_candidates == 1
    assert snapshot.live_research_gap.total_positions == 1
    assert snapshot.live_research_gap.observed_count == 1
    assert snapshot.warnings == ()


def test_portfolio_review_snapshot_surfaces_retire_and_live_gap_warnings():
    service = PortfolioReviewService()
    portfolio = _PortfolioProvider([_position("2330", 109.0)])
    retire_run = _run(
        "retire",
        metrics={
            "total_return": "-0.12",
            "sharpe_ratio": "-0.30",
            "max_drawdown": "0.65",
            "win_rate": "0.33",
            "total_trades": 30,
        },
    )
    drift = StrategyDriftReport(
        baseline_run_id="baseline",
        current_run_id="current",
        status=GateStatus.FAIL,
        drift_reasons=("drawdown_worsened",),
    )

    snapshot = service.build_snapshot(
        portfolio_provider=portfolio,
        candidate_runs=[retire_run],
        drift_reports_by_stock={"2330": drift},
    )

    assert snapshot.quality == GateStatus.FAIL
    assert snapshot.lifecycle_summary.retire_count == 1
    assert snapshot.live_research_gap.invalid_count == 1
    assert "strategy_lifecycle_retire_count:1" in snapshot.warnings
    assert "portfolio_feedback_invalid_count:1" in snapshot.warnings
    assert "strategy_drift_count:1" in snapshot.warnings
