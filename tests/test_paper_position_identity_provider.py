from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from app_module.paper_position_identity_provider import PaperPositionIdentityProvider
from app_module.position_health_daily_refresh_service import PositionHealthDailyRefreshService
from app_module.position_health_transition_evaluator import evaluate_baseline_file


def _make_state(path: Path, snapshots: list[tuple[str, str, dict[str, int]]]) -> None:
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
        for snapshot_id, decision_date, quantities in snapshots:
            connection.execute(
                "INSERT INTO paper_portfolio_snapshots VALUES (?, ?, ?, ?, ?, ?)",
                (snapshot_id, "paper-main", decision_date, f"source-{decision_date}", "100000.00", "200000.00"),
            )
            for stock_code, quantity in sorted(quantities.items()):
                connection.execute(
                    "INSERT INTO paper_portfolio_positions VALUES (?, ?, ?, ?, ?, ?)",
                    (snapshot_id, stock_code, quantity, "10.00", str(quantity * 10), 1000 if quantity else 0),
                )


def _make_ledger(path: Path, rows: list[tuple[object, ...]]) -> None:
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


def _ledger_row(
    *,
    token: str,
    event_date: str,
    stock_code: str,
    side: str,
    quantity: int,
    status: str = "filled",
) -> tuple[object, ...]:
    fill_price: str | None = "10.00" if quantity else None
    return (
        "paper-trade-ledger.v1",
        f"fill-{token}",
        f"order-{token}",
        "paper-main",
        event_date,
        stock_code,
        side,
        quantity,
        quantity,
        "10.00",
        fill_price,
        "0.00",
        "0.00",
        "0.00",
        100,
        0 if quantity else None,
        status,
        f"event-{token}",
        None,
        "paper_daily_execution_delayed_eod_replay_v1",
        1,
        0,
        0,
    )


def _write_status(
    path: Path,
    *,
    state_db: Path,
    ledger_db: Path,
    snapshot_id: str,
    decision_date: str,
    transitions: int,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "paper-portfolio-daily-status.v1",
                "producer": "scripts.scheduled.run_paper_portfolio_daily_isolated",
                "status": "passed",
                "decision_at": f"{decision_date}T08:30:00+08:00",
                "decision_date": decision_date,
                "snapshot_id": snapshot_id,
                "portfolio_id": "paper-main",
                "state_db": str(state_db.resolve()),
                "paper_ledger_db": str(ledger_db.resolve()),
                "snapshot_appended": True,
                "paper_ledger_transitions_applied": transitions,
                "trading_calendar_validated": True,
                "writes_market_db": False,
                "auto_rebalance_allowed": False,
                "changes_advice": False,
                "broker_execution": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _provider(
    state_db: Path,
    ledger_db: Path,
    status_path: Path,
) -> PaperPositionIdentityProvider:
    return PaperPositionIdentityProvider(
        state_db_path=state_db,
        ledger_db_path=ledger_db,
        coverage_status_path=status_path,
    )


def test_provider_derives_new_natural_entry_and_keeps_old_identity_unknown(
    tmp_path: Path,
) -> None:
    state_db = tmp_path / "paper.sqlite"
    ledger_db = tmp_path / "ledger.sqlite"
    status_path = tmp_path / "status.json"
    _make_state(
        state_db,
        [
            ("paper-main-20260907", "2026-09-07", {"1418": 1000, "2330": 0}),
            ("paper-main-20260908", "2026-09-08", {"1418": 1000, "2330": 1000}),
        ],
    )
    _make_ledger(
        ledger_db,
        [
            _ledger_row(
                token="entry-2330",
                event_date="2026-09-07",
                stock_code="2330",
                side="buy",
                quantity=1000,
            )
        ],
    )
    _write_status(
        status_path,
        state_db=state_db,
        ledger_db=ledger_db,
        snapshot_id="paper-main-20260908",
        decision_date="2026-09-08",
        transitions=1,
    )
    state_before = state_db.read_bytes()
    ledger_before = ledger_db.read_bytes()

    result = _provider(state_db, ledger_db, status_path).resolve(
        snapshot_id="paper-main-20260908",
        snapshot_date="2026-09-08",
        observed_at=datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc),
    )
    assert result.blockers == ()
    assert result.provenance["status"] == "degraded"
    identity = result.identities["2330"]
    assert identity["status"] == "natural_entry_verified"
    assert identity["entry_fill_id"] == "fill-entry-2330"
    assert str(identity["position_id"]).startswith("paper:paper-main:2330:entry-")
    assert "1418" not in result.identities
    assert "paper_position_identity_unproven:1418" in result.warnings
    repeated = _provider(state_db, ledger_db, status_path).resolve(
        snapshot_id="paper-main-20260908",
        snapshot_date="2026-09-08",
        observed_at=datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc),
    )
    assert repeated.identities["2330"]["position_id"] == identity["position_id"]
    assert state_db.read_bytes() == state_before
    assert ledger_db.read_bytes() == ledger_before


