from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3

import pytest

from data_module.formal_simulated_portfolio_ledger import (
    SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION,
    SimulatedPortfolioLedgerError,
    append_simulated_transition,
    build_simulated_transition,
    summarize_simulated_ledger,
)
from data_module.prospective_formal_clock import build_clock_manifest, load_clock_manifest, payload_hash
from ml_module.allocation_contracts import AllocationWeightContract, CausalPortfolioState


_NOW = datetime.fromisoformat("2026-08-14T09:00:00+08:00")


def _clock(tmp_path: Path, *, decision_time: str = "08:30:00"):
    seed = {"kind": "cash", "cash_bp": 10_000, "position_count": 0}
    seed["state_hash"] = payload_hash(seed)
    calendar = {
        "schema_version": "official-trading-calendar-evidence.v1",
        "date": "2026-08-17",
        "is_trading_day": True,
        "reason_code": "twse_holiday_schedule_open",
        "source": "TWSE holidaySchedule",
        "source_hash": "sha256:" + "1" * 64,
    }
    body: dict[str, object] = {
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
        "clock_id": "clock:prospective:20260817:r1",
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-decision:test",
        "owner_decision_timestamp": "2026-08-14T08:45:00+08:00",
        "activation_trading_day": "2026-08-17",
        "decision_timezone": "Asia/Taipei",
        "decision_time": decision_time,
        "activation_calendar_evidence": calendar,
        "seed_state": seed,
        "virtual_notional_minor_units": 1_000_000,
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        "policy_hash": "sha256:" + "2" * 64,
        "universe_hash": "sha256:" + "3" * 64,
        "source_policy_hash": "sha256:" + "4" * 64,
        "candidate_model_hash": "sha256:" + "5" * 64,
        "candidate_feature_manifest_hash": "sha256:" + "6" * 64,
        "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
        "calibration_policy_hash": "sha256:" + "7" * 64,
        "evaluation_policy_hash": "sha256:" + "8" * 64,
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    path = tmp_path / "clock.json"
    path.write_text(json.dumps(build_clock_manifest(body)), encoding="utf-8")
    return load_clock_manifest(path, now=_NOW)


def _cash_state() -> CausalPortfolioState:
    return CausalPortfolioState.create(
        as_of_date="2026-08-14",
        weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
        weekly_turnover_used_bp=0,
    )


def _invested_state() -> AllocationWeightContract:
    return AllocationWeightContract(positions_bp=(("2330", 1_000),), cash_bp=9_000)


def _transition(clock, *, previous_chain_hash: str = "sha256:" + "0" * 64):
    return build_simulated_transition(
        clock=clock,
        decision_date="2026-08-17",
        decision_at="2026-08-17T08:30:00+08:00",
        previous_trading_day="2026-08-14",
        input_state=_cash_state(),
        desired_weights=_invested_state(),
        feature_input_hash="sha256:" + "9" * 64,
        estimated_cost_bp=25,
        output_weekly_turnover_used_bp=1_000,
        previous_chain_hash=previous_chain_hash,
    )


def test_portfolio_uses_clock_bound_decision_time(tmp_path: Path) -> None:
    clock = _clock(tmp_path, decision_time="09:00:00")
    transition = build_simulated_transition(
        clock=clock,
        decision_date="2026-08-17",
        decision_at="2026-08-17T09:00:00+08:00",
        previous_trading_day="2026-08-14",
        input_state=_cash_state(),
        desired_weights=_invested_state(),
        feature_input_hash="sha256:" + "9" * 64,
        estimated_cost_bp=25,
        output_weekly_turnover_used_bp=1_000,
    )

    path = tmp_path / "ledger-09.sqlite"
    append_simulated_transition(path, transition)
    summary = summarize_simulated_ledger(path, clock=clock)

    assert summary.decision_dates == ("2026-08-17",)


def test_first_transition_is_t_minus_one_and_hash_bound(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    transition = _transition(clock)
    result = append_simulated_transition(tmp_path / "ledger.sqlite", transition)

    assert result.idempotent is False
    assert transition.canonical_turnover_bp == 1_000
    assert transition.buy_turnover_bp == 1_000
    assert transition.sell_turnover_bp == 0
    assert transition.add_count == 1
    assert transition.reduce_count == 0
    assert transition.future_teacher_target_used is False
    assert transition.same_day_advice_used is False
    summary = summarize_simulated_ledger(tmp_path / "ledger.sqlite", clock=clock)
    assert summary.schema_version == SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION
    assert summary.decision_dates == ("2026-08-17",)
    assert summary.non_cash_state_day_count == 0


def test_same_transition_is_idempotent_but_conflict_is_rejected(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    path = tmp_path / "ledger.sqlite"
    transition = _transition(clock)
    assert append_simulated_transition(path, transition).idempotent is False
    assert append_simulated_transition(path, transition).idempotent is True

    conflict = _transition(clock)
    conflict = build_simulated_transition(
        clock=clock,
        decision_date=conflict.decision_date,
        decision_at=conflict.decision_at,
        previous_trading_day=conflict.previous_trading_day,
        input_state=conflict.input_state,
        desired_weights=AllocationWeightContract(positions_bp=(("2317", 1_000),), cash_bp=9_000),
        feature_input_hash="sha256:" + "a" * 64,
        estimated_cost_bp=25,
        output_weekly_turnover_used_bp=1_000,
    )
    with pytest.raises(SimulatedPortfolioLedgerError, match="different transition"):
        append_simulated_transition(path, conflict)


def test_second_transition_preserves_state_and_recursive_chain(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    path = tmp_path / "ledger.sqlite"
    first = _transition(clock)
    append_simulated_transition(path, first)

    second = build_simulated_transition(
        clock=clock,
        decision_date="2026-08-18",
        decision_at="2026-08-18T08:30:00+08:00",
        previous_trading_day="2026-08-17",
        input_state=first.output_state,
        desired_weights=_invested_state(),
        feature_input_hash="sha256:" + "b" * 64,
        estimated_cost_bp=0,
        output_weekly_turnover_used_bp=1_000,
        previous_chain_hash=first.chain_hash,
    )
    append_simulated_transition(path, second)

    summary = summarize_simulated_ledger(path, clock=clock)
    assert summary.decision_dates == ("2026-08-17", "2026-08-18")
    assert summary.decision_date_count == 2
    assert summary.non_cash_state_day_count == 1
    assert summary.transition_chain_hash == second.chain_hash

    connection = sqlite3.connect(path)
    stored_previous_chain = connection.execute(
        "SELECT previous_chain_hash FROM transitions WHERE decision_date = ?",
        ("2026-08-18",),
    ).fetchone()[0]
    connection.close()
    assert stored_previous_chain == first.chain_hash


def test_t_minus_one_policy_and_clock_identity_are_enforced(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    with pytest.raises(SimulatedPortfolioLedgerError, match="previous trading day"):
        build_simulated_transition(
            clock=clock,
            decision_date="2026-08-17",
            decision_at="2026-08-17T08:30:00+08:00",
            previous_trading_day="2026-08-15",
            input_state=_cash_state(),
            desired_weights=_invested_state(),
            feature_input_hash="sha256:" + "9" * 64,
            estimated_cost_bp=25,
            output_weekly_turnover_used_bp=1_000,
        )
    with pytest.raises(SimulatedPortfolioLedgerError, match="decision_at"):
        build_simulated_transition(
            clock=clock,
            decision_date="2026-08-17",
            decision_at="2026-08-17T09:00:00+08:00",
            previous_trading_day="2026-08-14",
            input_state=_cash_state(),
            desired_weights=_invested_state(),
            feature_input_hash="sha256:" + "9" * 64,
            estimated_cost_bp=25,
            output_weekly_turnover_used_bp=1_000,
        )


def test_sqlite_update_and_delete_are_blocked(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    path = tmp_path / "ledger.sqlite"
    append_simulated_transition(path, _transition(clock))
    connection = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("UPDATE transitions SET estimated_cost_bp = 26")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("DELETE FROM transitions")
    connection.close()
