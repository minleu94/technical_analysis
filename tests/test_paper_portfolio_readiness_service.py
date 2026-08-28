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
from app_module.paper_portfolio_readiness_service import (
    PaperPortfolioReadinessService,
)
import app_module.paper_portfolio_readiness_service as paper_readiness
from app_module.paper_trade_ledger import PaperTradeFill, PaperTradeLedgerRepository
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from scripts.inspect_paper_portfolio_readiness import main as inspect_readiness_main


def _snapshot(snapshot_id: str, decision_date: str, total_value: str) -> PaperPortfolioSnapshot:
    return PaperPortfolioSnapshot(
        snapshot_id=snapshot_id,
        portfolio_id="paper-main",
        decision_date=decision_date,
        source_result_id="rec-1",
        cash=Decimal("100.00"),
        total_value=Decimal(total_value),
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


def _status(path: Path, *, snapshot: PaperPortfolioSnapshot, state_db: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "paper-portfolio-daily-status.v1",
                "status": "passed",
                "snapshot_id": snapshot.snapshot_id,
                "decision_date": snapshot.decision_date,
                "cash": str(snapshot.cash),
                "total_value": str(snapshot.total_value),
                "state_db": str(state_db.resolve()),
                "writes_market_db": False,
                "auto_rebalance_allowed": False,
                "changes_advice": False,
                "broker_execution": False,
                "diagnostics": ["t_minus_one_visible_price:2330:2026-08-20"],
            }
        ),
        encoding="utf-8",
    )


def test_missing_paper_inputs_are_not_configured_without_creating_files(tmp_path: Path) -> None:
    result = PaperPortfolioReadinessService(output_root=tmp_path / "output").inspect()

    assert result.status == "not_configured"
    assert "paper_daily_status_missing" in result.blockers
    assert "paper_snapshot_db_missing" in result.blockers
    assert "equal_weight_benchmark_db_missing" in result.blockers
    assert not (tmp_path / "output" / "paper_portfolio").exists()
    assert result.read_only is True
    assert result.writes_allowed is False


def test_readiness_reads_snapshots_and_benchmark_without_mutating_databases(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    state_db = output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    status_path = output_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    benchmark_db = output_root / "paper_portfolio" / "equal_weight.sqlite"

    repository = PaperPortfolioSnapshotRepository(state_db)
    first = _snapshot("paper-main-20260820", "2026-08-20", "1000.00")
    latest = _snapshot("paper-main-20260821", "2026-08-21", "1100.00")
    repository.append(first)
    repository.append(latest)
    _status(status_path, snapshot=latest, state_db=state_db)

    benchmark_service = EqualWeightBenchmarkService()
    benchmark_ledger = EqualWeightBenchmarkLedger(benchmark_db)
    benchmark = benchmark_service.create_baseline(
        benchmark_id="paper-main-equal",
        decision_date="2026-08-20",
        capital=Decimal("1000.00"),
        prices={"2330": Decimal("900.00")},
    )
    benchmark_ledger.append(benchmark)
    benchmark_ledger.append(
        benchmark_service.mark(
            prior=benchmark,
            decision_date="2026-08-21",
            prices=(
                PaperPriceObservation(
                    "2330",
                    "2026-08-21",
                    "2026-08-21",
                    Decimal("900.00"),
                ),
            ),
        )
    )

    state_size = state_db.stat().st_size
    benchmark_size = benchmark_db.stat().st_size
    result = PaperPortfolioReadinessService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
    ).inspect()

    assert result.status == "partial"
    assert result.latest_status == "passed"
    assert result.snapshot_count == 2
    assert result.latest_snapshot_id == latest.snapshot_id
    assert result.latest_total_value == Decimal("1100.00")
    assert result.latest_cash == Decimal("100.00")
    assert result.latest_position_count == 1
    assert result.benchmark_observation_count == 2
    assert result.benchmark_ready is True
    assert result.weekly_report_status == "not_computable_cost_ledger_missing"
    assert "paper_trade_cost_ledger_not_configured" in result.warnings
    assert state_db.stat().st_size == state_size
    assert benchmark_db.stat().st_size == benchmark_size


def test_future_snapshot_is_degraded_and_never_counts_as_current_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    state_db = output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    status_path = output_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    repository = PaperPortfolioSnapshotRepository(state_db)
    first = _snapshot("paper-main-20260820", "2026-08-20", "1000.00")
    future = _snapshot("paper-main-20260821", "2026-08-21", "1100.00")
    repository.append(first)
    repository.append(future)
    _status(status_path, snapshot=future, state_db=state_db)
    monkeypatch.setattr(paper_readiness, "paper_portfolio_today", lambda: date(2026, 8, 20))

    result = PaperPortfolioReadinessService(output_root=output_root).inspect()

    assert result.status == "degraded"
    assert "paper_snapshot_future_dated" in result.blockers
    assert "paper_daily_status_future_dated" in result.blockers
    assert any("paper_snapshot_future_date:2026-08-21" in item for item in result.diagnostics)
    assert result.latest_snapshot_id == first.snapshot_id
    assert result.latest_snapshot_date == first.decision_date
    assert result.latest_total_value == first.total_value
    assert result.latest_position_count == len(first.positions)
    assert result.weekly_report_status == "not_computable_future_dated"
    assert any("future_rows_excluded_from_current_projection:1" in item for item in result.diagnostics)