def test_provider_reentry_gets_new_identity_instead_of_closed_prior_identity(
    tmp_path: Path,
) -> None:
    state_db = tmp_path / "paper.sqlite"
    ledger_db = tmp_path / "ledger.sqlite"
    status_path = tmp_path / "status.json"
    _make_state(
        state_db,
        [
            ("paper-main-20260907", "2026-09-07", {"1418": 1000}),
            ("paper-main-20260909", "2026-09-09", {"1418": 1000}),
        ],
    )
    _make_ledger(
        ledger_db,
        [
            _ledger_row(token="exit", event_date="2026-09-07", stock_code="1418", side="sell", quantity=1000),
            _ledger_row(token="reentry", event_date="2026-09-08", stock_code="1418", side="buy", quantity=1000),
        ],
    )
    _write_status(
        status_path,
        state_db=state_db,
        ledger_db=ledger_db,
        snapshot_id="paper-main-20260909",
        decision_date="2026-09-09",
        transitions=2,
    )
    result = _provider(state_db, ledger_db, status_path).resolve(
        snapshot_id="paper-main-20260909",
        snapshot_date="2026-09-09",
        observed_at=datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc),
        previous_baseline={
            "1418": {
                "stock_code": "1418",
                "position_id": "paper:paper-main:1418:entry-old",
                "entry_lineage_id": "paper:paper-main:1418:entry-old",
                "entry_lineage_status": "ledger_continuous_no_trade",
                "state": "CLOSED",
            }
        },
    )
    assert result.blockers == ()
    identity = result.identities["1418"]
    assert identity["status"] == "natural_entry_verified"
    assert identity["entry_fill_id"] == "fill-reentry"
    assert identity["position_id"] != "paper:paper-main:1418:entry-old"


def test_provider_blocks_quantity_mismatch_before_identity_output(tmp_path: Path) -> None:
    state_db = tmp_path / "paper.sqlite"
    ledger_db = tmp_path / "ledger.sqlite"
    status_path = tmp_path / "status.json"
    _make_state(
        state_db,
        [
            ("paper-main-20260907", "2026-09-07", {"2330": 0}),
            ("paper-main-20260908", "2026-09-08", {"2330": 999}),
        ],
    )
    _make_ledger(
        ledger_db,
        [_ledger_row(token="entry", event_date="2026-09-07", stock_code="2330", side="buy", quantity=1000)],
    )
    _write_status(
        status_path,
        state_db=state_db,
        ledger_db=ledger_db,
        snapshot_id="paper-main-20260908",
        decision_date="2026-09-08",
        transitions=1,
    )
    result = _provider(state_db, ledger_db, status_path).resolve(
        snapshot_id="paper-main-20260908",
        snapshot_date="2026-09-08",
        observed_at=datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc),
    )
    assert result.identities == {}
    assert result.blockers
    assert any("quantity_mismatch:2330" in item for item in result.blockers)


def test_provider_uses_last_entry_after_multi_day_flat_interval(tmp_path: Path) -> None:
    state_db = tmp_path / "paper.sqlite"
    ledger_db = tmp_path / "ledger.sqlite"
    status_path = tmp_path / "status.json"
    _make_state(
        state_db,
        [
            ("paper-main-20260907", "2026-09-07", {"1418": 0}),
            ("paper-main-20260910", "2026-09-10", {"1418": 1000}),
        ],
    )
    _make_ledger(
        ledger_db,
        [
            _ledger_row(token="entry-a", event_date="2026-09-07", stock_code="1418", side="buy", quantity=1000),
            _ledger_row(token="exit", event_date="2026-09-08", stock_code="1418", side="sell", quantity=1000),
            _ledger_row(token="entry-b", event_date="2026-09-09", stock_code="1418", side="buy", quantity=1000),
        ],
    )
    _write_status(
        status_path,
        state_db=state_db,
        ledger_db=ledger_db,
        snapshot_id="paper-main-20260910",
        decision_date="2026-09-10",
        transitions=3,
    )

    result = _provider(state_db, ledger_db, status_path).resolve(
        snapshot_id="paper-main-20260910",
        snapshot_date="2026-09-10",
        observed_at=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
    )

    assert result.blockers == ()
    identity = result.identities["1418"]
    assert identity["status"] == "natural_entry_verified"
    assert identity["entry_fill_id"] == "fill-entry-b"
    assert "entry-a" not in str(identity["position_id"])


