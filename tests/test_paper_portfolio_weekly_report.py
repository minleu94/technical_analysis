from decimal import Decimal

from app_module.paper_equal_weight_benchmark_ledger import EqualWeightBenchmarkEntry
from app_module.paper_portfolio_snapshot_repository import PaperPortfolioSnapshot
from app_module.paper_portfolio_weekly_report import (
    PaperTradeCostRecord,
    PaperPortfolioWeeklyReportService,
)


def _snapshot(day: str, value: str) -> PaperPortfolioSnapshot:
    return PaperPortfolioSnapshot(
        snapshot_id=f"p-{day}",
        portfolio_id="paper-main",
        decision_date=day,
        source_result_id="rec-1",
        cash=Decimal(value),
        total_value=Decimal(value),
        positions=(),
    )


def _benchmark(day: str, value: str) -> EqualWeightBenchmarkEntry:
    return EqualWeightBenchmarkEntry("b", day, ("2330",), (("2330", Decimal("1")),), Decimal(value))


def test_weekly_report_separates_gross_and_cost_adjusted_returns() -> None:
    report = PaperPortfolioWeeklyReportService().build(
        portfolio_snapshots=(_snapshot("2026-07-06", "100000"), _snapshot("2026-07-10", "102000")),
        benchmark_entries=(_benchmark("2026-07-06", "100000"), _benchmark("2026-07-10", "101000")),
        trade_costs=(PaperTradeCostRecord("2026-07-08", Decimal("200"), 500),),
        expected_trading_days=5,
    )

    assert report.gross_return_bp == 200
    assert report.net_return_bp == 180
    assert report.benchmark_return_bp == 100
    assert report.net_excess_return_bp == 80
    assert report.total_cost == Decimal("200.00")
    assert report.turnover_bp == 500
    assert report.investment_effectiveness_claim is False


def test_incomplete_week_is_disclosed_not_silently_complete() -> None:
    report = PaperPortfolioWeeklyReportService().build(
        portfolio_snapshots=(_snapshot("2026-07-06", "100000"), _snapshot("2026-07-10", "102000")),
        benchmark_entries=(_benchmark("2026-07-06", "100000"), _benchmark("2026-07-10", "101000")),
        trade_costs=(),
        expected_trading_days=5,
    )

    assert report.observed_trading_days == 2
    assert report.data_quality == "DEGRADED"
    assert "incomplete_trading_week" in report.warnings


def test_report_requires_aligned_boundary_dates() -> None:
    try:
        PaperPortfolioWeeklyReportService().build(
            portfolio_snapshots=(_snapshot("2026-07-06", "100000"), _snapshot("2026-07-10", "102000")),
            benchmark_entries=(_benchmark("2026-07-07", "100000"), _benchmark("2026-07-10", "101000")),
            trade_costs=(),
            expected_trading_days=5,
        )
    except ValueError as exc:
        assert "aligned boundary dates" in str(exc)
    else:
        raise AssertionError("unaligned report should fail")
