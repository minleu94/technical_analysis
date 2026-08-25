"""Prospective-only 模擬 Portfolio transition producer。

這個 writer 與既有 ``causal-portfolio-ledger.v1`` deliberately 分離。它只接受
已通過 prospective clock contract 的 frozen identities，並將每個決策日以
T-1 state、整數 bp turnover、canonical transition hash 與 recursive chain hash
append 到 SQLite。沒有 Teacher target、same-day Advice 或 retroactive append。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time
import json
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    SHA256_PREFIX,
    canonical_json,
    file_sha256,
    payload_hash,
)
from financial_module.portfolio_turnover import canonical_turnover_bp
from ml_module.allocation_contracts import AllocationWeightContract, CausalPortfolioState


SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION = "causal-simulated-portfolio-ledger.v1"
SIMULATED_PORTFOLIO_TRANSITION_SCHEMA_VERSION = (
    "causal-simulated-portfolio-ledger-transition.v1"
)
SIMULATED_PORTFOLIO_STATE_SCHEMA_VERSION = "causal-portfolio-state.v1"
ZERO_CHAIN_HASH = SHA256_PREFIX + ("0" * 64)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")

_METADATA_FIELDS = frozenset(
    {"schema_version", "clock_id", "clock_manifest_hash", "policy_hash"}
)
_TRANSITION_COLUMN_ORDER = (
    "clock_id",
    "clock_manifest_hash",
    "policy_hash",
    "decision_date",
    "decision_at",
    "previous_trading_day",
    "input_state_json",
    "desired_weights_json",
    "output_state_json",
    "feature_input_hash",
    "buy_turnover_bp",
    "sell_turnover_bp",
    "canonical_turnover_bp",
    "estimated_cost_bp",
    "add_count",
    "reduce_count",
    "previous_chain_hash",
    "future_teacher_target_used",
    "same_day_advice_used",
    "transition_hash",
    "chain_hash",
)
_TRANSITION_FIELDS = frozenset(_TRANSITION_COLUMN_ORDER)


class SimulatedPortfolioLedgerError(ValueError):
    """模擬 ledger 不能安全 append 或驗證。"""


@dataclass(frozen=True)
class SimulatedPortfolioTransition:
    clock_id: str
    clock_manifest_hash: str
    policy_hash: str
    decision_date: str
    decision_at: str
    previous_trading_day: str
    input_state: CausalPortfolioState
    desired_weights: AllocationWeightContract
    output_state: CausalPortfolioState
    feature_input_hash: str
    buy_turnover_bp: int
    sell_turnover_bp: int
    canonical_turnover_bp: int
    estimated_cost_bp: int
    add_count: int
    reduce_count: int
    previous_chain_hash: str
    transition_hash: str
    chain_hash: str
    future_teacher_target_used: bool = False
    same_day_advice_used: bool = False

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": SIMULATED_PORTFOLIO_TRANSITION_SCHEMA_VERSION,
            "clock_id": self.clock_id,
            "clock_manifest_hash": self.clock_manifest_hash,
            "policy_hash": self.policy_hash,
            "decision_date": self.decision_date,
            "decision_at": self.decision_at,
            "previous_trading_day": self.previous_trading_day,
            "input_state_hash": self.input_state.state_hash,
            "desired_weights": _weight_payload(self.desired_weights),
            "output_state_hash": self.output_state.state_hash,
            "feature_input_hash": self.feature_input_hash,
            "previous_chain_hash": self.previous_chain_hash,
            "buy_turnover_bp": self.buy_turnover_bp,
            "sell_turnover_bp": self.sell_turnover_bp,
            "canonical_turnover_bp": self.canonical_turnover_bp,
            "estimated_cost_bp": self.estimated_cost_bp,
            "add_count": self.add_count,
            "reduce_count": self.reduce_count,
            "future_teacher_target_used": False,
            "same_day_advice_used": False,
        }

    def as_row(self) -> dict[str, object]:
        return {
            "clock_id": self.clock_id,
            "clock_manifest_hash": self.clock_manifest_hash,
            "policy_hash": self.policy_hash,
            "decision_date": self.decision_date,
            "decision_at": self.decision_at,
            "previous_trading_day": self.previous_trading_day,
            "input_state_json": _state_json(self.input_state),
            "desired_weights_json": canonical_json(_weight_payload(self.desired_weights)),
            "output_state_json": _state_json(self.output_state),
            "feature_input_hash": self.feature_input_hash,
            "buy_turnover_bp": self.buy_turnover_bp,
            "sell_turnover_bp": self.sell_turnover_bp,
            "canonical_turnover_bp": self.canonical_turnover_bp,
            "estimated_cost_bp": self.estimated_cost_bp,
            "add_count": self.add_count,
            "reduce_count": self.reduce_count,
            "previous_chain_hash": self.previous_chain_hash,
            "future_teacher_target_used": 0,
            "same_day_advice_used": 0,
            "transition_hash": self.transition_hash,
            "chain_hash": self.chain_hash,
        }


@dataclass(frozen=True)
class SimulatedLedgerAppendResult:
    transition: SimulatedPortfolioTransition
    idempotent: bool


@dataclass(frozen=True)
class SimulatedLedgerSummary:
    schema_version: str
    clock_id: str
    clock_manifest_hash: str
    policy_hash: str
    decision_dates: tuple[str, ...]
    decision_date_count: int
    non_cash_state_day_count: int
    transition_chain_hash: str
    sqlite_file_hash: str


def build_simulated_transition(
    *,
    clock: ProspectiveFormalClock,
    decision_date: str,
    decision_at: str,
    previous_trading_day: str,
    input_state: CausalPortfolioState,
    desired_weights: AllocationWeightContract,
    feature_input_hash: str,
    estimated_cost_bp: int,
    output_weekly_turnover_used_bp: int,
    previous_chain_hash: str = ZERO_CHAIN_HASH,
) -> SimulatedPortfolioTransition:
    """建立一筆未寫入 SQLite 的 immutable transition。"""

    normalized_decision_date = _parse_date(decision_date, "decision_date").isoformat()
    normalized_previous_day = _parse_date(
        previous_trading_day, "previous_trading_day"
    ).isoformat()
    if normalized_previous_day >= normalized_decision_date:
        raise SimulatedPortfolioLedgerError(
            "previous_trading_day must be before decision_date"
        )
    if normalized_decision_date < clock.activation_trading_day.isoformat():
        raise SimulatedPortfolioLedgerError(
            "decision_date cannot precede prospective clock activation"
        )
    if input_state.as_of_date != normalized_previous_day:
        raise SimulatedPortfolioLedgerError(
            "input state must equal the supplied previous trading day"
        )
    if input_state.as_of_date >= normalized_decision_date:
        raise SimulatedPortfolioLedgerError("input state is not T-1")
    parsed_decision_at = _parse_decision_at(decision_at)
    if parsed_decision_at.date().isoformat() != normalized_decision_date:
        raise SimulatedPortfolioLedgerError("decision_at date does not match decision_date")
    expected_time = time.fromisoformat(str(clock.payload["decision_time"]))
    if parsed_decision_at.timetz().replace(tzinfo=None) != expected_time:
        raise SimulatedPortfolioLedgerError("decision_at does not match clock decision_time")
    if not _is_sha256(feature_input_hash):
        raise SimulatedPortfolioLedgerError("feature_input_hash must be sha256")
    if not _is_sha256(previous_chain_hash):
        raise SimulatedPortfolioLedgerError("previous_chain_hash must be sha256")
    if not isinstance(estimated_cost_bp, int) or isinstance(estimated_cost_bp, bool):
        raise SimulatedPortfolioLedgerError("estimated_cost_bp must be an integer")
    if estimated_cost_bp < 0:
        raise SimulatedPortfolioLedgerError("estimated_cost_bp must be non-negative")
    if not isinstance(output_weekly_turnover_used_bp, int) or isinstance(
        output_weekly_turnover_used_bp, bool
    ):
        raise SimulatedPortfolioLedgerError(
            "output_weekly_turnover_used_bp must be an integer"
        )
    if output_weekly_turnover_used_bp < 0 or output_weekly_turnover_used_bp > 10_000:
        raise SimulatedPortfolioLedgerError(
            "output_weekly_turnover_used_bp must be within 0..10000"
        )
    policy_hash = str(clock.payload["policy_hash"])
    current = dict(input_state.weights.positions_bp)
    target = dict(desired_weights.positions_bp)
    symbols = tuple(sorted(set(current) | set(target)))
    current_vector = tuple(current.get(symbol, 0) for symbol in symbols)
    target_vector = tuple(target.get(symbol, 0) for symbol in symbols)
    buy_turnover_bp = sum(
        max(target.get(symbol, 0) - current.get(symbol, 0), 0) for symbol in symbols
    )
    sell_turnover_bp = sum(
        max(current.get(symbol, 0) - target.get(symbol, 0), 0) for symbol in symbols
    )
    canonical = canonical_turnover_bp(
        current_position_weights_bp=current_vector,
        current_cash_bp=input_state.weights.cash_bp,
        target_position_weights_bp=target_vector,
        target_cash_bp=desired_weights.cash_bp,
    )
    add_count = sum(
        target.get(symbol, 0) > current.get(symbol, 0) for symbol in symbols
    )
    reduce_count = sum(
        current.get(symbol, 0) > target.get(symbol, 0) for symbol in symbols
    )
    output_state = CausalPortfolioState.create(
        as_of_date=normalized_decision_date,
        weights=desired_weights,
        weekly_turnover_used_bp=output_weekly_turnover_used_bp,
    )
    transition_without_hash = SimulatedPortfolioTransition(
        clock_id=clock.clock_id,
        clock_manifest_hash=clock.manifest_hash,
        policy_hash=policy_hash,
        decision_date=normalized_decision_date,
        decision_at=parsed_decision_at.isoformat(),
        previous_trading_day=normalized_previous_day,
        input_state=input_state,
        desired_weights=desired_weights,
        output_state=output_state,
        feature_input_hash=feature_input_hash,
        buy_turnover_bp=buy_turnover_bp,
        sell_turnover_bp=sell_turnover_bp,
        canonical_turnover_bp=canonical,
        estimated_cost_bp=estimated_cost_bp,
        add_count=add_count,
        reduce_count=reduce_count,
        previous_chain_hash=previous_chain_hash,
        transition_hash="",
        chain_hash="",
    )
    transition_hash = payload_hash(transition_without_hash.canonical_payload())
    chain_hash = payload_hash(
        {
            "schema_version": SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION,
            "clock_id": clock.clock_id,
            "previous_chain_hash": previous_chain_hash,
            "transition_hash": transition_hash,
        }
    )
    return replace(
        transition_without_hash,
        transition_hash=transition_hash,
        chain_hash=chain_hash,
    )


def append_simulated_transition(
    sqlite_path: Path,
    transition: SimulatedPortfolioTransition,
) -> SimulatedLedgerAppendResult:
    """以 transaction append 一筆 transition；同列完全相同時回傳 idempotent。"""

    path = sqlite_path.expanduser().resolve()
    if not path.parent.exists():
        raise SimulatedPortfolioLedgerError(
            "sqlite parent directory must already exist"
        )
    row_payload = transition.as_row()
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema(connection)
        _validate_transition(transition)
        _ensure_metadata(
            connection,
            clock_id=transition.clock_id,
            clock_manifest_hash=transition.clock_manifest_hash,
            policy_hash=transition.policy_hash,
        )
        existing = connection.execute(
            "SELECT * FROM transitions WHERE decision_date = ?",
            (transition.decision_date,),
        ).fetchone()
        columns = _table_columns(connection, "transitions")
        if existing is not None:
            existing_row = dict(zip(columns, existing, strict=True))
            if existing_row == row_payload:
                connection.commit()
                return SimulatedLedgerAppendResult(transition=transition, idempotent=True)
            raise SimulatedPortfolioLedgerError(
                "decision_date already exists with different transition"
            )
        last = connection.execute(
            "SELECT chain_hash, output_state_json FROM transitions "
            "ORDER BY decision_date DESC LIMIT 1"
        ).fetchone()
        if last is not None:
            previous_chain_hash = str(last[0])
            previous_output = _state_from_json(str(last[1]), "previous output state")
            if transition.previous_chain_hash != previous_chain_hash:
                raise SimulatedPortfolioLedgerError(
                    "transition previous_chain_hash does not match ledger tail"
                )
            if transition.input_state.state_hash != previous_output.state_hash:
                raise SimulatedPortfolioLedgerError(
                    "transition input state does not match ledger tail output"
                )
        elif transition.previous_chain_hash != ZERO_CHAIN_HASH:
            raise SimulatedPortfolioLedgerError(
                "first transition must use zero previous_chain_hash"
            )
        expected_hash = payload_hash(transition.canonical_payload())
        if transition.transition_hash != expected_hash:
            raise SimulatedPortfolioLedgerError("transition hash mismatch")
        expected_chain = payload_hash(
            {
                "schema_version": SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION,
                "clock_id": transition.clock_id,
                "previous_chain_hash": transition.previous_chain_hash,
                "transition_hash": transition.transition_hash,
            }
        )
        if transition.chain_hash != expected_chain:
            raise SimulatedPortfolioLedgerError("chain hash mismatch")
        placeholders = ", ".join("?" for _ in _TRANSITION_COLUMN_ORDER)
        connection.execute(
            f"INSERT INTO transitions({', '.join(_TRANSITION_COLUMN_ORDER)}) VALUES ({placeholders})",
            tuple(row_payload[field] for field in _TRANSITION_COLUMN_ORDER),
        )
        connection.commit()
        return SimulatedLedgerAppendResult(transition=transition, idempotent=False)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def summarize_simulated_ledger(
    sqlite_path: Path,
    *,
    clock: ProspectiveFormalClock,
) -> SimulatedLedgerSummary:
    """唯讀重驗 SQLite schema、state chain、transition hash 與 metadata。"""

    path = sqlite_path.expanduser().resolve()
    if not path.is_file():
        raise SimulatedPortfolioLedgerError("simulated ledger sqlite is missing")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        _ensure_schema(connection, create=False)
        _ensure_metadata(
            connection,
            clock_id=clock.clock_id,
            clock_manifest_hash=clock.manifest_hash,
            policy_hash=str(clock.payload["policy_hash"]),
            create=False,
        )
        rows = connection.execute(
            "SELECT * FROM transitions ORDER BY decision_date ASC"
        ).fetchall()
        previous_chain_hash = ZERO_CHAIN_HASH
        previous_output_hash: str | None = None
        dates: list[str] = []
        non_cash = 0
        for row in rows:
            transition = _transition_from_row(dict(row))
            expected_decision_time = time.fromisoformat(
                str(clock.payload["decision_time"])
            )
            _validate_transition(
                transition,
                expected_decision_time=expected_decision_time,
            )
            if transition.clock_id != clock.clock_id:
                raise SimulatedPortfolioLedgerError("row clock_id mismatch")
            if transition.clock_manifest_hash != clock.manifest_hash:
                raise SimulatedPortfolioLedgerError("row clock manifest hash mismatch")
            if transition.policy_hash != str(clock.payload["policy_hash"]):
                raise SimulatedPortfolioLedgerError("row policy hash mismatch")
            if transition.previous_chain_hash != previous_chain_hash:
                raise SimulatedPortfolioLedgerError("row previous chain hash mismatch")
            if previous_output_hash is not None and transition.input_state.state_hash != previous_output_hash:
                raise SimulatedPortfolioLedgerError("row input state chain mismatch")
            if transition.transition_hash != payload_hash(transition.canonical_payload()):
                raise SimulatedPortfolioLedgerError("stored transition hash mismatch")
            expected_chain = payload_hash(
                {
                    "schema_version": SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION,
                    "clock_id": transition.clock_id,
                    "previous_chain_hash": previous_chain_hash,
                    "transition_hash": transition.transition_hash,
                }
            )
            if transition.chain_hash != expected_chain:
                raise SimulatedPortfolioLedgerError("stored chain hash mismatch")
            if dates and transition.decision_date <= dates[-1]:
                raise SimulatedPortfolioLedgerError("ledger decision dates are not increasing")
            dates.append(transition.decision_date)
            non_cash += transition.input_state.weights.invested_bp > 0
            previous_chain_hash = transition.chain_hash
            previous_output_hash = transition.output_state.state_hash
        if not rows:
            raise SimulatedPortfolioLedgerError("simulated ledger has no transitions")
        return SimulatedLedgerSummary(
            schema_version=SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION,
            clock_id=clock.clock_id,
            clock_manifest_hash=clock.manifest_hash,
            policy_hash=str(clock.payload["policy_hash"]),
            decision_dates=tuple(dates),
            decision_date_count=len(dates),
            non_cash_state_day_count=non_cash,
            transition_chain_hash=previous_chain_hash,
            sqlite_file_hash=file_sha256(path),
        )
    finally:
        connection.close()


def _ensure_schema(connection: sqlite3.Connection, *, create: bool = True) -> None:
    if create:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_metadata(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transitions(
                clock_id TEXT NOT NULL,
                clock_manifest_hash TEXT NOT NULL,
                policy_hash TEXT NOT NULL,
                decision_date TEXT PRIMARY KEY,
                decision_at TEXT NOT NULL,
                previous_trading_day TEXT NOT NULL,
                input_state_json TEXT NOT NULL,
                desired_weights_json TEXT NOT NULL,
                output_state_json TEXT NOT NULL,
                feature_input_hash TEXT NOT NULL,
                buy_turnover_bp INTEGER NOT NULL,
                sell_turnover_bp INTEGER NOT NULL,
                canonical_turnover_bp INTEGER NOT NULL,
                estimated_cost_bp INTEGER NOT NULL,
                add_count INTEGER NOT NULL,
                reduce_count INTEGER NOT NULL,
                previous_chain_hash TEXT NOT NULL,
                future_teacher_target_used INTEGER NOT NULL CHECK(future_teacher_target_used = 0),
                same_day_advice_used INTEGER NOT NULL CHECK(same_day_advice_used = 0),
                transition_hash TEXT NOT NULL UNIQUE,
                chain_hash TEXT NOT NULL UNIQUE
            )
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS simulated_transitions_no_update
            BEFORE UPDATE ON transitions
            BEGIN
                SELECT RAISE(ABORT, 'append-only simulated ledger');
            END;
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS simulated_transitions_no_delete
            BEFORE DELETE ON transitions
            BEGIN
                SELECT RAISE(ABORT, 'append-only simulated ledger');
            END;
            """
        )
    required = {"ledger_metadata", "transitions"}
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not required.issubset(tables):
        raise SimulatedPortfolioLedgerError("simulated ledger schema is incomplete")
    columns = set(_table_columns(connection, "transitions"))
    if columns != _TRANSITION_FIELDS:
        raise SimulatedPortfolioLedgerError("simulated ledger transition schema is invalid")
    trigger_names = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    if not {
        "simulated_transitions_no_update",
        "simulated_transitions_no_delete",
    }.issubset(trigger_names):
        raise SimulatedPortfolioLedgerError(
            "simulated ledger append-only triggers are missing"
        )


