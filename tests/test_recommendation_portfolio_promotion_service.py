import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationPortfolioBacktestResultDTO,
    RecommendationSnapshotDTO,
    StockContributionDTO,
)
from app_module.recommendation_portfolio_promotion_service import (
    RecommendationPortfolioPromotionService,
)
from app_module.recommendation_portfolio_run_repository import (
    RecommendationPortfolioRunRepository,
)
from app_module.strategy_version_service import StrategyVersionService


class DummyConfig:
    def __init__(self, temp_dir):
        self.temp_dir = Path(temp_dir)

    def resolve_output_path(self, relative_path: str) -> Path:
        path = self.temp_dir / relative_path
        path.mkdir(parents=True, exist_ok=True)
        return path


@pytest.fixture
def promotion_fixture():
    temp_dir = tempfile.mkdtemp()
    config = DummyConfig(temp_dir)
    run_repository = RecommendationPortfolioRunRepository(config)
    strategy_version_service = StrategyVersionService(config)
    service = RecommendationPortfolioPromotionService(
        run_repository=run_repository,
        strategy_version_service=strategy_version_service,
    )
    yield service, run_repository, strategy_version_service
    shutil.rmtree(temp_dir)


def _sample_result(total_return=0.08, sharpe_ratio=1.2):
    snapshot = RecommendationSnapshotDTO(
        as_of_date="2026-01-02",
        profile_id="balanced",
        strategy_config={"buy_score": 70, "enable_volume": True},
        regime="Trend",
        recommendations=[{"stock_code": "2330", "total_score": 92.0}],
    )
    holding = PeriodHoldingDTO(
        rebalance_date="2026-01-02",
        stock_code="2330",
        stock_name="台積電",
        rank=1,
        total_score=92.0,
        factor_scores={"technical": 90.0},
        allocation_amount=100000.0,
        allocation_weight=1.0,
        entry_date="2026-01-02",
        entry_price=100.0,
        planned_exit_date="2026-01-09",
        actual_exit_date="2026-01-09",
        actual_exit_price=108.0,
        exit_reason="holding_period",
        holding_days=5,
        return_pct=0.08,
    )
    contribution = StockContributionDTO(
        stock_code="2330",
        stock_name="台積電",
        selected_count=1,
        total_pnl=8000.0,
        avg_return_pct=0.08,
        win_rate=1.0,
        worst_return_pct=0.08,
    )
    return RecommendationPortfolioBacktestResultDTO(
        summary={
            "total_return": total_return,
            "max_drawdown": -0.03,
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": 1.8,
            "total_trades": 1,
        },
        equity_curve=pd.DataFrame(
            [
                {"date": "2026-01-02", "portfolio_value": 100000.0},
                {"date": "2026-01-09", "portfolio_value": 108000.0},
            ]
        ),
        trades=pd.DataFrame([{"stock_code": "2330", "return_pct": 0.08}]),
        snapshots=[snapshot],
        period_holdings=[holding],
        stock_contribution=[contribution],
        improvement_hints=["維持現有參數，觀察跨期穩定性。"],
    )


def test_promote_saved_portfolio_run_creates_strategy_version(promotion_fixture):
    service, run_repository, strategy_version_service = promotion_fixture
    run_id = run_repository.save_run(
        run_id="port_run_for_promotion",
        run_name="平衡型推薦組合",
        profile_id="balanced",
        start_date="2026-01-02",
        end_date="2026-01-09",
        initial_capital=100000.0,
        rebalance_frequency="weekly",
        top_n=5,
        allocation_method="score_weight",
        holding_days=5,
        stop_loss_pct=0.05,
        take_profit_pct=0.12,
        result=_sample_result(),
        notes="promote 測試",
    )

    version_id = service.promote_to_strategy_version(run_id, notes="納入策略版本")

    assert version_id is not None
    version = strategy_version_service.get_version(version_id)
    assert version is not None
    assert version.strategy_id == "recommendation_portfolio:balanced"
    assert version.source_run_id == run_id
    assert version.profile_id == "balanced"
    assert version.params["top_n"] == 5
    assert version.params["holding_days"] == 5
    assert version.config["recommendation_config"]["buy_score"] == 70
    assert version.backtest_summary["total_return"] == 0.08
    assert "維持現有參數" in version.notes
    assert run_repository.list_runs()[0]["promoted_version_id"] == version_id


def test_promote_rejects_unprofitable_portfolio_run(promotion_fixture):
    service, run_repository, strategy_version_service = promotion_fixture
    run_id = run_repository.save_run(
        run_id="port_run_loss",
        run_name="虧損推薦組合",
        profile_id="balanced",
        start_date="2026-01-02",
        end_date="2026-01-09",
        initial_capital=100000.0,
        rebalance_frequency="weekly",
        top_n=5,
        allocation_method="equal_weight",
        holding_days=5,
        stop_loss_pct=None,
        take_profit_pct=None,
        result=_sample_result(total_return=-0.02, sharpe_ratio=-0.5),
    )

    version_id = service.promote_to_strategy_version(run_id)

    assert version_id is None
    assert strategy_version_service.list_versions() == []
    assert run_repository.list_runs()[0]["promoted_version_id"] is None
