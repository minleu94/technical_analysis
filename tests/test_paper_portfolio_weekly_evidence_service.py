from __future__ import annotations

from decimal import Decimal
from datetime import date
import json
from pathlib import Path
import sqlite3

from app_module.paper_equal_weight_benchmark_ledger import (
    EqualWeightBenchmarkLedger,
    EqualWeightBenchmarkService,
)
from app_module.paper_portfolio_daily_runner import PaperPriceObservation
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from app_module.paper_portfolio_weekly_evidence_service import (
    PaperPortfolioWeeklyEvidenceService,
)
import app_module.paper_portfolio_weekly_evidence_service as paper_weekly
from app_module.paper_trade_ledger import PaperTradeFill, PaperTradeLedgerRepository


def _snapshot(snapshot_id: str, day: str, value: str) -> PaperPortfolioSnapshot:
    return PaperPortfolioSnapshot(
        snapshot_id=snapshot_id,
        portfolio_id="paper-main",
        decision_date=day,
        source_result_id="rec-1",
        cash=Decimal("100.00"),
        total_value=Decimal(value),
        positions=(
            PaperPortfolioPositionSnapshot(
                stock_code="2330",
                quantity=1,
                mark_price=Decimal("900.00"),
                market_value=Decimal("900.00"),
                weight_bp=9000,
            ),
        ),
    )


def _build_inputs(tmp_path: Path, *, first: str = "2026-08-20", latest: str = "2026-08-21") -> tuple[Path, Path, Path]:
    output_root = tmp_path / "output"
    state_db = output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    benchmark_db = output_root / "paper_portfolio" / "equal_weight.sqlite"
    cost_db = output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"

    PaperPortfolioSnapshotRepository(state_db).append(_snapshot("p-first", first, "1000.00"))
    PaperPortfolioSnapshotRepository(state_db).append(_snapshot("p-latest", latest, "1100.00"))

    benchmark_service = EqualWeightBenchmarkService()
    benchmark_ledger = EqualWeightBenchmarkLedger(benchmark_db)
    baseline = benchmark_service.create_baseline(
        benchmark_id="paper-main-equal",
        decision_date=first,
        capital=Decimal("1000.00"),
        prices={"2330": Decimal("900.00")},
    )
    benchmark_ledger.append(baseline)
    benchmark_ledger.append(
        benchmark_service.mark(
            prior=baseline,
            decision_date=latest,
            prices=(
                PaperPriceObservation("2330", latest, latest, Decimal("990.00")),
            ),
        )
    )
    PaperTradeLedgerRepository(cost_db).append(
        PaperTradeFill(
            fill_id="fill-1",
            order_id="order-1",
            portfolio_id="paper-main",
            event_date=first,
            stock_code="2330",
            side="buy",
            requested_quantity=1,
            filled_quantity=1,
            reference_price=Decimal("900.00"),
            fill_price=Decimal("900.10"),
            commission=Decimal("1.00"),
            tax=Decimal("0.00"),
            slippage_cost=Decimal("0.10"),
            turnover_bp=100,
            execution_gap_bp=1,
            status="filled",
            source_event_id="event-1",
        )
    )
    return output_root, benchmark_db, cost_db


def test_missing_inputs_are_fail_closed_and_do_not_create_databases(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    result = PaperPortfolioWeeklyEvidenceService(
        output_root=output_root,
        benchmark_db_path=output_root / "paper_portfolio" / "equal_weight.sqlite",
    ).build(
        period_start="2026-08-20",
        period_end="2026-08-21",
        expected_trading_days=2,
    )

    assert result.status == "not_configured"
    assert result.report is None
    assert "paper_snapshot_db_missing" in result.blockers
    assert not (output_root / "paper_portfolio").exists()
    assert result.research_only is True
    assert result.writes_allowed is False


def test_future_weekly_period_is_not_computable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paper_weekly, "paper_portfolio_today", lambda: date(2026, 8, 20))

    result = PaperPortfolioWeeklyEvidenceService(output_root=tmp_path / "output").build(
        period_start="2026-08-20",
        period_end="2026-08-21",
        expected_trading_days=2,
    )

    assert result.status == "not_configured"
    assert result.report is None
    assert "paper_weekly_report_future_period" in result.blockers
    assert any("paper_weekly_report_future_period:2026-08-21" in item for item in result.diagnostics)


