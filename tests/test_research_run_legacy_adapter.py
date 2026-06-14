from types import SimpleNamespace

import pandas as pd

from app_module.research_run_service import ResearchRunService
from data_module.config import TWStockConfig


def _config(tmp_path):
    return TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")


def _legacy_backtest_run():
    return SimpleNamespace(
        run_id="legacy-backtest-001",
        run_name="Legacy Backtest",
        stock_code="2330",
        start_date="2026-01-01",
        end_date="2026-03-31",
        strategy_id="baseline_score",
        strategy_params={"buy_score": 55, "sell_score": 45},
        capital=1000000.0,
        fee_bps=14.25,
        slippage_bps=5.0,
        stop_loss_pct=None,
        take_profit_pct=None,
        total_return=0.12,
        annual_return=0.18,
        sharpe_ratio=1.1,
        max_drawdown=-0.08,
        total_trades=3,
        created_at="2026-06-14T12:00:00",
    )


class _FakeBacktestRepository:
    def __init__(self):
        self.run = _legacy_backtest_run()

    def list_runs(self):
        return [{"run_id": self.run.run_id}]

    def load_run(self, run_id):
        assert run_id == self.run.run_id
        return self.run

    def load_run_data(self, run_id):
        assert run_id == self.run.run_id
        return {
            "equity_curve": pd.DataFrame({"日期": ["2026-01-02"], "portfolio_value": [1000000]}),
            "trade_list": pd.DataFrame({"日期": ["2026-01-05"], "stock_code": ["2330"]}),
        }


def test_backtest_legacy_mapping_preserves_unknown_metadata():
    from app_module.research_run_legacy_adapter import ResearchRunLegacyAdapter

    adapter = ResearchRunLegacyAdapter()
    metadata, equity, trades = adapter.from_backtest_run(
        _legacy_backtest_run(),
        {
            "equity_curve": pd.DataFrame({"日期": ["2026-01-02"], "portfolio_value": [1000000]}),
            "trade_list": pd.DataFrame({"日期": ["2026-01-05"], "stock_code": ["2330"]}),
        },
    )

    assert metadata.run_id == "legacy-backtest:legacy-backtest-001"
    assert metadata.strategy_version == "unknown"
    assert metadata.parameter_contract_version == "unknown"
    assert metadata.original_input["legacy_run_id"] == "legacy-backtest-001"
    assert metadata.original_input["source_repository"] == "BacktestRunRepository"
    assert "strategy_version" in metadata.fallback_reason["missing_metadata"]
    assert metadata.capital_cents == 100000000
    assert metadata.fee_bp_x100 == 1425
    assert metadata.slippage_bp_x100 == 500
    assert equity.shape == (1, 2)
    assert trades.shape == (1, 2)


def test_backfill_dry_run_and_apply_are_explicit_and_idempotent(tmp_path):
    from scripts.backfill_legacy_runs import backfill_legacy_runs

    config = _config(tmp_path)
    service = ResearchRunService(config)
    legacy_repo = _FakeBacktestRepository()

    dry_summary = backfill_legacy_runs(
        config,
        apply=False,
        backtest_repository=legacy_repo,
        portfolio_repository=None,
        service=service,
    )
    assert dry_summary.planned == 1
    assert dry_summary.saved == 0
    assert service.list_runs(include_archived=True) == []

    first_apply = backfill_legacy_runs(
        config,
        apply=True,
        backtest_repository=legacy_repo,
        portfolio_repository=None,
        service=service,
    )
    second_apply = backfill_legacy_runs(
        config,
        apply=True,
        backtest_repository=legacy_repo,
        portfolio_repository=None,
        service=service,
    )

    assert first_apply.saved == 1
    assert second_apply.saved == 1
    assert [run.run_id for run in service.list_runs(include_archived=True)] == [
        "legacy-backtest:legacy-backtest-001"
    ]
