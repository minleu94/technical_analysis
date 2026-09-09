from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from app_module.exit_effectiveness_producer import (
    _sha256_json,
    produce_exit_effectiveness,
)
from app_module.paper_trade_ledger import PaperTradeFill, PaperTradeLedgerRepository
from app_module.position_health_service import PositionHealthState
from app_module.position_health_transition_repository import (
    PositionHealthTransitionRecord,
    PositionHealthTransitionRepository,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


class _StaticOfficialCalendar:
    def get_trading_days_in_range(
        self,
        start_date: date,
        end_date: date,
        allow_online_probe: bool = False,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        current = start_date
        while current <= end_date:
            is_open = current.weekday() < 5
            rows.append(
                {
                    "date": current,
                    "date_str": current.isoformat(),
                    "is_trading_day": is_open,
                    "reason_code": "fixture_official_open" if is_open else "fixture_weekend",
                }
            )
            current += timedelta(days=1)
        return rows

    def evidence_for(self, target_date: date) -> dict[str, object]:
        return {
            "mode": "fixture_official_calendar",
            "target_date": target_date.isoformat(),
            "source_hash": "sha256:" + "1" * 64,
            "is_trading_day": target_date.weekday() < 5,
        }


def _fill(
    *,
    fill_id: str,
    event_date: str,
    side: str,
    requested: int,
    filled: int,
    price: str | None,
    status: str,
    commission: str = "0",
    tax: str = "0",
) -> PaperTradeFill:
    return PaperTradeFill(
        fill_id=fill_id,
        order_id=f"order-{fill_id}",
        portfolio_id="paper-main",
        event_date=event_date,
        stock_code="2330",
        side=side,
        requested_quantity=requested,
        filled_quantity=filled,
        reference_price=Decimal("100"),
        fill_price=None if price is None else Decimal(price),
        commission=Decimal(commission),
        tax=Decimal(tax),
        slippage_cost=Decimal("0"),
        turnover_bp=100,
        execution_gap_bp=None if filled == 0 else 0,
        status=status,
        source_event_id=f"source-{fill_id}",
        source_type="paper_simulation",
    )


def _market_db(
    path: Path,
    *,
    with_corporate_actions: bool = True,
    with_row_availability: bool = True,
) -> None:
    with sqlite3.connect(path) as connection:
        availability_column = ", available_at TEXT" if with_row_availability else ""
        connection.execute(
            "CREATE TABLE daily_prices (日期 TEXT, 證券代號 TEXT, 收盤價 TEXT"
            f"{availability_column}, PRIMARY KEY (證券代號, 日期))"
        )
        prices = {
            "20260831": "100",
            "20260901": "99",
            "20260902": "95",
            "20260903": "94",
            "20260904": "93",
            "20260907": "92",
            "20260908": "91",
            "20260909": "90",
            "20260910": "89",
        }
        if with_row_availability:
            connection.executemany(
                "INSERT INTO daily_prices VALUES (?, '2330', ?, ?)",
                tuple(
                    (
                        date_text,
                        price,
                        (
                            "2026-09-01T08:00:00+08:00"
                            if date_text == "20260831"
                            else "2026-09-08T08:00:00+08:00"
                        ),
                    )
                    for date_text, price in prices.items()
                ),
            )
        else:
            connection.executemany(
                "INSERT INTO daily_prices VALUES (?, '2330', ?)",
                tuple((date_text, price) for date_text, price in prices.items()),
            )
        if with_corporate_actions:
            connection.execute(
                "CREATE TABLE corporate_action_events (stock_code TEXT, event_date TEXT, event_type TEXT)"
            )
    # The source file is deliberately newer than the decision date.  A
    # correct producer must use the row-level timestamp for the anchor and
    # must not backdate or trust the container mtime as historical evidence.
    source_time = datetime(2026, 9, 30, 10, tzinfo=UTC).timestamp()
    os.utime(path, (source_time, source_time))


def _make_sources(
    tmp_path: Path,
    *,
    sell: PaperTradeFill | None = None,
    rejected_sell: PaperTradeFill | None = None,
    with_corporate_actions: bool = True,
    with_row_availability: bool = True,
    entry_commission: str = "0",
    entry_tax: str = "0",
    decision_date: str = "2026-09-01",
) -> tuple[Path, Path, Path, str]:
    ledger_path = tmp_path / "paper_trade_ledger.sqlite"
    ledger = PaperTradeLedgerRepository(ledger_path)
    entry = _fill(
        fill_id="buy-2330",
        event_date="2026-08-31",
        side="buy",
        requested=100,
        filled=100,
        price="100",
        status="filled",
        commission=entry_commission,
        tax=entry_tax,
    )
    entries = [entry]
    if sell is not None:
        entries.append(sell)
    if rejected_sell is not None:
        entries.append(rejected_sell)
    ledger.append_many(entries)
    with sqlite3.connect(ledger_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM paper_trade_ledger WHERE fill_id = 'buy-2330'"
        ).fetchone()
        canonical = {key: row[key] for key in row.keys()}
    entry_suffix = _sha256_json(canonical).split(":", 1)[1][:24]
    position_id = f"paper:paper-main:2330:entry-{entry_suffix}"

    transition_path = tmp_path / "position_health_transitions.sqlite"
    transition_repo = PositionHealthTransitionRepository(transition_path)
    transition_repo.append(
        PositionHealthTransitionRecord.proposal(
            event_id="exit-event-2330",
            position_id=position_id,
            decision_date=decision_date,
            previous_state=PositionHealthState.HEALTHY,
            proposed_state=PositionHealthState.EXIT_CANDIDATE,
            reasons=("invalidation_triggered:drawdown_bp",),
        )
    )
    market_path = tmp_path / "market.sqlite"
    _market_db(
        market_path,
        with_corporate_actions=with_corporate_actions,
        with_row_availability=with_row_availability,
    )
    return transition_path, ledger_path, market_path, position_id


def test_real_closed_lineage_is_separate_from_counterfactual_and_is_idempotent(
    tmp_path: Path,
) -> None:
    transition, ledger, market, _ = _make_sources(
        tmp_path,
        sell=_fill(
            fill_id="sell-2330",
            event_date="2026-09-02",
            side="sell",
            requested=100,
            filled=100,
            price="95",
            status="filled",
        ),
    )
    output = tmp_path / "exit-effectiveness.json"
    first = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=output,
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )
    second = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=output,
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )

    assert first["status"] == "passed"
    assert first["actual_closed_count"] == 1
    assert first["observations"][0]["action_stage"] == "closed"
    assert first["observations"][0]["realized_return_bp"] == -500
    assert first["observations"][0]["realized_return_basis"] == (
        "net_cash_after_commission_tax_bp"
    )
    assert first["observations"][0]["post_exit_return_bp"] == -526
    assert first["observations"][0]["entry_fill_id"] == "buy-2330"
    assert first["observations"][0]["exit_fill_id"] == "sell-2330"
    assert first["observations"][0]["limitation_codes"] == []
    assert first["report"]["slices"][0]["ready_count"] == 1
    assert first["report"]["slices"][0]["average_realized_return_bp"] == -500
    assert first["report"]["slices"][0]["counterfactual_ready_count"] == 0
    assert second["artifact_write_status"] == "reused"
    assert second["evidence_hash"] == first["evidence_hash"]
    assert Path(first["artifact_path"]).read_bytes() == output.read_bytes()


