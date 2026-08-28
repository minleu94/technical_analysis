from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3

from scripts.run_paper_portfolio_daily import (
    _latest_reached_decision_at,
    _next_decision_at,
    run,
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