def test_provider_rejects_same_day_fills_without_sequence_or_time(tmp_path: Path) -> None:
    state_db = tmp_path / "paper.sqlite"
    ledger_db = tmp_path / "ledger.sqlite"
    status_path = tmp_path / "status.json"
    _make_state(
        state_db,
        [
            ("paper-main-20260907", "2026-09-07", {"1418": 0}),
            ("paper-main-20260908", "2026-09-08", {"1418": 1000}),
        ],
    )
    _make_ledger(
        ledger_db,
        [
            _ledger_row(token="buy-a", event_date="2026-09-07", stock_code="1418", side="buy", quantity=1000),
            _ledger_row(token="sell", event_date="2026-09-07", stock_code="1418", side="sell", quantity=1000),
            _ledger_row(token="buy-b", event_date="2026-09-07", stock_code="1418", side="buy", quantity=1000),
        ],
    )
    _write_status(
        status_path,
        state_db=state_db,
        ledger_db=ledger_db,
        snapshot_id="paper-main-20260908",
        decision_date="2026-09-08",
        transitions=3,
    )

    result = _provider(state_db, ledger_db, status_path).resolve(
        snapshot_id="paper-main-20260908",
        snapshot_date="2026-09-08",
        observed_at=datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc),
    )

    assert result.identities == {}
    assert any(
        item.startswith("paper_position_identity_event_order_ambiguous:1418:2026-09-07:")
        for item in result.blockers
    )


def test_daily_refresh_and_evaluator_consume_derived_entry_identity(tmp_path: Path) -> None:
    state_db = tmp_path / "paper.sqlite"
    ledger_db = tmp_path / "ledger.sqlite"
    status_path = tmp_path / "status.json"
    output = tmp_path / "health"
    _make_state(
        state_db,
        [
            ("paper-main-20260907", "2026-09-07", {"2330": 0}),
            ("paper-main-20260908", "2026-09-08", {"2330": 1000}),
        ],
    )
    _make_ledger(
        ledger_db,
        [_ledger_row(token="entry", event_date="2026-09-07", stock_code="2330", side="buy", quantity=1000)],
    )
    _write_status(
        status_path,
        state_db=state_db,
        ledger_db=ledger_db,
        snapshot_id="paper-main-20260908",
        decision_date="2026-09-08",
        transitions=1,
    )
    previous = output / "baseline_20260908.json"
    previous.parent.mkdir(parents=True)
    previous.write_text(
        json.dumps(
            {
                "decision_date": "2026-09-08",
                "source_snapshot_id": "paper-main-20260907",
                "research_only": True,
                "auto_action_allowed": False,
                "positions": [],
            }
        ),
        encoding="utf-8",
    )
    service = PositionHealthDailyRefreshService(
        state_db_path=state_db,
        status_path=status_path,
        ledger_db_path=ledger_db,
        coverage_status_path=status_path,
        position_identity_provider=_provider(state_db, ledger_db, status_path),
    )
    receipt = service.refresh(
        as_of_date=datetime(2026, 9, 8, tzinfo=timezone.utc).date(),
        output_dir=output,
        previous_baseline_path=previous,
        observed_at=datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc),
    )
    assert receipt["status"] == "passed"
    baseline = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    assert baseline["position_identity_verified_codes"] == ["2330"]
    assert baseline["positions"][0]["position_id"].startswith("paper:paper-main:2330:entry-")
    assert baseline["positions"][0]["entry_lineage_status"] == "natural_entry_verified"

    evaluation = evaluate_baseline_file(
        baseline_path=output / "latest.json",
        output_dir=tmp_path / "evaluation",
        observed_at=datetime.now(timezone.utc),
        transition_repository_path=tmp_path / "evaluation" / "proposals.sqlite",
        calendar_cache_path=Path("output/paper_execution_eod_replay/calendar_cache"),
    )
    assert evaluation["status"] == "degraded"
    assert evaluation["positions"][0]["position_id"].startswith("paper:paper-main:2330:entry-")
    assert "thesis_contract_missing" in " ".join(
        evaluation["positions"][0]["reasons"]
    )
