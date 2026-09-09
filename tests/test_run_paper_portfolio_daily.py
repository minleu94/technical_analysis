from __future__ import annotations

from datetime import date, datetime
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path
import sqlite3
import sys

import pytest

from scripts.run_paper_portfolio_daily import (
    _latest_reached_decision_at,
    _next_decision_at,
    run,
)
from app_module.paper_trade_ledger import PaperTradeFill, PaperTradeLedgerRepository
from app_module.paper_portfolio_snapshot_repository import PaperPortfolioSnapshotRepository
from data_module.paper_daily_execution_producer import (
    PaperExecutionPaths,
    run_paper_execution_daily,
)
from data_module.portfolio_ml_dataset_assembler import (
    SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
    SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
)


class _OpenCalendar:
    def is_official_trading_day(self, _target_date):
        return True, "test_official_schedule_open"


class _ClosedCalendar:
    def is_official_trading_day(self, _target_date):
        return False, "weekend_closed"


class _UnknownCalendar:
    def is_official_trading_day(self, _target_date):
        return None, "twse_holiday_schedule_unavailable"


class _PaperT1Calendar:
    _open_dates = {"2026-09-04", "2026-09-07", "2026-09-08"}

    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool, str]:
        del allow_online_probe
        key = target_date.isoformat()
        return (
            key in self._open_dates,
            "test_official_schedule_open" if key in self._open_dates else "test_closed",
        )