def test_proposal_maturity_is_counterfactual_only(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(tmp_path)
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "proposal.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )
    row = result["observations"][0]
    slice_row = result["report"]["slices"][0]

    assert result["status"] == "passed"
    assert row["action_stage"] == "proposal"
    assert row["execution_status"] == "not_executed"
    assert row["post_exit_return_bp"] is None
    assert row["counterfactual_post_exit_return_bp"] == -800
    assert slice_row["ready_count"] == 0
    assert slice_row["avoided_loss_count"] == 0
    assert slice_row["counterfactual_ready_count"] == 1
    assert slice_row["counterfactual_avoided_loss_count"] == 1


def test_partial_sell_never_becomes_closed(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(
        tmp_path,
        sell=_fill(
            fill_id="sell-partial",
            event_date="2026-09-02",
            side="sell",
            requested=100,
            filled=40,
            price="95",
            status="partially_filled",
        ),
    )
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "partial.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )
    row = result["observations"][0]
    assert row["action_stage"] == "proposal"
    assert row["execution_status"] == "partially_filled"
    assert row["post_exit_return_bp"] is None
    assert "partial_exit_not_closed" in row["limitation_codes"]
    assert result["report"]["slices"][0]["ready_count"] == 0


def test_rejected_sell_then_no_reentry_cannot_claim_close(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(
        tmp_path,
        rejected_sell=_fill(
            fill_id="sell-rejected",
            event_date="2026-09-02",
            side="sell",
            requested=100,
            filled=0,
            price=None,
            status="rejected",
        ),
    )
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "rejected.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )
    row = result["observations"][0]
    assert row["action_stage"] == "proposal"
    assert row["execution_status"] == "rejected"
    assert "sell_rejected" in row["limitation_codes"]
    assert row["post_exit_return_bp"] is None
    assert result["report"]["slices"][0]["ready_count"] == 0


def test_missing_corporate_action_source_is_visible_and_blocks_credit(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(
        tmp_path,
        sell=_fill(
            fill_id="sell-2330",
            event_date="2026-09-02",
            side="sell",
            requested=100,
            filled=100,
            price="95",
            status="filled",
        ),
        with_corporate_actions=False,
    )
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "missing-action-source.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )
    row = result["observations"][0]
    assert result["status"] == "degraded"
    assert "corporate_action_source_unavailable" in row["limitation_codes"]
    assert row["maturity_status"] == "pending"
    assert result["report"]["slices"][0]["ready_count"] == 0


def test_future_transition_is_blocked_and_not_backfilled(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(
        tmp_path,
        decision_date="2026-10-01",
    )
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "future.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )
    assert result["status"] == "blocked"
    assert "transition_decision_date_in_future" in result["blockers"][0]
    assert result["observations"] == []


def test_future_maturity_remains_pending(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(tmp_path)
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "pending.json",
        now=datetime(2026, 9, 3, 12, tzinfo=UTC),
        calendar=_StaticOfficialCalendar(),
    )
    row = result["observations"][0]
    assert result["status"] == "degraded"
    assert row["maturity_status"] == "pending"
    assert row["outcome_date"] == "2026-09-07"
    assert row["counterfactual_post_exit_return_bp"] is None


def test_future_market_file_mtime_does_not_invalidate_row_level_pit(
    tmp_path: Path,
) -> None:
    transition, ledger, market, _ = _make_sources(tmp_path)
    future_time = datetime(2030, 1, 1, tzinfo=UTC).timestamp()
    os.utime(market, (future_time, future_time))
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "future-market.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )

    row = result["observations"][0]
    assert result["status"] == "passed"
    # Row-level availability proves the old anchor even though the container
    # mtime is in the future; the future mtime must not invalidate a valid
    # row-level PIT record.
    assert row["maturity_status"] == "ready"
    assert row["limitation_codes"] == []


def test_missing_row_level_availability_cannot_credit_proposal(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(
        tmp_path,
        with_row_availability=False,
    )
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "missing-row-availability.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )

    row = result["observations"][0]
    assert result["status"] == "degraded"
    assert row["maturity_status"] == "pending"
    assert "anchor_price_pit_availability_unproven" in row["limitation_codes"]
    assert row["counterfactual_post_exit_return_bp"] is None


def test_closed_fill_does_not_require_anchor_row_timestamp(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(
        tmp_path,
        with_row_availability=False,
        sell=_fill(
            fill_id="sell-closed-no-anchor-ts",
            event_date="2026-09-02",
            side="sell",
            requested=100,
            filled=100,
            price="95",
            status="filled",
        ),
    )
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "closed-no-anchor-ts.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )

    row = result["observations"][0]
    assert result["status"] == "passed"
    assert row["maturity_status"] == "ready"
    assert row["realized_return_basis"] == "net_cash_after_commission_tax_bp"
    assert "anchor_price_pit_availability_unproven" not in row["limitation_codes"]


def test_future_row_level_anchor_availability_is_rejected(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(tmp_path)
    with sqlite3.connect(market) as connection:
        connection.execute(
            "UPDATE daily_prices SET available_at = ? WHERE 日期 = ?",
            ("2030-01-01T00:00:00+00:00", "20260831"),
        )
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "future-row-availability.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )

    row = result["observations"][0]
    assert result["status"] == "degraded"
    assert row["maturity_status"] == "pending"
    assert "anchor_price_available_after_decision" in row["limitation_codes"]
    assert "market_price_source_future" in row["limitation_codes"]


def test_realized_return_includes_commission_and_tax(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(
        tmp_path,
        entry_commission="1.00",
        entry_tax="1.00",
        sell=_fill(
            fill_id="sell-costed",
            event_date="2026-09-02",
            side="sell",
            requested=100,
            filled=100,
            price="95",
            status="filled",
            commission="1.00",
            tax="1.00",
        ),
    )
    result = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=tmp_path / "costed.json",
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )

    row = result["observations"][0]
    assert result["status"] == "passed"
    # Entry cash = 100*100 + 2; exit cash = 100*95 - 2 => -504 bp.
    assert row["realized_return_bp"] == -504
    assert row["realized_return_basis"] == "net_cash_after_commission_tax_bp"


def test_divergent_immutable_artifact_is_kept_beside_original(tmp_path: Path) -> None:
    transition, ledger, market, _ = _make_sources(tmp_path)
    output = tmp_path / "immutable.json"
    first = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=output,
        now=NOW,
        calendar=_StaticOfficialCalendar(),
    )
    # A different run clock changes the body hash; the original artifact must
    # remain untouched and a hash-suffixed sibling is created.
    second = produce_exit_effectiveness(
        transition_db=transition,
        paper_ledger_db=ledger,
        market_db=market,
        output=output,
        now=NOW + timedelta(seconds=1),
        calendar=_StaticOfficialCalendar(),
    )
    assert first["artifact_path"] == str(output.resolve())
    assert second["artifact_path"] != first["artifact_path"]
    assert output.exists()
    assert Path(second["artifact_path"]).exists()
