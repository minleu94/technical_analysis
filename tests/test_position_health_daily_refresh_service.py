from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from app_module.position_health_daily_refresh_service import (
    PositionHealthDailyRefreshService,
)


def _make_state(path: Path, *, snapshot_id: str = "paper-main-20260907", weight_bp: int = 1500) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE paper_portfolio_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                source_result_id TEXT NOT NULL,
                cash TEXT NOT NULL,
                total_value TEXT NOT NULL
            );
            CREATE TABLE paper_portfolio_positions (
                snapshot_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                mark_price TEXT NOT NULL,
                market_value TEXT NOT NULL,
                weight_bp INTEGER NOT NULL,
                PRIMARY KEY (snapshot_id, stock_code)
            );
            """
        )
        connection.execute(
            "INSERT INTO paper_portfolio_snapshots VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot_id, "paper-main", "2026-09-07", "eod-20260907", "100000", "200000"),
        )
        connection.executemany(
            "INSERT INTO paper_portfolio_positions VALUES (?, ?, ?, ?, ?, ?)",
            [
                (snapshot_id, "1615", 1000, "48.95", "48950", weight_bp),
                (snapshot_id, "2330", 0, "1000.00", "0", 0),
            ],
        )


def _append_snapshot(
    path: Path,
    *,
    snapshot_id: str = "paper-main-20260908",
    decision_date: str = "2026-09-08",
    quantity: int = 1000,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO paper_portfolio_snapshots VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot_id, "paper-main", decision_date, f"eod-{decision_date.replace('-', '')}", "100000", "200000"),
        )
        connection.execute(
            "INSERT INTO paper_portfolio_positions VALUES (?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                "1615",
                quantity,
                "48.95",
                str((Decimal(quantity) * Decimal("48.95")).quantize(Decimal("0.01"))),
                1500,
            ),
        )


def _ledger_row(
    *,
    token: str,
    event_date: str,
    stock_code: str,
    side: str,
    filled_quantity: int,
    status: str,
) -> tuple[object, ...]:
    return (
        "paper-trade-ledger.v1",
        f"fill-{token}",
        f"order-{token}",
        "paper-main",
        event_date,
        stock_code,
        side,
        filled_quantity,
        filled_quantity,
        "10.00",
        "10.00",
        "0.00",
        "0.00",
        "0.00",
        0,
        0,
        status,
        f"event-{token}",
        None,
        "paper_simulation",
        1,
        0,
        0,
    )


def _make_ledger(path: Path, rows: list[tuple[object, ...]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE paper_trade_ledger (
                schema_version TEXT NOT NULL,
                fill_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                portfolio_id TEXT NOT NULL,
                event_date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                side TEXT NOT NULL,
                requested_quantity INTEGER NOT NULL,
                filled_quantity INTEGER NOT NULL,
                reference_price TEXT NOT NULL,
                fill_price TEXT,
                commission TEXT NOT NULL,
                tax TEXT NOT NULL,
                slippage_cost TEXT NOT NULL,
                turnover_bp INTEGER,
                execution_gap_bp INTEGER,
                status TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                override_reason TEXT,
                source_type TEXT NOT NULL,
                research_only INTEGER NOT NULL,
                broker_order_allowed INTEGER NOT NULL,
                auto_rebalance_allowed INTEGER NOT NULL
            )
            """
        )
        if rows:
            connection.executemany(
                "INSERT INTO paper_trade_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )


def _write_status(
    path: Path,
    state_db: Path,
    *,
    snapshot_id: str = "paper-main-20260907",
    decision_date: str = "2026-09-07",
    ledger_db: Path | None = None,
) -> None:
    resolved_ledger = ledger_db or state_db.parent.parent / "paper_trade_ledger.sqlite"
    path.write_text(
        json.dumps(
            {
                "schema_version": "paper-portfolio-daily-status.v1",
                "producer": "scripts.scheduled.run_paper_portfolio_daily_isolated",
                "status": "passed",
                "decision_date": decision_date,
                "snapshot_id": snapshot_id,
                "portfolio_id": "paper-main",
                "state_db": str(state_db.resolve()),
                "paper_ledger_db": str(resolved_ledger.resolve()),
                "snapshot_appended": True,
                "paper_ledger_transitions_applied": 0,
                "trading_calendar_validated": True,
                "writes_market_db": False,
                "auto_rebalance_allowed": False,
                "changes_advice": False,
                "broker_execution": False,
            }
        ),
        encoding="utf-8",
    )


def test_refresh_uses_one_paper_snapshot_and_preserves_only_existing_human_fields(
    tmp_path: Path,
) -> None:
    state_db = tmp_path / "state" / "paper.sqlite"
    status_path = tmp_path / "status.json"
    output = tmp_path / "health"
    _make_state(state_db)
    _write_status(status_path, state_db)
    previous = output / "baseline_20260712.json"
    previous.parent.mkdir(parents=True)
    previous.write_text(
        json.dumps(
            {
                "decision_date": "2026-07-12",
                "source_snapshot_id": "paper-main-20260907",
                "research_only": True,
                "auto_action_allowed": False,
                "positions": [
                    {
                        "stock_code": "1615",
                        "stock_name": "大山",
                        "state": "WATCH",
                        "entry_thesis": "human supplied thesis",
                        "invalidation": None,
                        "holding_horizon": None,
                        "review_date": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = state_db.read_bytes()

    receipt = PositionHealthDailyRefreshService(
        state_db_path=state_db,
        status_path=status_path,
    ).refresh(
        as_of_date=date(2026, 9, 8),
        output_dir=output,
        previous_baseline_path=previous,
        observed_at=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert receipt["status"] == "passed"
    assert receipt["snapshot_id"] == "paper-main-20260907"
    assert Path(str(receipt["baseline_path"])).name == "baseline_20260907.json"
    baseline = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    assert baseline["decision_date"] == "2026-09-07"
    assert baseline["as_of_date"] == "2026-09-08"
    assert baseline["source_snapshot_rows_sha256"].startswith("sha256:")
    assert len(baseline["positions"]) == 1
    position = baseline["positions"][0]
    assert position["stock_code"] == "1615"
    assert position["stock_name"] == "大山"
    assert position["entry_thesis"] == "human supplied thesis"
    assert position["state"] == "WATCH"
    assert set(position["required_human_fields"]) == {
        "invalidation",
        "holding_horizon",
        "review_date",
    }
    assert "health_transition_not_evaluated" in position["reasons"]
    assert baseline["research_only"] is True
    assert baseline["writes_positions_db"] is False
    assert baseline["auto_action_allowed"] is False
    assert state_db.read_bytes() == before


def test_refresh_does_not_carry_prior_closed_or_thesis_to_unproven_new_entry(
    tmp_path: Path,
) -> None:
    state_db = tmp_path / "state.sqlite"
    status_path = tmp_path / "status.json"
    ledger_db = tmp_path / "paper_trade_ledger.sqlite"
    output = tmp_path / "health"
    _make_state(state_db)
    _write_status(status_path, state_db)
    _make_ledger(ledger_db)
    previous = output / "baseline_20260906.json"
    previous.parent.mkdir(parents=True)
    previous.write_text(
        json.dumps(
            {
                "decision_date": "2026-09-06",
                "source_snapshot_id": "paper-main-20260906",
                "research_only": True,
                "auto_action_allowed": False,
                "positions": [
                    {
                        "stock_code": "1615",
                        "stock_name": "舊持倉",
                        "state": "CLOSED",
                        "entry_thesis": "old entry",
                        "invalidation": "old invalidation",
                        "holding_horizon": 30,
                        "review_date": "2026-09-05",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    receipt = PositionHealthDailyRefreshService(
        state_db_path=state_db,
        status_path=status_path,
        ledger_db_path=ledger_db,
    ).refresh(
        as_of_date=date(2026, 9, 8),
        output_dir=output,
        previous_baseline_path=previous,
    )

    assert receipt["status"] == "passed"
    baseline = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    position = baseline["positions"][0]
    assert position["state"] == "WATCH"
    assert position["entry_thesis"] is None
    assert position["invalidation"] is None
    assert position["holding_horizon"] is None
    assert position["review_date"] is None
    assert position["entry_lineage_status"] == "unproven"
    assert baseline["entry_lineage_verified"] is False
    assert "paper_position_entry_lineage_not_verified" in baseline["warnings"]
    assert any(
        warning.startswith("paper_entry_lineage_coverage_unavailable")
        for warning in baseline["warnings"]
    )


def test_refresh_preserves_human_fields_for_cross_date_continuous_holding(
    tmp_path: Path,
) -> None:
    state_db = tmp_path / "state.sqlite"
    status_path = tmp_path / "status.json"
    ledger_db = tmp_path / "paper_trade_ledger.sqlite"
    output = tmp_path / "health"
    _make_state(state_db)
    _append_snapshot(state_db)
    _write_status(
        status_path,
        state_db,
        snapshot_id="paper-main-20260908",
        decision_date="2026-09-08",
        ledger_db=ledger_db,
    )
    _make_ledger(ledger_db)
    previous = output / "baseline_20260907.json"
    previous.parent.mkdir(parents=True)
    previous.write_text(
        json.dumps(
            {
                "decision_date": "2026-09-07",
                "source_snapshot_id": "paper-main-20260907",
                "research_only": True,
                "auto_action_allowed": False,
                "positions": [
                    {
                        "stock_code": "1615",
                        "stock_name": "大山",
                        "paper_shares": 1000,
                        "state": "EXIT_CANDIDATE",
                        "entry_thesis": "human supplied thesis",
                        "invalidation": "human supplied invalidation",
                        "holding_horizon": 30,
                        "review_date": "2026-09-30",
                        "reasons": ["exit_trigger_from_prior_review"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    receipt = PositionHealthDailyRefreshService(
        state_db_path=state_db,
        status_path=status_path,
        ledger_db_path=ledger_db,
        coverage_status_path=status_path,
    ).refresh(
        as_of_date=date(2026, 9, 8),
        output_dir=output,
        previous_baseline_path=previous,
        observed_at=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert receipt["status"] == "passed"
    baseline = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    position = baseline["positions"][0]
    assert position["entry_lineage_status"] == "ledger_continuous_no_trade"
    assert position["entry_thesis"] == "human supplied thesis"
    assert position["state"] == "EXIT_CANDIDATE"
    assert "exit_trigger_from_prior_review" in position["reasons"]
    assert position["historical_prior_health_fields"]["entry_thesis"] == "human supplied thesis"
    assert baseline["entry_lineage_verified"] is True
    assert baseline["entry_lineage_verified_codes"] == ["1615"]
    assert baseline["entry_lineage_source"]["status"] == "ready"
    assert baseline["entry_lineage_source"]["event_count"] == 0
    assert "paper_position_entry_lineage_not_verified" not in baseline["warnings"]


def test_refresh_rejects_closed_to_reentry_even_when_shares_match(
    tmp_path: Path,
) -> None:
    state_db = tmp_path / "state.sqlite"
    status_path = tmp_path / "status.json"
    ledger_db = tmp_path / "paper_trade_ledger.sqlite"
    output = tmp_path / "health"
    _make_state(state_db)
    _append_snapshot(state_db)
    _write_status(
        status_path,
        state_db,
        snapshot_id="paper-main-20260908",
        decision_date="2026-09-08",
        ledger_db=ledger_db,
    )
    _make_ledger(
        ledger_db,
        rows=[
            _ledger_row(
                token="sell-1615",
                event_date="2026-09-08",
                stock_code="1615",
                side="sell",
                filled_quantity=1000,
                status="filled",
            ),
            _ledger_row(
                token="buy-1615",
                event_date="2026-09-08",
                stock_code="1615",
                side="buy",
                filled_quantity=1000,
                status="filled",
            ),
        ],
    )
    previous = output / "baseline_20260907.json"
    previous.parent.mkdir(parents=True)
    previous.write_text(
        json.dumps(
            {
                "decision_date": "2026-09-07",
                "source_snapshot_id": "paper-main-20260907",
                "research_only": True,
                "auto_action_allowed": False,
                "positions": [
                    {
                        "stock_code": "1615",
                        "stock_name": "舊持倉",
                        "paper_shares": 1000,
                        "state": "CLOSED",
                        "entry_thesis": "old entry",
                        "invalidation": "old invalidation",
                        "holding_horizon": 30,
                        "review_date": "2026-09-05",
                        "reasons": ["prior_exit_filled"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    receipt = PositionHealthDailyRefreshService(
        state_db_path=state_db,
        status_path=status_path,
        ledger_db_path=ledger_db,
        coverage_status_path=status_path,
    ).refresh(
        as_of_date=date(2026, 9, 8),
        output_dir=output,
        previous_baseline_path=previous,
        observed_at=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert receipt["status"] == "passed"
    baseline = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    position = baseline["positions"][0]
    assert position["entry_lineage_status"] == "unproven"
    assert position["state"] == "WATCH"
    assert position["entry_thesis"] is None
    assert position["historical_prior_state"] == "CLOSED"
    assert position["historical_prior_health_fields"]["entry_thesis"] == "old entry"
    assert position["historical_prior_reasons"] == ["prior_exit_filled"]
    assert baseline["entry_lineage_verified"] is False
    assert baseline["entry_lineage_unproven_codes"] == ["1615"]
    assert baseline["entry_lineage_historical_prior_codes"] == ["1615"]
    assert baseline["entry_lineage_source"]["event_count"] == 2
    assert "paper_position_entry_lineage_not_verified" in baseline["warnings"]


def test_refresh_blocks_without_verified_paper_status_and_does_not_create_baseline(
    tmp_path: Path,
) -> None:
    state_db = tmp_path / "state.sqlite"
    status_path = tmp_path / "missing-status.json"
    output = tmp_path / "health"
    _make_state(state_db)

    receipt = PositionHealthDailyRefreshService(
        state_db_path=state_db,
        status_path=status_path,
    ).refresh(as_of_date=date(2026, 9, 8), output_dir=output)

    assert receipt["status"] == "blocked"
    assert any("FileNotFoundError" in str(item) for item in receipt["blockers"])
    assert not (output / "latest.json").exists()
    status = json.loads((output / "latest_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "blocked"
    assert status["writes_positions_db"] is False


def test_refresh_keeps_immutable_history_when_same_date_snapshot_bytes_change(
    tmp_path: Path,
) -> None:
    state_db = tmp_path / "state.sqlite"
    status_path = tmp_path / "status.json"
    output = tmp_path / "health"
    _make_state(state_db)
    _write_status(status_path, state_db)
    service = PositionHealthDailyRefreshService(state_db_path=state_db, status_path=status_path)

    first = service.refresh(as_of_date=date(2026, 9, 8), output_dir=output)
    original = Path(str(first["baseline_path"]))
    with sqlite3.connect(state_db) as connection:
        connection.execute(
            "UPDATE paper_portfolio_positions SET weight_bp = ? WHERE snapshot_id = ? AND stock_code = ?",
            (1750, "paper-main-20260907", "1615"),
        )
    second = service.refresh(as_of_date=date(2026, 9, 8), output_dir=output)

    assert first["status"] == "passed"
    assert second["status"] == "passed"
    assert Path(str(second["baseline_path"])) != original
    assert original.is_file()
    assert Path(str(second["baseline_path"])).is_file()
    latest = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    assert latest["positions"][0]["paper_weight_bp"] == 1750
