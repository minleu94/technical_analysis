import pytest
import tempfile
import shutil
from pathlib import Path
import pandas as pd

from app_module.recommendation_portfolio_dtos import (
    RecommendationPortfolioBacktestResultDTO,
    PeriodHoldingDTO,
    StockContributionDTO,
    RecommendationSnapshotDTO,
)
from app_module.recommendation_portfolio_run_repository import (
    RecommendationPortfolioRunRepository,
)

class DummyConfig:
    def __init__(self, temp_dir):
        self.temp_dir = Path(temp_dir)
        
    def resolve_output_path(self, relative_path: str) -> Path:
        p = self.temp_dir / relative_path
        p.mkdir(parents=True, exist_ok=True)
        return p


@pytest.fixture
def repo_fixture():
    temp_dir = tempfile.mkdtemp()
    config = DummyConfig(temp_dir)
    repo = RecommendationPortfolioRunRepository(config)
    yield repo, temp_dir
    shutil.rmtree(temp_dir)


def test_repository_save_load_list_delete(repo_fixture):
    repo, temp_dir = repo_fixture
    
    # 建立一個測試用的 DTO
    snapshot = RecommendationSnapshotDTO(
        as_of_date="2026-01-02",
        profile_id="momentum",
        strategy_config={"param1": 123},
        regime="Trend",
        recommendations=[{"stock_code": "2330", "total_score": 90.0}],
    )
    holding = PeriodHoldingDTO(
        rebalance_date="2026-01-02",
        stock_code="2330",
        stock_name="台積電",
        rank=1,
        total_score=90.0,
        factor_scores={},
        allocation_amount=100000.0,
        allocation_weight=1.0,
        entry_date="2026-01-02",
        entry_price=100.0,
        planned_exit_date="2026-01-06",
        actual_exit_date="2026-01-06",
        actual_exit_price=105.0,
        exit_reason="holding_period",
        holding_days=4,
        return_pct=0.05,
    )
    contribution = StockContributionDTO(
        stock_code="2330",
        stock_name="台積電",
        selected_count=1,
        total_pnl=5000.0,
        win_rate=1.0,
        worst_return_pct=0.05,
        avg_return_pct=0.05,
    )
    result = RecommendationPortfolioBacktestResultDTO(
        summary={"total_return": 0.05, "max_drawdown": -0.02, "sharpe_ratio": 1.5, "sortino_ratio": 2.0, "total_trades": 1},
        equity_curve=pd.DataFrame([{"date": "2026-01-02", "equity": 100000.0}, {"date": "2026-01-06", "equity": 105000.0}]),
        trades=pd.DataFrame([{"stock_code": "2330", "side": "buy"}]),
        snapshots=[snapshot],
        period_holdings=[holding],
        stock_contribution=[contribution],
        selection_diagnostics=[],
        improvement_hints=["💡 建議放寬停損。"],
    )
    
    # 1. 測試 save_run
    run_id = repo.save_run(
        run_name="測試回測紀錄",
        profile_id="momentum",
        start_date="2026-01-02",
        end_date="2026-01-06",
        initial_capital=100000.0,
        rebalance_frequency="once",
        top_n=1,
        allocation_method="equal_weight",
        holding_days=4,
        stop_loss_pct=0.05,
        take_profit_pct=None,
        result=result,
        notes="這是一筆測試備註"
    )
    
    assert run_id.startswith("port_run_")
    
    # 2. 測試 list_runs
    runs = repo.list_runs()
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert runs[0]["run_name"] == "測試回測紀錄"
    assert runs[0]["total_return"] == 0.05
    assert runs[0]["notes"] == "這是一筆測試備註"
    
    # 3. 測試 load_run
    loaded = repo.load_run(run_id)
    assert loaded is not None
    assert loaded["run_name"] == "測試回測紀錄"
    assert loaded["notes"] == "這是一筆測試備註"
    assert loaded["config"]["profile_id"] == "momentum"
    
    # 還原的 DTO 檢查
    dto = loaded["result_dto"]
    assert isinstance(dto, RecommendationPortfolioBacktestResultDTO)
    assert dto.summary["total_return"] == 0.05
    assert len(dto.period_holdings) == 1
    assert dto.period_holdings[0].stock_code == "2330"
    assert dto.period_holdings[0].pnl() == 5000.0
    assert dto.improvement_hints == ["💡 建議放寬停損。"]
    assert not dto.equity_curve.empty
    assert dto.equity_curve.iloc[1]["equity"] == 105000.0
    
    # 4. 測試 delete_run
    deleted = repo.delete_run(run_id)
    assert deleted is True
    
    # 確保刪除後資料庫與檔案被清空
    assert repo.load_run(run_id) is None
    assert len(repo.list_runs()) == 0
    # 確保 JSON 檔案被刪除
    json_file = Path(loaded["data_path"])
    assert not json_file.exists()