def _ensure_metadata(
    connection: sqlite3.Connection,
    *,
    clock_id: str,
    clock_manifest_hash: str,
    policy_hash: str,
    create: bool = True,
) -> None:
    expected = {
        "schema_version": SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION,
        "clock_id": clock_id,
        "clock_manifest_hash": clock_manifest_hash,
        "policy_hash": policy_hash,
    }
    for key, value in expected.items():
        row = connection.execute(
            "SELECT value FROM ledger_metadata WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            if not create:
                raise SimulatedPortfolioLedgerError(
                    "simulated ledger metadata is incomplete"
                )
            connection.execute(
                "INSERT INTO ledger_metadata(key, value) VALUES (?, ?)",
                (key, value),
            )
        elif str(row[0]) != value:
            raise SimulatedPortfolioLedgerError(
                f"simulated ledger metadata mismatch: {key}"
            )
    actual_keys = {
        str(row[0])
        for row in connection.execute("SELECT key FROM ledger_metadata")
    }
    if actual_keys != set(expected):
        raise SimulatedPortfolioLedgerError("simulated ledger metadata fields are invalid")


def _validate_transition(
    transition: SimulatedPortfolioTransition,
    *,
    expected_decision_time: time | None = None,
) -> None:
    if transition.future_teacher_target_used or transition.same_day_advice_used:
        raise SimulatedPortfolioLedgerError(
            "simulated transition contains forbidden future input"
        )
    for field_name, value in (
        ("clock_manifest_hash", transition.clock_manifest_hash),
        ("policy_hash", transition.policy_hash),
        ("feature_input_hash", transition.feature_input_hash),
        ("previous_chain_hash", transition.previous_chain_hash),
        ("transition_hash", transition.transition_hash),
        ("chain_hash", transition.chain_hash),
    ):
        if not _is_sha256(value):
            raise SimulatedPortfolioLedgerError(f"{field_name} must be sha256")
    decision_day = _parse_date(transition.decision_date, "decision_date").isoformat()
    previous_day = _parse_date(
        transition.previous_trading_day, "previous_trading_day"
    ).isoformat()
    if previous_day >= decision_day:
        raise SimulatedPortfolioLedgerError(
            "previous_trading_day must be before decision_date"
        )
    if transition.input_state.as_of_date != previous_day:
        raise SimulatedPortfolioLedgerError(
            "input state must equal the supplied previous trading day"
        )
    if transition.output_state.as_of_date != decision_day:
        raise SimulatedPortfolioLedgerError(
            "output state must equal decision_date"
        )
    if transition.output_state.weights != transition.desired_weights:
        raise SimulatedPortfolioLedgerError(
            "output state weights must equal desired weights"
        )
    parsed_decision_at = _parse_decision_at(transition.decision_at)
    if parsed_decision_at.date().isoformat() != decision_day:
        raise SimulatedPortfolioLedgerError(
            "decision_at date does not match decision_date"
        )
    if (
        expected_decision_time is not None
        and parsed_decision_at.timetz().replace(tzinfo=None) != expected_decision_time
    ):
        raise SimulatedPortfolioLedgerError(
            "decision_at does not match clock decision_time"
        )
    integer_fields = (
        "buy_turnover_bp",
        "sell_turnover_bp",
        "canonical_turnover_bp",
        "estimated_cost_bp",
        "add_count",
        "reduce_count",
    )
    for field_name in integer_fields:
        value = getattr(transition, field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SimulatedPortfolioLedgerError(
                f"{field_name} must be non-negative integer"
            )
    current = dict(transition.input_state.weights.positions_bp)
    target = dict(transition.desired_weights.positions_bp)
    symbols = tuple(sorted(set(current) | set(target)))
    expected_buy = sum(
        max(target.get(symbol, 0) - current.get(symbol, 0), 0)
        for symbol in symbols
    )
    expected_sell = sum(
        max(current.get(symbol, 0) - target.get(symbol, 0), 0)
        for symbol in symbols
    )
    expected_turnover = canonical_turnover_bp(
        current_position_weights_bp=tuple(current.get(symbol, 0) for symbol in symbols),
        current_cash_bp=transition.input_state.weights.cash_bp,
        target_position_weights_bp=tuple(target.get(symbol, 0) for symbol in symbols),
        target_cash_bp=transition.desired_weights.cash_bp,
    )
    expected_add = sum(
        target.get(symbol, 0) > current.get(symbol, 0) for symbol in symbols
    )
    expected_reduce = sum(
        current.get(symbol, 0) > target.get(symbol, 0) for symbol in symbols
    )
    observed = {
        "buy_turnover_bp": transition.buy_turnover_bp,
        "sell_turnover_bp": transition.sell_turnover_bp,
        "canonical_turnover_bp": transition.canonical_turnover_bp,
        "add_count": transition.add_count,
        "reduce_count": transition.reduce_count,
    }
    expected = {
        "buy_turnover_bp": expected_buy,
        "sell_turnover_bp": expected_sell,
        "canonical_turnover_bp": expected_turnover,
        "add_count": expected_add,
        "reduce_count": expected_reduce,
    }
    if observed != expected:
        raise SimulatedPortfolioLedgerError(
            "simulated transition turnover metrics are inconsistent"
        )
    if transition.transition_hash != payload_hash(transition.canonical_payload()):
        raise SimulatedPortfolioLedgerError("transition hash mismatch")
    expected_chain = payload_hash(
        {
            "schema_version": SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION,
            "clock_id": transition.clock_id,
            "previous_chain_hash": transition.previous_chain_hash,
            "transition_hash": transition.transition_hash,
        }
    )
    if transition.chain_hash != expected_chain:
        raise SimulatedPortfolioLedgerError("chain hash mismatch")


def _transition_from_row(row: Mapping[str, object]) -> SimulatedPortfolioTransition:
    required = _TRANSITION_FIELDS - set(row)
    if required:
        raise SimulatedPortfolioLedgerError(
            "stored transition missing fields: " + ", ".join(sorted(required))
        )
    input_state = _state_from_json(str(row["input_state_json"]), "input_state")
    output_state = _state_from_json(str(row["output_state_json"]), "output_state")
    desired = _weights_from_json(str(row["desired_weights_json"]), "desired_weights")
    bool_fields = ("future_teacher_target_used", "same_day_advice_used")
    if any(row[field] != 0 for field in bool_fields):
        raise SimulatedPortfolioLedgerError("stored transition contains forbidden future input")
    integer_fields = (
        "buy_turnover_bp",
        "sell_turnover_bp",
        "canonical_turnover_bp",
        "estimated_cost_bp",
        "add_count",
        "reduce_count",
    )
    integers = {}
    for field in integer_fields:
        value = row[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SimulatedPortfolioLedgerError(f"stored {field} must be non-negative integer")
        integers[field] = value
    previous_chain_hash = str(row["previous_chain_hash"])
    for field_name, value in (
        ("feature_input_hash", row["feature_input_hash"]),
        ("previous_chain_hash", previous_chain_hash),
        ("transition_hash", row["transition_hash"]),
        ("chain_hash", row["chain_hash"]),
    ):
        if not _is_sha256(value):
            raise SimulatedPortfolioLedgerError(
                f"stored {field_name} must be sha256"
            )
    return SimulatedPortfolioTransition(
        clock_id=str(row["clock_id"]),
        clock_manifest_hash=str(row["clock_manifest_hash"]),
        policy_hash=str(row["policy_hash"]),
        decision_date=str(row["decision_date"]),
        decision_at=str(row["decision_at"]),
        previous_trading_day=str(row["previous_trading_day"]),
        input_state=input_state,
        desired_weights=desired,
        output_state=output_state,
        feature_input_hash=str(row["feature_input_hash"]),
        buy_turnover_bp=integers["buy_turnover_bp"],
        sell_turnover_bp=integers["sell_turnover_bp"],
        canonical_turnover_bp=integers["canonical_turnover_bp"],
        estimated_cost_bp=integers["estimated_cost_bp"],
        add_count=integers["add_count"],
        reduce_count=integers["reduce_count"],
        previous_chain_hash=previous_chain_hash,
        transition_hash=str(row["transition_hash"]),
        chain_hash=str(row["chain_hash"]),
    )


def _state_json(state: CausalPortfolioState) -> str:
    return canonical_json(
        {
            "as_of_date": state.as_of_date,
            "weights": _weight_payload(state.weights),
            "weekly_turnover_used_bp": state.weekly_turnover_used_bp,
            "state_hash": state.state_hash,
        }
    )


def _state_from_json(value: str, field_name: str) -> CausalPortfolioState:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SimulatedPortfolioLedgerError(f"{field_name} is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise SimulatedPortfolioLedgerError(f"{field_name} must be an object")
    if canonical_json(payload) != value:
        raise SimulatedPortfolioLedgerError(f"{field_name} must be canonical JSON")
    if set(payload) != {
        "as_of_date",
        "weights",
        "weekly_turnover_used_bp",
        "state_hash",
    }:
        raise SimulatedPortfolioLedgerError(f"{field_name} fields are invalid")
    weights = payload.get("weights")
    if not isinstance(weights, Mapping):
        raise SimulatedPortfolioLedgerError(f"{field_name}.weights must be an object")
    return CausalPortfolioState(
        as_of_date=str(payload.get("as_of_date")),
        weights=_weights_from_mapping(weights, f"{field_name}.weights"),
        weekly_turnover_used_bp=_required_nonnegative_int(
            payload.get("weekly_turnover_used_bp"),
            f"{field_name}.weekly_turnover_used_bp",
        ),
        state_hash=str(payload.get("state_hash")),
    )


def _weights_from_json(value: str, field_name: str) -> AllocationWeightContract:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SimulatedPortfolioLedgerError(f"{field_name} is invalid JSON") from exc
    if not isinstance(payload, Mapping) or canonical_json(payload) != value:
        raise SimulatedPortfolioLedgerError(f"{field_name} must be canonical object JSON")
    return _weights_from_mapping(payload, field_name)


def _weights_from_mapping(
    value: Mapping[str, object], field_name: str
) -> AllocationWeightContract:
    if set(value) != {"positions_bp", "cash_bp"}:
        raise SimulatedPortfolioLedgerError(f"{field_name} fields are invalid")
    positions = value.get("positions_bp")
    if not isinstance(positions, list):
        raise SimulatedPortfolioLedgerError(f"{field_name}.positions_bp must be an array")
    parsed: list[tuple[str, int]] = []
    for item in positions:
        if not isinstance(item, list) or len(item) != 2:
            raise SimulatedPortfolioLedgerError(f"{field_name}.positions_bp row invalid")
        symbol, weight = item
        if not isinstance(symbol, str) or not symbol.strip():
            raise SimulatedPortfolioLedgerError(f"{field_name}.symbol invalid")
        if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
            raise SimulatedPortfolioLedgerError(f"{field_name}.weight must be positive integer")
        parsed.append((symbol, weight))
    if parsed != sorted(parsed):
        raise SimulatedPortfolioLedgerError(f"{field_name}.positions_bp must be sorted")
    cash = value.get("cash_bp")
    if not isinstance(cash, int) or isinstance(cash, bool):
        raise SimulatedPortfolioLedgerError(f"{field_name}.cash_bp must be integer")
    try:
        return AllocationWeightContract(positions_bp=tuple(parsed), cash_bp=cash)
    except (TypeError, ValueError) as exc:
        raise SimulatedPortfolioLedgerError(str(exc)) from exc


def _weight_payload(weights: AllocationWeightContract) -> dict[str, object]:
    return {
        "positions_bp": [[symbol, value] for symbol, value in weights.positions_bp],
        "cash_bp": weights.cash_bp,
    }


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")'))


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise SimulatedPortfolioLedgerError(f"{field_name} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SimulatedPortfolioLedgerError(f"{field_name} is invalid") from exc


def _parse_decision_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SimulatedPortfolioLedgerError("decision_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SimulatedPortfolioLedgerError("decision_at must include timezone")
    return parsed.astimezone(TAIPEI_TIMEZONE)


def _required_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SimulatedPortfolioLedgerError(f"{field_name} must be non-negative integer")
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith(SHA256_PREFIX) and all(
        char in "0123456789abcdef" for char in value[len(SHA256_PREFIX) :]
    )
