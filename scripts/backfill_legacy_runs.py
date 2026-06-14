"""Backfill legacy research runs into the unified Research Run Registry."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from app_module.research_run_legacy_adapter import ResearchRunLegacyAdapter
from app_module.research_run_service import ResearchRunService
from data_module.config import TWStockConfig


@dataclass(frozen=True)
class BackfillSummary:
    planned: int = 0
    saved: int = 0
    skipped: int = 0
    errors: int = 0


def backfill_legacy_runs(
    config: TWStockConfig,
    *,
    apply: bool = False,
    backtest_repository: Any | None = None,
    portfolio_repository: Any | None = None,
    service: ResearchRunService | None = None,
) -> BackfillSummary:
    adapter = ResearchRunLegacyAdapter()
    service = service or ResearchRunService(config)
    planned = 0
    saved = 0
    skipped = 0
    errors = 0

    if backtest_repository is None:
        from app_module.backtest_repository import BacktestRunRepository

        backtest_repository = BacktestRunRepository(config)
    if portfolio_repository is None:
        from app_module.recommendation_portfolio_run_repository import (
            RecommendationPortfolioRunRepository,
        )

        portfolio_repository = RecommendationPortfolioRunRepository(config)

    for run_summary in backtest_repository.list_runs():
        planned += 1
        try:
            run_id = run_summary["run_id"] if isinstance(run_summary, dict) else run_summary.run_id
            legacy_run = backtest_repository.load_run(run_id)
            legacy_data = backtest_repository.load_run_data(run_id) or {}
            if legacy_run is None:
                skipped += 1
                continue
            metadata, equity, trades = adapter.from_backtest_run(legacy_run, legacy_data)
            if apply:
                service.save_run(metadata, equity, trades)
                saved += 1
        except Exception:
            errors += 1

    for run_summary in portfolio_repository.list_runs():
        planned += 1
        try:
            run_id = run_summary["run_id"] if isinstance(run_summary, dict) else run_summary.run_id
            legacy_run = portfolio_repository.load_run(run_id)
            if legacy_run is None:
                skipped += 1
                continue
            metadata, equity, trades = adapter.from_recommendation_portfolio_run(legacy_run)
            if apply:
                service.save_run(metadata, equity, trades)
                saved += 1
        except Exception:
            errors += 1

    return BackfillSummary(planned=planned, saved=saved, skipped=skipped, errors=errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy research runs.")
    parser.add_argument("--apply", action="store_true", help="明確寫入 Research Run Registry")
    args = parser.parse_args()

    config = TWStockConfig()
    summary = backfill_legacy_runs(config, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"{mode}: planned={summary.planned}, saved={summary.saved}, "
        f"skipped={summary.skipped}, errors={summary.errors}"
    )
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