def _sector_sidecar(path: Path, symbol: str = "2330") -> str:
    rows = [
        {
            "symbol": symbol,
            "sector_id": "SEMICONDUCTOR",
            "available_at": "2026-01-01T00:00:00+00:00",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "status": "accepted",
            "source_id": "official:twse:t187ap03_L",
            "license_id": "twse-open-data-license-v1",
            "source_hash": "sha256:" + "a" * 64,
        }
    ]
    manifest_body = {
        "schema_version": SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
        "row_count": len(rows),
        "rows_hash": "sha256:"
        + hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    manifest = {
        **manifest_body,
        "canonical_hash": "sha256:"
        + hashlib.sha256(
            json.dumps(
                {
                    "sidecar_schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
                    "manifest": manifest_body,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    payload = {
        "schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
        "manifest": manifest,
        "rows": rows,
    }
    path.write_bytes(
        (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    )
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _baseline(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "decision_date": "2026-07-12",
                "source_result_id": "rec-1",
                "residual_cash": "80000.00",
                "allocations": [
                    {
                        "stock_code": "2330",
                        "executable_shares": 1000,
                        "reference_price": "20.00",
                        "executable_amount": "20000.00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _market_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                收盤價 TEXT
            );
            INSERT INTO daily_prices VALUES
                ('20260729', '2330', '21.00'),
                ('20260730', '2330', '9999.00');
            """
        )


def test_daily_paper_snapshot_uses_strict_t_minus_one_and_is_idempotent(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "output" / "paper_portfolio" / "baseline.json"
    market_db = tmp_path / "market.sqlite"
    state_db = tmp_path / "output" / "paper_portfolio" / "paper.sqlite"
    _baseline(baseline)
    _market_db(market_db)
    decision_at = datetime.fromisoformat("2026-07-30T08:30:00+08:00")

    first = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "output",
        decision_at=decision_at,
        calendar=_OpenCalendar(),
    )
    second = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "output",
        decision_at=decision_at,
        calendar=_OpenCalendar(),
    )

    assert first["snapshot_appended"] is True
    assert first["total_value"] == "101000.00"
    assert first["diagnostics"] == ["t_minus_one_visible_price:2330:2026-07-29"]
    assert second["snapshot_appended"] is False
    assert second["skipped_duplicate"] is True
    assert first["writes_market_db"] is False
    assert first["auto_rebalance_allowed"] is False
    assert first["broker_execution"] is False


def test_next_preopen_projects_eod_fill_into_cash_and_quantity_once(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "output" / "paper_portfolio" / "baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps(
            {
                "decision_date": "2026-07-28",
                "source_result_id": "rec-preopen",
                "residual_cash": "80000.00",
                "allocations": [
                    {
                        "stock_code": "2330",
                        "executable_shares": 1000,
                        "reference_price": "20.00",
                        "executable_amount": "20000.00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    market_db = tmp_path / "market.sqlite"
    with sqlite3.connect(market_db) as connection:
        connection.execute(
            "CREATE TABLE daily_prices (日期 TEXT, 證券代號 TEXT, 收盤價 TEXT)"
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?)",
            (
                ("20260728", "2330", "20.00"),
                ("20260729", "2330", "21.00"),
                ("20260730", "2330", "22.00"),
            ),
        )
    state_db = tmp_path / "output" / "paper_portfolio" / "paper.sqlite"
    ledger_db = tmp_path / "output" / "paper_portfolio" / "paper-ledger.sqlite"
    first = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "output",
        decision_at=datetime.fromisoformat("2026-07-29T08:30:00+08:00"),
        now=datetime.fromisoformat("2026-07-29T20:00:00+08:00"),
        calendar=_OpenCalendar(),
        ledger_db=ledger_db,
    )
    assert first["snapshot_appended"] is True
    assert first["cash"] == "80000.00"
    assert first["total_value"] == "100000.00"

    fill = PaperTradeFill(
        fill_id="paper-execution:test-20260729-2330",
        order_id="paper-order:test-20260729-2330",
        portfolio_id="paper-main",
        event_date="2026-07-29",
        stock_code="2330",
        side="sell",
        requested_quantity=1000,
        filled_quantity=1000,
        reference_price=Decimal("21.00"),
        fill_price=Decimal("21.00"),
        commission=Decimal("0.10"),
        tax=Decimal("0.21"),
        slippage_cost=Decimal("0.00"),
        turnover_bp=1,
        execution_gap_bp=0,
        status="filled",
        source_event_id="paper-execution:test-20260729-2330",
        source_type="paper_daily_execution_delayed_eod_replay_v1",
    )
    PaperTradeLedgerRepository(ledger_db).append(fill)

    second = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "output",
        decision_at=datetime.fromisoformat("2026-07-30T08:30:00+08:00"),
        now=datetime.fromisoformat("2026-07-30T20:00:00+08:00"),
        calendar=_OpenCalendar(),
        ledger_db=ledger_db,
    )
    expected_cash = (
        Decimal("80000.00")
        + fill.gross_amount
        - fill.cash_settlement_cost
    )
    assert second["snapshot_appended"] is True
    assert second["paper_ledger_transitions_applied"] == 1
    assert second["cash"] == str(expected_cash)
    assert second["total_value"] == str(expected_cash)
    snapshot = PaperPortfolioSnapshotRepository(state_db).get("paper-main-20260730")
    assert snapshot is not None
    assert snapshot.cash == expected_cash
    assert snapshot.total_value == expected_cash
    assert snapshot.positions == ()

    retry = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "output",
        decision_at=datetime.fromisoformat("2026-07-30T08:30:00+08:00"),
        now=datetime.fromisoformat("2026-07-30T20:00:00+08:00"),
        calendar=_OpenCalendar(),
        ledger_db=ledger_db,
    )
    assert retry["snapshot_appended"] is False
    assert retry["paper_ledger_transitions_applied"] == 0


def test_scheduled_preopen_eod_retry_and_next_preopen_form_one_causal_chain(
    tmp_path: Path,
) -> None:
    """串接排程 producer 與下一個 snapshot reader。"""

    output_root = tmp_path / "output"
    baseline = output_root / "paper_portfolio" / "baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps(
            {
                "decision_date": "2026-09-04",
                "source_result_id": "rec-preopen-chain",
                "residual_cash": "100000.00",
                "allocations": [
                    {
                        "stock_code": "2330",
                        "executable_shares": 0,
                        "reference_price": "10.00",
                        "executable_amount": "0.00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    recommendation = tmp_path / "scheduled-recommendation.json"
    recommendation.write_text(
        json.dumps(
            {
                "result_id": "scheduled_rec_20260906_200000",
                "created_at": "2026-09-06T20:00:00+08:00",
                "config": {
                    "research_only": True,
                    "decision_date": "2026-09-06",
                    "top_n": 8,
                    "profile_id": "scheduled_daily_research_default_v1",
                    "safety_boundary": {
                        "confirm": False,
                        "writes_evidence_db": False,
                        "auto_trading": False,
                        "lifecycle_action": False,
                    },
                },
                "recommendations": [
                    {
                        "證券代號": "2330",
                        "證券名稱": "測試公司",
                        "總分": "100.00",
                        "收盤價": "10.00",
                        "產業": "半導體",
                        "eligible_universe_date": "2026-09-06",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    market_db = tmp_path / "market.sqlite"
    with sqlite3.connect(market_db) as connection:
        connection.execute(
            "CREATE TABLE daily_prices ("
            "日期 TEXT, 證券代號 TEXT, 證券名稱 TEXT, "
            "開盤價 TEXT, 收盤價 TEXT, 成交股數 INTEGER)"
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?)",
            (
                ("20260904", "2330", "測試公司", "9.80", "10.00", 90000),
                ("20260907", "2330", "測試公司", "10.20", "10.30", 100000),
                ("20260908", "2330", "測試公司", "10.40", "10.50", 100000),
            ),
        )
        connection.execute("CREATE TABLE market_indices (日期 TEXT, 指數名稱 TEXT)")
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?)",
            (("20260904", "TAIEX"), ("20260907", "TAIEX"), ("20260908", "TAIEX")),
        )
    state_db = output_root / "paper_portfolio" / "paper.sqlite"
    ledger_db = output_root / "paper_portfolio" / "paper-ledger.sqlite"
    sector_path = tmp_path / "pit-sector.json"
    sector_hash = _sector_sidecar(sector_path)
    calendar = _PaperT1Calendar()

    preopen = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=output_root,
        decision_at=datetime.fromisoformat("2026-09-07T08:30:00+08:00"),
        now=datetime.fromisoformat("2026-09-07T08:30:01+08:00"),
        calendar=calendar,
        ledger_db=ledger_db,
    )
    assert preopen["snapshot_appended"] is True
    snapshot_before = PaperPortfolioSnapshotRepository(state_db).get(
        "paper-main-20260907"
    )
    assert snapshot_before is not None
    state_bytes_before = state_db.read_bytes()
    # The policy adapter is read-only but requires an explicit append-only
    # ledger schema, including when this first candidate has no prior fills.
    PaperTradeLedgerRepository(ledger_db)

    execution_paths = PaperExecutionPaths(
        recommendation_json=recommendation,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "execution-candidate",
        ledger_db=ledger_db,
        sector_membership_path=sector_path,
        sector_membership_file_hash=sector_hash,
    )
    candidate = run_paper_execution_daily(
        execution_paths,
        now=datetime.fromisoformat("2026-09-07T15:00:01+08:00"),
        calendar=calendar,
        confirm_append=False,
    )
    assert candidate["status"] == "machine_verified_candidate"
    assert candidate["state_source"]["execution_snapshot_exists"] is True
    assert candidate["ledger"]["appended"] is False
    # The policy adapter consumes an explicit append-only ledger source even
    # for a candidate-only run.  The producer must leave that pre-created
    # schema empty until the explicit append pass.
    assert ledger_db.is_file()
    assert PaperTradeLedgerRepository(ledger_db).list() == ()

    appended = run_paper_execution_daily(
        PaperExecutionPaths(
            **{**execution_paths.__dict__, "output_root": tmp_path / "execution-appended"}
        ),
        now=datetime.fromisoformat("2026-09-07T15:00:02+08:00"),
        calendar=calendar,
        confirm_append=True,
    )
    assert appended["status"] == "machine_verified_candidate"
    assert appended["ledger"]["appended"] is True
    fill = appended["fills"][0]
    assert isinstance(fill, dict)
    assert appended["state_source"]["execution_snapshot_exists"] is True
    assert state_db.read_bytes() == state_bytes_before

    retry = run_paper_execution_daily(
        PaperExecutionPaths(
            **{**execution_paths.__dict__, "output_root": tmp_path / "execution-retry"}
        ),
        now=datetime.fromisoformat("2026-09-07T15:00:03+08:00"),
        calendar=calendar,
        confirm_append=True,
    )
    assert retry["status"] == "machine_verified_candidate"
    assert retry["ledger"]["idempotent_replay"] is True

    next_preopen = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=output_root,
        decision_at=datetime.fromisoformat("2026-09-08T08:30:00+08:00"),
        now=datetime.fromisoformat("2026-09-08T08:30:01+08:00"),
        calendar=calendar,
        ledger_db=ledger_db,
    )
    assert next_preopen["snapshot_appended"] is True
    assert next_preopen["paper_ledger_transitions_applied"] == 1
    next_snapshot = PaperPortfolioSnapshotRepository(state_db).get(
        "paper-main-20260908"
    )
    assert next_snapshot is not None
    expected_cash = (
        Decimal("100000.00")
        - Decimal(str(fill["gross_amount"]))
        - Decimal(str(fill["commission"]))
        - Decimal(str(fill["tax"]))
    )
    assert next_snapshot.cash == expected_cash
    expected_quantity = int(fill["filled_quantity"])
    expected_marked_value = Decimal("10.30") * expected_quantity
    assert next_snapshot.total_value == expected_cash + expected_marked_value
    assert next_snapshot.positions[0].quantity == expected_quantity

    # 下一個 execution session 也必須讀取綁在 9/7 preopen snapshot 的同日
    # postfill event；此處保護 producer state projection 的含下界語意。
    next_recommendation = tmp_path / "next-recommendation.json"
    next_payload = json.loads(recommendation.read_text(encoding="utf-8"))
    next_payload["created_at"] = "2026-09-07T20:00:00+08:00"
    next_payload["config"]["decision_date"] = "2026-09-07"
    next_payload["recommendations"][0]["收盤價"] = "10.30"
    next_payload["recommendations"][0]["eligible_universe_date"] = "2026-09-07"
    next_recommendation.write_text(
        json.dumps(next_payload),
        encoding="utf-8",
    )
    next_execution = run_paper_execution_daily(
        PaperExecutionPaths(
            recommendation_json=next_recommendation,
            state_db=state_db,
            market_db=market_db,
            output_root=tmp_path / "next-execution",
            ledger_db=ledger_db,
            sector_membership_path=sector_path,
            sector_membership_file_hash=sector_hash,
        ),
        now=datetime.fromisoformat("2026-09-08T15:00:04+08:00"),
        calendar=calendar,
        confirm_append=False,
    )
    assert next_execution["status"] == "no_trade_required_candidate"
    next_state_source = next_execution["state_source"]
    assert isinstance(next_state_source, dict)
    assert next_state_source["ledger_event_ids_applied"] == [fill["fill_id"]]


def test_default_decision_is_next_future_taipei_cutoff() -> None:
    assert _next_decision_at(
        None,
        now=datetime.fromisoformat("2026-07-29T20:00:00+08:00"),
    ).isoformat() == "2026-07-30T08:30:00+08:00"


def test_scheduled_default_decision_is_latest_reached_taipei_cutoff() -> None:
    assert _latest_reached_decision_at(
        None,
        now=datetime.fromisoformat("2026-07-30T20:00:00+08:00"),
    ).isoformat() == "2026-07-30T08:30:00+08:00"
    assert _latest_reached_decision_at(
        None,
        now=datetime.fromisoformat("2026-07-30T08:29:59+08:00"),
    ).isoformat() == "2026-07-29T08:30:00+08:00"


def test_scheduled_default_decision_rejects_naive_clock() -> None:
    try:
        _latest_reached_decision_at(
            None,
            now=datetime.fromisoformat("2026-07-30T08:00:00"),
        )
    except ValueError as exc:
        assert "timezone" in str(exc)
    else:
        raise AssertionError("naive scheduler clock must fail closed")


def test_cli_help_reconfigures_windows_console_before_argparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chinese CLI help must remain printable on a cp1252 Windows host."""

    from scripts.run_paper_portfolio_daily import main

    payload = io.BytesIO()
    stream = io.TextIOWrapper(payload, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    stream.flush()
    assert exc_info.value.code == 0
    assert "嚴格" in payload.getvalue().decode("utf-8")


def test_future_decision_does_not_initialize_or_append_paper_ledger(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "output" / "paper_portfolio" / "baseline.json"
    market_db = tmp_path / "market.sqlite"
    state_db = tmp_path / "output" / "paper_portfolio" / "paper.sqlite"
    _baseline(baseline)
    _market_db(market_db)

    result = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "output",
        decision_at=datetime.fromisoformat("2026-08-28T08:30:00+08:00"),
        now=datetime.fromisoformat("2026-08-27T20:00:00+08:00"),
        calendar=_OpenCalendar(),
    )

    assert result["status"] == "skipped_future_decision"
    assert result["snapshot_appended"] is False
    assert result["market_db_mode"] == "not_opened"
    assert result["trading_calendar_validated"] is False
    assert not state_db.exists()
    persisted = json.loads(
        (
            tmp_path
            / "output"
            / "scheduled"
            / "paper_portfolio_daily"
            / "latest_status.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted["status"] == "skipped_future_decision"
    assert persisted["writes_market_db"] is False


def test_closed_day_does_not_initialize_or_append_paper_ledger(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "output" / "paper_portfolio" / "baseline.json"
    market_db = tmp_path / "market.sqlite"
    state_db = tmp_path / "output" / "paper_portfolio" / "paper.sqlite"
    _baseline(baseline)
    _market_db(market_db)

    result = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "output",
        decision_at=datetime.fromisoformat("2026-08-01T08:30:00+08:00"),
        calendar=_ClosedCalendar(),
    )

    assert result["status"] == "skipped_non_trading_day"
    assert result["snapshot_appended"] is False
    assert result["market_db_mode"] == "not_opened"
    assert not state_db.exists()


def test_unknown_calendar_does_not_initialize_or_append_paper_ledger(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "output" / "paper_portfolio" / "baseline.json"
    market_db = tmp_path / "market.sqlite"
    state_db = tmp_path / "output" / "paper_portfolio" / "paper.sqlite"
    _baseline(baseline)
    _market_db(market_db)

    result = run(
        baseline_path=baseline,
        state_db=state_db,
        market_db=market_db,
        output_root=tmp_path / "output",
        decision_at=datetime.fromisoformat("2026-07-30T08:30:00+08:00"),
        calendar=_UnknownCalendar(),
    )

    assert result["status"] == "degraded_calendar_unknown"
    assert result["trading_calendar_validated"] is False
    assert result["snapshot_appended"] is False
    assert not state_db.exists()