def test_adapter_rebuilds_cost_adjusted_report_from_existing_ledgers(tmp_path: Path) -> None:
    output_root, benchmark_db, cost_db = _build_inputs(tmp_path)
    state_db = output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    before = {path: path.stat().st_size for path in (state_db, benchmark_db, cost_db)}

    result = PaperPortfolioWeeklyEvidenceService(
        output_root=output_root,
        state_db_path=state_db,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).build(
        period_start="2026-08-20",
        period_end="2026-08-21",
        expected_trading_days=2,
    )

    assert result.status == "ready"
    assert result.weekly_report_status == "ready"
    assert result.snapshot_count == 2
    assert result.benchmark_observation_count == 2
    assert result.cost_record_count == 1
    assert result.report is not None
    assert result.report.gross_return_bp == 1000
    assert result.report.net_return_bp == 989
    assert result.report.total_cost == Decimal("1.10")
    assert result.report.turnover_bp == 100
    assert result.report.research_only is True
    assert result.report.investment_effectiveness_claim is False
    assert {path: path.stat().st_size for path in (state_db, benchmark_db, cost_db)} == before

    payload = result.to_dict()
    assert payload["schema_version"] == "paper-portfolio-weekly-evidence.v1"
    assert payload["report"]["total_cost"] == "1.10"


def test_latest_helper_uses_observed_boundaries_and_discloses_incomplete_week(tmp_path: Path) -> None:
    output_root, benchmark_db, cost_db = _build_inputs(tmp_path)
    result = PaperPortfolioWeeklyEvidenceService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).build_latest(expected_trading_days=5)

    assert result.status == "partial"
    assert result.period_start == "2026-08-20"
    assert result.period_end == "2026-08-21"
    assert result.report is not None
    assert result.report.observed_trading_days == 2
    assert "incomplete_trading_week" in result.report.warnings


def test_period_boundaries_must_exist_in_both_ledgers(tmp_path: Path) -> None:
    output_root, benchmark_db, cost_db = _build_inputs(tmp_path)
    result = PaperPortfolioWeeklyEvidenceService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).build(
        period_start="2026-08-19",
        period_end="2026-08-21",
        expected_trading_days=3,
    )

    assert result.status == "degraded"
    assert result.report is None
    assert "paper_weekly_report_period_start_snapshot_missing" in result.blockers
    assert "paper_weekly_report_period_start_benchmark_missing" in result.blockers


def test_missing_turnover_is_not_silently_treated_as_zero_cost(tmp_path: Path) -> None:
    output_root, benchmark_db, _cost_db = _build_inputs(tmp_path)
    cost_db = output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"
    with sqlite3.connect(cost_db) as connection:
        connection.execute("UPDATE paper_trade_ledger SET turnover_bp = NULL")

    result = PaperPortfolioWeeklyEvidenceService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).build(
        period_start="2026-08-20",
        period_end="2026-08-21",
        expected_trading_days=2,
    )

    assert result.status == "degraded"
    assert result.report is None
    assert "paper_weekly_report_cost_turnover_missing" in result.blockers


def test_noncanonical_safety_flag_is_invalid(tmp_path: Path) -> None:
    output_root, benchmark_db, cost_db = _build_inputs(tmp_path)
    with sqlite3.connect(cost_db) as connection:
        connection.execute("UPDATE paper_trade_ledger SET research_only = 2")

    result = PaperPortfolioWeeklyEvidenceService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).build(
        period_start="2026-08-20",
        period_end="2026-08-21",
        expected_trading_days=2,
    )

    assert result.status == "degraded"
    assert "paper_trade_ledger_invalid_row" in result.blockers


def test_non_paper_source_is_not_accepted_as_execution_evidence(tmp_path: Path) -> None:
    output_root, benchmark_db, cost_db = _build_inputs(tmp_path)
    with sqlite3.connect(cost_db) as connection:
        connection.execute("UPDATE paper_trade_ledger SET source_type = 'manual_trade'")

    result = PaperPortfolioWeeklyEvidenceService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).build(
        period_start="2026-08-20",
        period_end="2026-08-21",
        expected_trading_days=2,
    )

    assert result.status == "degraded"
    assert "paper_trade_ledger_invalid_row" in result.blockers
    assert any("source_type_not_paper" in item for item in result.diagnostics)


def test_to_dict_is_json_serializable(tmp_path: Path) -> None:
    output_root, benchmark_db, cost_db = _build_inputs(tmp_path)
    result = PaperPortfolioWeeklyEvidenceService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).build(
        period_start="2026-08-20",
        period_end="2026-08-21",
        expected_trading_days=2,
    )

    json.dumps(result.to_dict(), ensure_ascii=False)