def test_readiness_accepts_complete_cost_ledger_for_weekly_report(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    state_db = output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    status_path = output_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    benchmark_db = output_root / "paper_portfolio" / "equal_weight.sqlite"
    cost_db = output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"

    repository = PaperPortfolioSnapshotRepository(state_db)
    first = _snapshot("paper-main-20260820", "2026-08-20", "1000.00")
    latest = _snapshot("paper-main-20260821", "2026-08-21", "1100.00")
    repository.append(first)
    repository.append(latest)
    _status(status_path, snapshot=latest, state_db=state_db)

    benchmark_service = EqualWeightBenchmarkService()
    benchmark_ledger = EqualWeightBenchmarkLedger(benchmark_db)
    benchmark = benchmark_service.create_baseline(
        benchmark_id="paper-main-equal",
        decision_date="2026-08-20",
        capital=Decimal("1000.00"),
        prices={"2330": Decimal("900.00")},
    )
    benchmark_ledger.append(benchmark)
    benchmark_ledger.append(
        benchmark_service.mark(
            prior=benchmark,
            decision_date="2026-08-21",
            prices=(PaperPriceObservation("2330", "2026-08-21", "2026-08-21", Decimal("900.00")),),
        )
    )
    PaperTradeLedgerRepository(cost_db).append(
        PaperTradeFill(
            fill_id="fill-1",
            order_id="order-1",
            portfolio_id="paper-main",
            event_date="2026-08-20",
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

    result = PaperPortfolioReadinessService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).inspect()

    assert result.status == "ready"
    assert result.cost_ledger_status == "ready"
    assert result.cost_record_count == 1
    assert result.cost_total_cost == Decimal("1.10")
    assert result.filled_event_count == 1
    assert result.weekly_report_status == "ready"
    assert "paper_trade_cost_ledger_not_configured" not in result.warnings


def test_incomplete_cost_ledger_is_visible_and_not_weekly_ready(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    state_db = output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    status_path = output_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    benchmark_db = output_root / "paper_portfolio" / "equal_weight.sqlite"
    cost_db = output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"
    repository = PaperPortfolioSnapshotRepository(state_db)
    first = _snapshot("paper-main-20260820", "2026-08-20", "1000.00")
    latest = _snapshot("paper-main-20260821", "2026-08-21", "1100.00")
    repository.append(first)
    repository.append(latest)
    _status(status_path, snapshot=latest, state_db=state_db)

    benchmark_service = EqualWeightBenchmarkService()
    benchmark_ledger = EqualWeightBenchmarkLedger(benchmark_db)
    benchmark = benchmark_service.create_baseline(
        benchmark_id="paper-main-equal",
        decision_date="2026-08-20",
        capital=Decimal("1000.00"),
        prices={"2330": Decimal("900.00")},
    )
    benchmark_ledger.append(benchmark)
    benchmark_ledger.append(
        benchmark_service.mark(
            prior=benchmark,
            decision_date="2026-08-21",
            prices=(PaperPriceObservation("2330", "2026-08-21", "2026-08-21", Decimal("900.00")),),
        )
    )
    PaperTradeLedgerRepository(cost_db).append(
        PaperTradeFill(
            fill_id="fill-incomplete",
            order_id="order-incomplete",
            portfolio_id="paper-main",
            event_date="2026-08-20",
            stock_code="2330",
            side="buy",
            requested_quantity=1,
            filled_quantity=1,
            reference_price=Decimal("900.00"),
            fill_price=Decimal("900.10"),
            commission=Decimal("1.00"),
            tax=Decimal("0.00"),
            slippage_cost=Decimal("0.10"),
            turnover_bp=None,
            execution_gap_bp=1,
            status="filled",
            source_event_id="event-incomplete",
        )
    )

    result = PaperPortfolioReadinessService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).inspect()

    assert result.status == "partial"
    assert result.cost_ledger_status == "partial"
    assert result.missing_turnover_count == 1
    assert result.weekly_report_status == "not_computable_cost_ledger_incomplete"
    assert "paper_trade_ledger_fields_incomplete" in result.warnings


def test_future_dated_cost_event_is_invalid_and_never_counts_as_ready(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(paper_readiness, "paper_portfolio_today", lambda: date(2026, 8, 20))
    output_root = tmp_path / "output"
    cost_db = output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"
    PaperTradeLedgerRepository(cost_db).append(
        PaperTradeFill(
            fill_id="future-fill",
            order_id="future-order",
            portfolio_id="paper-main",
            event_date="2026-08-21",
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
            source_event_id="future-event",
        )
    )

    result = PaperPortfolioReadinessService(
        output_root=output_root,
        cost_ledger_db_path=cost_db,
    ).inspect()

    assert result.cost_ledger_status == "invalid"
    assert result.future_dated_event_count == 1
    assert "paper_trade_ledger_future_dated" in result.blockers
    # cost_record_count preserves the raw ledger row for auditability; the
    # future-dated row is still excluded from valid cost totals/readiness.
    assert result.cost_record_count == 1
    assert result.cost_total_cost is None
    assert any("paper_trade_ledger_future_date:2026-08-21" in item for item in result.diagnostics)


def test_misaligned_benchmark_boundaries_are_not_weekly_ready(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    state_db = output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    status_path = output_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    benchmark_db = output_root / "paper_portfolio" / "equal_weight.sqlite"
    cost_db = output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"

    repository = PaperPortfolioSnapshotRepository(state_db)
    first = _snapshot("paper-main-20260820", "2026-08-20", "1000.00")
    latest = _snapshot("paper-main-20260821", "2026-08-21", "1100.00")
    repository.append(first)
    repository.append(latest)
    _status(status_path, snapshot=latest, state_db=state_db)

    benchmark_service = EqualWeightBenchmarkService()
    benchmark_ledger = EqualWeightBenchmarkLedger(benchmark_db)
    benchmark = benchmark_service.create_baseline(
        benchmark_id="paper-main-equal",
        decision_date="2026-08-19",
        capital=Decimal("1000.00"),
        prices={"2330": Decimal("900.00")},
    )
    benchmark_ledger.append(benchmark)
    benchmark_ledger.append(
        benchmark_service.mark(
            prior=benchmark,
            decision_date="2026-08-21",
            prices=(PaperPriceObservation("2330", "2026-08-21", "2026-08-21", Decimal("900.00")),),
        )
    )
    PaperTradeLedgerRepository(cost_db).append(
        PaperTradeFill(
            fill_id="fill-aligned-cost",
            order_id="order-aligned-cost",
            portfolio_id="paper-main",
            event_date="2026-08-20",
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
            source_event_id="event-aligned-cost",
        )
    )

    result = PaperPortfolioReadinessService(
        output_root=output_root,
        benchmark_db_path=benchmark_db,
        cost_ledger_db_path=cost_db,
    ).inspect()

    assert result.status == "degraded"
    assert result.weekly_report_status == "not_computable_boundary_mismatch"
    assert "paper_weekly_report_boundary_mismatch" in result.blockers


def test_cost_ledger_without_expected_table_is_schema_invalid(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    cost_db = output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"
    cost_db.parent.mkdir(parents=True)
    with sqlite3.connect(cost_db):
        pass

    result = PaperPortfolioReadinessService(
        output_root=output_root,
        cost_ledger_db_path=cost_db,
    ).inspect()

    assert result.cost_ledger_status == "invalid"
    assert "paper_trade_ledger_schema_mismatch" in result.blockers
    assert "paper_trade_ledger_table_missing" in result.diagnostics


def test_cost_ledger_noncanonical_safety_flag_is_invalid(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    cost_db = output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"
    PaperTradeLedgerRepository(cost_db).append(
        PaperTradeFill(
            fill_id="fill-unsafe-flag",
            order_id="order-unsafe-flag",
            portfolio_id="paper-main",
            event_date="2026-08-20",
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
            source_event_id="event-unsafe-flag",
        )
    )
    with sqlite3.connect(cost_db) as connection:
        connection.execute(
            "UPDATE paper_trade_ledger SET research_only = 2 WHERE fill_id = ?",
            ("fill-unsafe-flag",),
        )

    result = PaperPortfolioReadinessService(
        output_root=output_root,
        cost_ledger_db_path=cost_db,
    ).inspect()

    assert result.cost_ledger_status == "invalid"
    assert "paper_trade_ledger_invalid_row" in result.blockers


def test_status_boundary_or_snapshot_mismatch_degrades_readiness(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    state_db = output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    status_path = output_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    repository = PaperPortfolioSnapshotRepository(state_db)
    latest = _snapshot("paper-main-20260821", "2026-08-21", "1100.00")
    repository.append(latest)
    _status(status_path, snapshot=latest, state_db=state_db)
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    payload["snapshot_id"] = "paper-main-other"
    payload["broker_execution"] = True
    status_path.write_text(json.dumps(payload), encoding="utf-8")

    result = PaperPortfolioReadinessService(output_root=output_root).inspect()

    assert result.status == "degraded"
    assert "paper_daily_status_snapshot_mismatch" in result.blockers
    assert "paper_daily_status_boundary_violation:broker_execution" in result.blockers


def test_invalid_status_json_is_fail_closed(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    status_path = output_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text("not-json", encoding="utf-8")

    result = PaperPortfolioReadinessService(output_root=output_root).inspect()

    assert result.status == "degraded"
    assert result.latest_status == "invalid"
    assert "paper_daily_status_invalid" in result.blockers


def test_readiness_cli_is_read_only_and_returns_machine_payload(tmp_path: Path, capsys) -> None:
    exit_code = inspect_readiness_main(
        ["--output-root", str(tmp_path / "output"), "--format", "json"]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "paper-portfolio-readiness.v1"
    assert payload["status"] == "not_configured"
    assert payload["writes_allowed"] is False
    assert not (tmp_path / "output").exists()
