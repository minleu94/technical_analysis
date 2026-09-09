"""Produce immutable, research-only exit effectiveness evidence.

The producer joins two existing append-only inputs:

* ``position_health_transitions`` supplies the proposal and its policy
  decision date; and
* ``paper_trade_ledger`` supplies the only evidence that a proposed exit was
  actually filled and closed.

Daily prices and the official calendar are read through bounded, read-only
   queries.  The resulting JSON is create-only.  A proposal can therefore
   receive a mature *counterfactual* outcome, while a realised metric is
   emitted only for a verified full Paper close with a stable entry lineage.
   This module never writes either source database and never sends an order.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from app_module.exit_effectiveness_read_model import (
    DEFAULT_EXIT_HORIZON_TRADING_DAYS,
    ExitEffectivenessObservation,
    ExitEffectivenessReadModel,
)
from app_module.outcome_maturity_service import OutcomeMaturityService
from app_module.paper_trade_ledger import PaperTradeFill
from app_module.position_health_transition_evaluator import (
    DEFAULT_POLICY_HASH as TRANSITION_POLICY_HASH,
)
from data_module.official_trading_calendar import OfficialTradingCalendar


SCHEMA_VERSION = "exit-effectiveness-evidence.v1"
POLICY_ID = "exit-effectiveness-research-policy.v1"
POLICY_HASH = "sha256:" + hashlib.sha256(
    b"exit-effectiveness-research-policy.v1|horizon=5-official-trading-days|"
    b"proposal-counterfactual-separate-from-closed"
).hexdigest()
MAX_TRANSITIONS = 2_500
MAX_LEDGER_ROWS = 250_000
MAX_PRICE_ROWS = 500_000
MAX_CORPORATE_ACTION_ROWS = 100_000
TAIPEI = timezone(timedelta(hours=8))
UTC = timezone.utc
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_POSITION_ID_RE = re.compile(
    r"^paper:(?P<portfolio>[^:]+):(?P<stock>[^:]+):entry-(?P<entry>[0-9a-f]{24})$"
)
_TRUSTED_PAPER_SOURCE_TYPES = frozenset(
    {
        "paper_simulation",
        "paper_daily_execution_v1",
        "paper_daily_execution_delayed_eod_replay_v1",
    }
)
_LEDGER_COLUMNS = (
    "schema_version",
    "fill_id",
    "order_id",
    "portfolio_id",
    "event_date",
    "stock_code",
    "side",
    "requested_quantity",
    "filled_quantity",
    "reference_price",
    "fill_price",
    "commission",
    "tax",
    "slippage_cost",
    "turnover_bp",
    "execution_gap_bp",
    "status",
    "source_event_id",
    "override_reason",
    "source_type",
    "research_only",
    "broker_order_allowed",
    "auto_rebalance_allowed",
)
_TRANSITION_COLUMNS = (
    "event_id",
    "position_id",
    "decision_date",
    "previous_state",
    "proposed_state",
    "recorded_state",
    "decision_kind",
    "reasons_json",
    "reviewer",
    "auto_action_allowed",
)
_PRICE_COLUMNS = ("日期", "證券代號", "收盤價")
_CLOSE_PRICE_COLUMNS = ("收盤價", "close", "close_price")
_PRICE_AVAILABILITY_COLUMNS = (
    "available_at",
    "data_available_at",
    "資料可得時間",
    "availableAt",
)
_MONEY_QUANTUM = Decimal("0.01")
_REALIZED_RETURN_BASIS = "net_cash_after_commission_tax_bp"
_COUNTERFACTUAL_RETURN_BASIS = "counterfactual_price_return_bp"


class ExitEffectivenessProducerError(ValueError):
    """A source or evidence boundary failed closed."""


@dataclass(frozen=True)
class _LedgerEvent:
    fill: PaperTradeFill
    canonical_row: Mapping[str, Any]
    row_hash: str


@dataclass(frozen=True)
class _ExecutionResolution:
    status: str
    entry: _LedgerEvent | None
    exit: _LedgerEvent | None
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _SourceSnapshot:
    path: Path
    file_hash: str
    rows_hash: str
    row_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "file_sha256": self.file_hash,
            "rows_sha256": self.rows_hash,
            "row_count": self.row_count,
            "read_only": True,
            "query_only": True,
        }


@dataclass(frozen=True)
class _PriceSnapshot:
    source: _SourceSnapshot
    values: Mapping[tuple[str, date], Decimal]
    invalid_keys: frozenset[tuple[str, date]]
    available_at: datetime
    row_available_at: Mapping[tuple[str, date], datetime | None]
    invalid_availability_keys: frozenset[tuple[str, date]]
    has_row_availability: bool


class _CalendarReader:
    """Read one bounded official-calendar window and retain its evidence."""

    def __init__(self, provider: Any, *, start: date, end: date) -> None:
        self.provider = provider
        self.start = start
        self.end = end
        self.unknown_dates: set[date] = set()
        self.trading_dates: set[date] = set()
        self.rows: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []
        try:
            result = provider.get_trading_days_in_range(
                start,
                end,
                allow_online_probe=False,
            )
        except TypeError:
            # Test doubles may expose the existing positional-only API.  The
            # production OfficialTradingCalendar always accepts the keyword.
            result = provider.get_trading_days_in_range(start, end, False)
        except Exception as exc:  # noqa: BLE001 - source boundary is fail closed
            raise ExitEffectivenessProducerError(
                f"official_calendar_read_failed:{type(exc).__name__}"
            ) from exc
        if not isinstance(result, Sequence):
            raise ExitEffectivenessProducerError("official_calendar_rows_invalid")
        for raw in result:
            if not isinstance(raw, Mapping):
                raise ExitEffectivenessProducerError("official_calendar_row_invalid")
            raw_date = raw.get("date", raw.get("date_str"))
            parsed = _parse_date(raw_date, "calendar_date")
            flag = raw.get("is_trading_day")
            reason_code = str(raw.get("reason_code") or "unknown")
            official_evidence_required = isinstance(provider, OfficialTradingCalendar)
            official_reason = reason_code.startswith(
                ("twse_holiday_schedule_", "twse_temporary_closure_official")
            )
            if flag is True and official_evidence_required and not official_reason:
                # The calendar's DB fallback proves that a row exists, but it
                # cannot prove that absent dates are closed.  Do not use it
                # as an ordinal-horizon source; require the hash-bound
                # official annual/closure evidence instead.
                self.unknown_dates.add(parsed)
            elif flag is True:
                self.trading_dates.add(parsed)
            elif flag is None:
                self.unknown_dates.add(parsed)
            self.rows.append(
                {
                    "date": parsed.isoformat(),
                    "is_trading_day": flag,
                    "reason_code": reason_code,
                }
            )
            if isinstance(provider, OfficialTradingCalendar):
                # ``evidence_for`` is a diagnostic API and may fall back to a
                # live TWSE request for a year that has no local cache.  A
                # scheduled producer is explicitly offline/read-only, so use
                # the already-loaded cache evidence instead of triggering a
                # network probe from an evidence-only read.
                continue
            if hasattr(provider, "evidence_for"):
                try:
                    evidence = provider.evidence_for(parsed)
                except Exception as exc:  # noqa: BLE001 - source boundary
                    raise ExitEffectivenessProducerError(
                        f"official_calendar_evidence_failed:{parsed}:{type(exc).__name__}"
                    ) from exc
                if isinstance(evidence, Mapping):
                    evidence_row: dict[str, Any] = {
                        "date": parsed.isoformat()
                    }
                    evidence_row.update(
                        {
                            str(key): _jsonable(item)
                            for key, item in evidence.items()
                        }
                    )
                    self.evidence.append(evidence_row)
        if not self.rows:
            raise ExitEffectivenessProducerError("official_calendar_rows_empty")
        loaded_evidence = getattr(provider, "_schedule_evidence", {})
        if isinstance(loaded_evidence, Mapping):
            for year, evidence in sorted(loaded_evidence.items(), key=lambda item: str(item[0])):
                if isinstance(evidence, Mapping):
                    self.evidence.append(
                        {
                            "calendar_year": str(year),
                            **{
                                str(key): _jsonable(item)
                                for key, item in evidence.items()
                            },
                        }
                    )
        self.source_hash = _sha256_json(
            {"rows": self.rows, "evidence": self.evidence}
        )

    def has_unknown(self, start: date, end: date) -> bool:
        return any(start <= item <= end for item in self.unknown_dates)

    def future_dates(
        self,
        reference_date: date,
        horizon_days: int,
        *,
        as_of_date: date,
    ) -> tuple[date | None, tuple[str, ...]]:
        upper = max(self.end, as_of_date)
        if reference_date >= upper:
            return None, ("official_calendar_horizon_unknown",)
        if self.has_unknown(reference_date + timedelta(days=1), upper):
            # Unknown weekdays before the target make the ordinal horizon
            # unknowable; weekends with a known False value are harmless.
            first_unknown = min(
                item
                for item in self.unknown_dates
                if reference_date < item <= upper
            )
            known_before_unknown = sum(
                1
                for item in self.trading_dates
                if reference_date < item < first_unknown
            )
            if known_before_unknown < horizon_days:
                return None, ("official_calendar_unknown",)
        dates = sorted(
            item for item in self.trading_dates if reference_date < item <= upper
        )
        if len(dates) < horizon_days:
            return None, ("official_calendar_horizon_unknown",)
        return dates[horizon_days - 1], ()

    def previous_date(self, decision_date: date) -> tuple[date | None, tuple[str, ...]]:
        start = self.start
        end = decision_date - timedelta(days=1)
        if end < start:
            return None, ("official_calendar_anchor_unknown",)
        if self.has_unknown(start, end):
            return None, ("official_calendar_anchor_unknown",)
        dates = [item for item in self.trading_dates if start <= item <= end]
        if not dates:
            return None, ("official_calendar_anchor_unknown",)
        return max(dates), ()


def _canonical_json(value: object) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [_jsonable(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(values, key=lambda item: _canonical_json(item))
        return values
    return value


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256(_canonical_json(value).encode("utf-8"))


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _parse_date(value: object, field_name: str) -> date:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ExitEffectivenessProducerError(f"{field_name}_invalid") from exc
    if parsed.isoformat() != text:
        raise ExitEffectivenessProducerError(f"{field_name}_must_be_iso_date")
    return parsed


def _parse_available_at(value: object, field_name: str) -> datetime | None:
    """Parse an optional row-level availability timestamp.

    A date-only or naive timestamp cannot establish a point-in-time boundary,
    so it is rejected as an invalid availability value instead of being
    silently interpreted in the machine's local timezone.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "nan"}:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExitEffectivenessProducerError(f"{field_name}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExitEffectivenessProducerError(f"{field_name}_must_be_timezone_aware")
    return parsed.astimezone(UTC)


def _parse_decimal(value: object, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ExitEffectivenessProducerError(f"{field_name}_missing")
    text = str(value).strip()
    if not text or text in {"--", "-", "null", "None", "nan", "NaN"}:
        raise ExitEffectivenessProducerError(f"{field_name}_invalid")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ExitEffectivenessProducerError(f"{field_name}_invalid") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ExitEffectivenessProducerError(f"{field_name}_non_positive")
    return parsed


def _return_bp(end_price: Decimal, start_price: Decimal) -> int:
    value = ((end_price / start_price) - Decimal("1")) * Decimal("10000")
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _net_realized_return_bp(
    entry: PaperTradeFill,
    exit: PaperTradeFill,
) -> int:
    """Return the realised return after cash settlement fees.

    ``fill_price`` already contains the execution price used by the Paper
    ledger.  Commission and tax are cash settlement costs and therefore are
    added to the buy cash and subtracted from the sell cash.  Slippage is
    retained in the ledger as an attribution field and is not deducted a
    second time from the already realised fill price.
    """

    if entry.fill_price is None or exit.fill_price is None:
        raise ExitEffectivenessProducerError("realized_return_fill_price_missing")
    if entry.filled_quantity <= 0 or exit.filled_quantity <= 0:
        raise ExitEffectivenessProducerError("realized_return_quantity_invalid")
    if entry.filled_quantity != exit.filled_quantity:
        raise ExitEffectivenessProducerError(
            "realized_return_multiple_entry_lots_unresolved"
        )
    entry_cash = (
        entry.fill_price * entry.filled_quantity + entry.cash_settlement_cost
    ).quantize(_MONEY_QUANTUM)
    exit_cash = (
        exit.fill_price * exit.filled_quantity - exit.cash_settlement_cost
    ).quantize(_MONEY_QUANTUM)
    if entry_cash <= 0 or exit_cash < 0:
        raise ExitEffectivenessProducerError("realized_return_cash_invalid")
    return _return_bp(exit_cash, entry_cash)


def _sqlite_read_uri(path: Path) -> str:
    return path.expanduser().resolve().as_uri() + "?mode=ro"


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _transition_rows(path: Path, *, as_of_date: date) -> tuple[list[dict[str, Any]], _SourceSnapshot]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ExitEffectivenessProducerError("transition_source_missing")
    before = _file_hash(path)
    rows: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(_sqlite_read_uri(path), uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            columns = _table_columns(connection, "position_health_transitions")
            if not set(_TRANSITION_COLUMNS).issubset(columns):
                raise ExitEffectivenessProducerError("transition_source_schema_invalid")
            raw_rows = connection.execute(
                """
                SELECT event_id, position_id, decision_date, previous_state,
                       proposed_state, recorded_state, decision_kind,
                       reasons_json, reviewer, auto_action_allowed
                FROM position_health_transitions
                WHERE proposed_state = 'EXIT_CANDIDATE'
                ORDER BY decision_date, event_id
                LIMIT ?
                """,
                (MAX_TRANSITIONS + 1,),
            ).fetchall()
            if len(raw_rows) > MAX_TRANSITIONS:
                raise ExitEffectivenessProducerError("transition_source_bounded_limit")
            for raw in raw_rows:
                item = {column: raw[column] for column in _TRANSITION_COLUMNS}
                item["decision_date"] = _parse_date(
                    item["decision_date"], "transition_decision_date"
                ).isoformat()
                if date.fromisoformat(item["decision_date"]) > as_of_date:
                    raise ExitEffectivenessProducerError(
                        f"transition_decision_date_in_future:{item['event_id']}"
                    )
                if item["decision_kind"] not in {"proposal", "human_approved"}:
                    raise ExitEffectivenessProducerError(
                        f"transition_decision_kind_invalid:{item['event_id']}"
                    )
                try:
                    reasons = json.loads(str(item["reasons_json"]))
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ExitEffectivenessProducerError(
                        f"transition_reasons_invalid:{item['event_id']}"
                    ) from exc
                if not isinstance(reasons, list) or not all(
                    isinstance(value, str) and value.strip() for value in reasons
                ):
                    raise ExitEffectivenessProducerError(
                        f"transition_reasons_invalid:{item['event_id']}"
                    )
                item["reasons"] = tuple(str(value) for value in reasons)
                item["row_hash"] = _sha256_json(item)
                rows.append(item)
    except ExitEffectivenessProducerError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise ExitEffectivenessProducerError(
            f"transition_source_read_failed:{type(exc).__name__}"
        ) from exc
    after = _file_hash(path)
    if before != after:
        raise ExitEffectivenessProducerError("transition_source_changed_during_read")
    snapshot = _SourceSnapshot(path, before, _sha256_json(rows), len(rows))
    return rows, snapshot


def _fill_from_row(row: Mapping[str, Any]) -> PaperTradeFill:
    return PaperTradeFill(
        fill_id=str(row["fill_id"]),
        order_id=str(row["order_id"]),
        portfolio_id=str(row["portfolio_id"]),
        event_date=_parse_date(row["event_date"], "ledger_event_date").isoformat(),
        stock_code=str(row["stock_code"]),
        side=str(row["side"]),
        requested_quantity=int(row["requested_quantity"]),
        filled_quantity=int(row["filled_quantity"]),
        reference_price=Decimal(str(row["reference_price"])),
        fill_price=(
            None
            if row["fill_price"] is None
            else Decimal(str(row["fill_price"]))
        ),
        commission=Decimal(str(row["commission"])),
        tax=Decimal(str(row["tax"])),
        slippage_cost=Decimal(str(row["slippage_cost"])),
        turnover_bp=(None if row["turnover_bp"] is None else int(row["turnover_bp"])),
        execution_gap_bp=(
            None
            if row["execution_gap_bp"] is None
            else int(row["execution_gap_bp"])
        ),
        status=str(row["status"]),
        source_event_id=str(row["source_event_id"]),
        override_reason=(
            None if row["override_reason"] is None else str(row["override_reason"])
        ),
        source_type=str(row["source_type"]),
        research_only=bool(row["research_only"]),
        broker_order_allowed=bool(row["broker_order_allowed"]),
        auto_rebalance_allowed=bool(row["auto_rebalance_allowed"]),
    )


def _ledger_rows(path: Path, *, as_of_date: date) -> tuple[list[_LedgerEvent], _SourceSnapshot, frozenset[tuple[str, str, str]]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ExitEffectivenessProducerError("paper_ledger_source_missing")
    before = _file_hash(path)
    events: list[_LedgerEvent] = []
    try:
        with sqlite3.connect(_sqlite_read_uri(path), uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            columns = _table_columns(connection, "paper_trade_ledger")
            if not set(_LEDGER_COLUMNS).issubset(columns):
                raise ExitEffectivenessProducerError("paper_ledger_source_schema_invalid")
            raw_rows = connection.execute(
                "SELECT "
                + ", ".join(f'"{column}"' for column in _LEDGER_COLUMNS)
                + " FROM paper_trade_ledger ORDER BY event_date, stock_code, fill_id LIMIT ?",
                (MAX_LEDGER_ROWS + 1,),
            ).fetchall()
            if len(raw_rows) > MAX_LEDGER_ROWS:
                raise ExitEffectivenessProducerError("paper_ledger_source_bounded_limit")
            for raw in raw_rows:
                item = {column: raw[column] for column in _LEDGER_COLUMNS}
                fill = _fill_from_row(item)
                canonical = dict(item)
                event = _LedgerEvent(fill, canonical, _sha256_json(canonical))
                events.append(event)
    except ExitEffectivenessProducerError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError, InvalidOperation) as exc:
        raise ExitEffectivenessProducerError(
            f"paper_ledger_source_read_failed:{type(exc).__name__}"
        ) from exc
    after = _file_hash(path)
    if before != after:
        raise ExitEffectivenessProducerError("paper_ledger_source_changed_during_read")
    canonical_rows = [dict(event.canonical_row) for event in events]
    ambiguous: set[tuple[str, str, str]] = set()
    by_day: dict[tuple[str, str, str], list[_LedgerEvent]] = defaultdict(list)
    for event in events:
        fill = event.fill
        if fill.filled_quantity > 0:
            by_day[(fill.portfolio_id, fill.stock_code, fill.event_date)].append(event)
        if _parse_date(fill.event_date, "ledger_event_date") > as_of_date:
            # Future ledger rows are retained for provenance, but every
            # observation using that source receives a visible limitation.
            continue
    for key, same_day in by_day.items():
        if len(same_day) > 1:
            ambiguous.add(key)
    snapshot = _SourceSnapshot(path, before, _sha256_json(canonical_rows), len(events))
    return events, snapshot, frozenset(ambiguous)


def _price_rows(
    path: Path,
    *,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
) -> _PriceSnapshot:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ExitEffectivenessProducerError("market_price_source_missing")
    before = _file_hash(path)
    values: dict[tuple[str, date], Decimal] = {}
    invalid: set[tuple[str, date]] = set()
    row_available_at: dict[tuple[str, date], datetime | None] = {}
    invalid_availability: set[tuple[str, date]] = set()
    canonical_rows: list[dict[str, Any]] = []
    has_row_availability = False
    try:
        with sqlite3.connect(_sqlite_read_uri(path), uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            columns = _table_columns(connection, "daily_prices")
            if not set(_PRICE_COLUMNS).issubset(columns):
                # Allow the normalized English spelling used by a few
                # isolated fixtures while remaining explicit about schema.
                english = {"date", "stock_code", "close_price"}
                if not english.issubset(columns):
                    raise ExitEffectivenessProducerError("market_price_source_schema_invalid")
                date_column, symbol_column, close_column = "date", "stock_code", "close_price"
            else:
                date_column, symbol_column, close_column = _PRICE_COLUMNS
            availability_column = next(
                (
                    candidate
                    for candidate in _PRICE_AVAILABILITY_COLUMNS
                    if candidate in columns
                ),
                None,
            )
            has_row_availability = availability_column is not None
            if not symbols:
                raw_rows: list[sqlite3.Row] = []
            else:
                placeholders = ",".join("?" for _ in symbols)
                if date_column == "日期":
                    date_expression = "REPLACE(REPLACE(TRIM(\"日期\"), '-', ''), '/', '')"
                else:
                    date_expression = 'REPLACE(REPLACE(TRIM("date"), \'-\', \'\'), \'/\', \'\')'
                availability_expression = (
                    f'"{availability_column}" AS source_available_at'
                    if availability_column is not None
                    else "NULL AS source_available_at"
                )
                query = (
                    f'SELECT "{date_column}" AS source_date, '
                    f'"{symbol_column}" AS source_symbol, "{close_column}" AS source_close, '
                    f"{availability_expression} "
                    "FROM daily_prices WHERE CAST(\"%s\" AS TEXT) IN (%s) "
                    "AND %s BETWEEN ? AND ? ORDER BY source_date, source_symbol"
                    % (symbol_column, placeholders, date_expression)
                )
                raw_rows = connection.execute(
                    query,
                    tuple(symbols) + (
                        start_date.strftime("%Y%m%d"),
                        end_date.strftime("%Y%m%d"),
                    ),
                ).fetchall()
            if len(raw_rows) > MAX_PRICE_ROWS:
                raise ExitEffectivenessProducerError("market_price_source_bounded_limit")
            for raw in raw_rows:
                try:
                    parsed_date = _parse_date(raw["source_date"], "market_price_date")
                except ExitEffectivenessProducerError:
                    continue
                symbol = str(raw["source_symbol"]).strip()
                key = (symbol, parsed_date)
                raw_available_at = raw["source_available_at"]
                parsed_available_at: datetime | None = None
                if has_row_availability:
                    try:
                        parsed_available_at = _parse_available_at(
                            raw_available_at,
                            "market_price_available_at",
                        )
                    except ExitEffectivenessProducerError:
                        invalid_availability.add(key)
                    row_available_at[key] = parsed_available_at
                canonical = {
                    "date": parsed_date.isoformat(),
                    "stock_code": symbol,
                    "close_price": None if raw["source_close"] is None else str(raw["source_close"]),
                    "available_at": (
                        None
                        if raw_available_at is None
                        else str(raw_available_at)
                    ),
                }
                canonical_rows.append(canonical)
                try:
                    value = _parse_decimal(raw["source_close"], "market_close")
                except ExitEffectivenessProducerError:
                    invalid.add(key)
                    continue
                values[key] = value
    except ExitEffectivenessProducerError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise ExitEffectivenessProducerError(
            f"market_price_source_read_failed:{type(exc).__name__}"
        ) from exc
    after = _file_hash(path)
    if before != after:
        raise ExitEffectivenessProducerError("market_price_source_changed_during_read")
    available_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return _PriceSnapshot(
        source=_SourceSnapshot(path, before, _sha256_json(canonical_rows), len(canonical_rows)),
        values=values,
        invalid_keys=frozenset(invalid),
        available_at=available_at,
        row_available_at=row_available_at,
        invalid_availability_keys=frozenset(invalid_availability),
        has_row_availability=has_row_availability,
    )


def _corporate_action_rows(path: Path) -> tuple[dict[str, Any], _SourceSnapshot, bool]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ExitEffectivenessProducerError("corporate_action_source_unavailable")
    before = _file_hash(path)
    rows: list[dict[str, Any]] = []
    available = False
    try:
        with sqlite3.connect(_sqlite_read_uri(path), uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "corporate_action_events" in tables:
                columns = _table_columns(connection, "corporate_action_events")
                required = {"stock_code", "event_date", "event_type"}
                if not required.issubset(columns):
                    raise ExitEffectivenessProducerError("corporate_action_source_schema_invalid")
                available = True
                raw_rows = connection.execute(
                    "SELECT stock_code, event_date, event_type "
                    "FROM corporate_action_events ORDER BY event_date, stock_code LIMIT ?",
                    (MAX_CORPORATE_ACTION_ROWS + 1,),
                ).fetchall()
                if len(raw_rows) > MAX_CORPORATE_ACTION_ROWS:
                    raise ExitEffectivenessProducerError("corporate_action_source_bounded_limit")
                for raw in raw_rows:
                    try:
                        event_date = _parse_date(raw["event_date"], "corporate_action_date")
                    except ExitEffectivenessProducerError:
                        continue
                    rows.append(
                        {
                            "stock_code": str(raw["stock_code"]),
                            "event_date": event_date.isoformat(),
                            "event_type": str(raw["event_type"]),
                        }
                    )
    except ExitEffectivenessProducerError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise ExitEffectivenessProducerError(
            f"corporate_action_source_read_failed:{type(exc).__name__}"
        ) from exc
    after = _file_hash(path)
    if before != after:
        raise ExitEffectivenessProducerError("corporate_action_source_changed_during_read")
    snapshot = _SourceSnapshot(path, before, _sha256_json(rows), len(rows))
    return {"rows": rows}, snapshot, available


def _position_parts(position_id: object) -> tuple[str, str, str] | None:
    match = _POSITION_ID_RE.fullmatch(str(position_id or "").strip())
    if match is None:
        return None
    return match.group("portfolio"), match.group("stock"), match.group("entry")


def _derived_position_suffix(event: _LedgerEvent) -> str:
    return event.row_hash.split(":", 1)[1][:24]


def _execution_for_transition(
    transition: Mapping[str, Any],
    *,
    events: Sequence[_LedgerEvent],
    ambiguous: frozenset[tuple[str, str, str]],
    as_of_date: date,
) -> _ExecutionResolution:
    parts = _position_parts(transition.get("position_id"))
    if parts is None:
        return _ExecutionResolution(
            "not_executed", None, None, ("position_lineage_unverified",)
        )
    portfolio, stock, suffix = parts
    decision_date = date.fromisoformat(str(transition["decision_date"]))
    selected = [
        event
        for event in events
        if event.fill.portfolio_id == portfolio and event.fill.stock_code == stock
    ]
    selected.sort(key=lambda item: (item.fill.event_date, item.fill.fill_id))
    limitations: list[str] = []
    if any(event.fill.source_type not in _TRUSTED_PAPER_SOURCE_TYPES for event in selected):
        limitations.append("paper_ledger_source_type_unverified")
    if any(
        _parse_date(event.fill.event_date, "ledger_event_date") > as_of_date
        for event in selected
    ):
        limitations.append("paper_ledger_future_dated")
    if any(
        (event.fill.portfolio_id, event.fill.stock_code, event.fill.event_date)
        in ambiguous
        for event in selected
        if event.fill.filled_quantity > 0
    ):
        limitations.append("paper_ledger_event_order_ambiguous")
    # Same-day material execution has no time/sequence in v1.  A sell on the
    # decision date therefore cannot be safely assigned before/after the
    # proposal and is kept as research-only pending evidence.
    if any(
        event.fill.filled_quantity > 0
        and event.fill.event_date == decision_date.isoformat()
        for event in selected
    ):
        limitations.append("paper_ledger_decision_day_order_ambiguous")

    holdings = 0
    entry: _LedgerEvent | None = None
    entry_index: int | None = None
    invalid = False
    for index, event in enumerate(selected):
        fill = event.fill
        event_date = date.fromisoformat(fill.event_date)
        if event_date > decision_date:
            break
        if fill.filled_quantity <= 0:
            continue
        if fill.side == "buy":
            if holdings == 0:
                entry = event
                entry_index = index
            holdings += fill.filled_quantity
        elif fill.side == "sell":
            if fill.filled_quantity > holdings:
                invalid = True
                break
            holdings -= fill.filled_quantity
            if holdings == 0:
                entry = None
                entry_index = None
        else:
            invalid = True
            break
    if invalid:
        return _ExecutionResolution(
            "ambiguous", None, None, tuple(dict.fromkeys((*limitations, "paper_ledger_lineage_invalid")))
        )
    if entry is None or entry_index is None or _derived_position_suffix(entry) != suffix:
        return _ExecutionResolution(
            "not_executed", None, None, tuple(dict.fromkeys((*limitations, "position_lineage_unverified")))
        )

    sold_quantity = 0
    rejected_sell = False
    exit_event: _LedgerEvent | None = None
    for event in selected[entry_index + 1 :]:
        fill = event.fill
        event_date = date.fromisoformat(fill.event_date)
        if event_date <= decision_date:
            continue
        if event_date > as_of_date:
            continue
        if fill.side == "buy" and fill.filled_quantity > 0:
            holdings += fill.filled_quantity
            continue
        if fill.side != "sell":
            continue
        if fill.filled_quantity <= 0:
            if fill.status in {"rejected", "cancelled"}:
                rejected_sell = True
            continue
        if fill.filled_quantity > holdings:
            limitations.append("paper_ledger_lineage_invalid")
            return _ExecutionResolution(
                "ambiguous", entry, None, tuple(dict.fromkeys(limitations))
            )
        holdings -= fill.filled_quantity
        sold_quantity += fill.filled_quantity
        if holdings == 0:
            exit_event = event
            break
    if exit_event is not None:
        return _ExecutionResolution(
            "closed", entry, exit_event, tuple(dict.fromkeys(limitations))
        )
    if sold_quantity > 0:
        limitations.append("partial_exit_not_closed")
        return _ExecutionResolution(
            "partially_filled", entry, None, tuple(dict.fromkeys(limitations))
        )
    if rejected_sell:
        limitations.append("sell_rejected")
        return _ExecutionResolution(
            "rejected", entry, None, tuple(dict.fromkeys(limitations))
        )
    return _ExecutionResolution("not_executed", entry, None, tuple(dict.fromkeys(limitations)))


def _reason_code(reasons: Iterable[str]) -> str:
    values = tuple(str(item).strip() for item in reasons if str(item).strip())
    for value in values:
        if value.startswith("invalidation_triggered:"):
            return value
    for value in values:
        if value.startswith("condition:"):
            return value
    return values[0] if values else "exit_candidate"


def _decision_cutoff(date_value: date) -> datetime:
    """The fixed daily exit decision cutoff used by the research lane."""

    return datetime.combine(date_value, datetime.min.time(), tzinfo=TAIPEI) + timedelta(
        hours=8,
        minutes=30,
    )


def _row_availability_limits(
    prices: _PriceSnapshot,
    key: tuple[str, date],
    *,
    cutoff: datetime,
    now: datetime,
    purpose: str,
) -> tuple[str, ...]:
    """Return explicit limits for one price row's PIT availability.

    File mtime is intentionally not consulted here.  An updated SQLite file
    can contain old rows whose own availability remains valid; using the
    container mtime would permanently invalidate those rows.  A source that
    has no row-level availability remains usable for a matured outcome
    through its read-time mtime, but cannot establish a decision-time anchor.
    """

    if not prices.has_row_availability:
        return (
            ("anchor_price_pit_availability_unproven",)
            if purpose == "anchor"
            else ()
        )
    if key in prices.invalid_availability_keys:
        return (
            "anchor_price_pit_availability_unproven"
            if purpose == "anchor"
            else "outcome_price_availability_unproven",
        )
    available_at = prices.row_available_at.get(key)
    if available_at is None:
        return (
            "anchor_price_pit_availability_unproven"
            if purpose == "anchor"
            else "outcome_price_availability_unproven",
        )
    limits: list[str] = []
    if available_at > now.astimezone(UTC):
        limits.append("market_price_source_future")
    if purpose == "anchor" and available_at > cutoff.astimezone(UTC):
        limits.append("anchor_price_available_after_decision")
    return tuple(limits)


def _create_only(path: Path, encoded: bytes) -> tuple[Path, str]:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() == encoded:
            return target, "reused"
        digest = hashlib.sha256(encoded).hexdigest()[:16]
        target = target.with_name(f"{target.stem}_{digest}{target.suffix}")
        if target.exists():
            if target.read_bytes() == encoded:
                return target, "reused"
            raise ExitEffectivenessProducerError("immutable_output_hash_collision")
    fd, temporary_name = tempfile.mkstemp(prefix=".exit-effectiveness-", dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() == encoded:
                return target, "reused"
            raise ExitEffectivenessProducerError("immutable_output_conflict")
    finally:
        if temporary.exists():
            temporary.unlink()
    return target, "inserted"


def _make_observation(
    *,
    transition: Mapping[str, Any],
    execution: _ExecutionResolution,
    calendar: _CalendarReader,
    prices: _PriceSnapshot,
    corporate_rows: Sequence[Mapping[str, Any]],
    corporate_source_available: bool,
    ledger_snapshot: _SourceSnapshot,
    calendar_hash: str,
    as_of_date: date,
    now: datetime,
    horizon_days: int,
) -> ExitEffectivenessObservation:
    decision_date = date.fromisoformat(str(transition["decision_date"]))
    reasons = tuple(str(item) for item in transition.get("reasons", ()))
    reason_code = _reason_code(reasons)
    stage = "closed" if execution.status == "closed" else str(transition["decision_kind"])
    limitations = list(execution.limitations)
    parts = _position_parts(transition.get("position_id"))
    stock_code = parts[1] if parts is not None else None

    anchor_date: date | None = None
    anchor_limits: tuple[str, ...] = ()
    if execution.status != "closed":
        anchor_date, anchor_limits = calendar.previous_date(decision_date)
        limitations.extend(anchor_limits)
    anchor_price: Decimal | None = None
    if execution.status != "closed" and stock_code is not None and anchor_date is not None:
        key = (stock_code, anchor_date)
        anchor_price = prices.values.get(key)
        if anchor_price is None:
            limitations.append(
                "anchor_price_invalid" if key in prices.invalid_keys else "anchor_price_missing"
            )
        else:
            limitations.extend(
                _row_availability_limits(
                    prices,
                    key,
                    cutoff=_decision_cutoff(decision_date),
                    now=now,
                    purpose="anchor",
                )
            )
    elif execution.status != "closed":
        limitations.append("anchor_price_unavailable")

    reference_date = anchor_date
    baseline_price = anchor_price
    realized_return: int | None = None
    realized_return_basis = (
        _REALIZED_RETURN_BASIS
        if execution.status == "closed"
        else _COUNTERFACTUAL_RETURN_BASIS
    )
    exit_date: str | None = None
    exit_fill_id: str | None = None
    exit_evidence_hash: str | None = None
    entry_fill_id: str | None = None
    entry_evidence_hash: str | None = None
    if execution.entry is not None:
        entry_fill_id = execution.entry.fill.fill_id
        entry_evidence_hash = execution.entry.row_hash
        if execution.entry.fill.fill_price is not None:
            # A closed outcome is measured from the verified entry fill.  The
            # counterfactual proposal remains anchored to the prior official
            # close above, which avoids turning an unfilled proposal into a
            # realised trade.
            if execution.status == "closed":
                baseline_price = execution.entry.fill.fill_price
    if execution.exit is not None:
        exit_date = execution.exit.fill.event_date
        exit_fill_id = execution.exit.fill.fill_id
        exit_evidence_hash = execution.exit.row_hash
        reference_date = date.fromisoformat(exit_date)
        baseline_price = execution.exit.fill.fill_price
        if (
            execution.entry is None
            or execution.entry.fill.fill_price is None
            or execution.exit.fill.fill_price is None
        ):
            limitations.append("closed_fill_price_missing")
        else:
            try:
                realized_return = _net_realized_return_bp(
                    execution.entry.fill,
                    execution.exit.fill,
                )
            except ExitEffectivenessProducerError:
                limitations.append("realized_return_cost_basis_invalid")
                realized_return = None

    if not corporate_source_available:
        limitations.append("corporate_action_source_unavailable")
    else:
        for row in corporate_rows:
            if str(row.get("stock_code")) != str(stock_code):
                continue
            event_date = _parse_date(row.get("event_date"), "corporate_action_date")
            if reference_date is not None and reference_date < event_date:
                # The target is not known yet; the interval is checked again
                # below once the maturity date is selected.
                continue

    target_date, target_limits = (
        calendar.future_dates(
            reference_date,
            horizon_days,
            as_of_date=as_of_date,
        )
        if reference_date is not None
        else (None, ("official_calendar_horizon_unknown",))
    )
    limitations.extend(target_limits)
    if target_date is not None and not target_limits and reference_date is not None:
        # Keep the ordinal-window semantics in one shared service.  The
        # calendar reader remains responsible for rejecting unknown official
        # dates before this service is allowed to call a window mature.
        maturity = OutcomeMaturityService().evaluate(
            event_date=reference_date.isoformat(),
            window_days=horizon_days,
            trading_dates=tuple(
                item.isoformat() for item in sorted(calendar.trading_dates)
            ),
            as_of_date=as_of_date.isoformat(),
        )
        if maturity.expected_trading_date is None:
            target_date = None
            limitations.append("official_calendar_horizon_unknown")
        else:
            target_date = date.fromisoformat(maturity.expected_trading_date)
    if target_date is None:
        maturity_status = "pending"
        outcome_return = None
    elif target_date > as_of_date:
        maturity_status = "pending"
        outcome_return = None
    else:
        maturity_status = "ready"
        outcome_return = None
        if baseline_price is None or stock_code is None:
            limitations.append("outcome_baseline_price_missing")
        else:
            key = (stock_code, target_date)
            target_price = prices.values.get(key)
            if target_price is None:
                limitations.append(
                    "outcome_price_invalid" if key in prices.invalid_keys else "outcome_price_missing"
                )
            else:
                outcome_return = _return_bp(target_price, baseline_price)
            limitations.extend(
                _row_availability_limits(
                    prices,
                    key,
                    cutoff=now,
                    now=now,
                    purpose="outcome",
                )
            )
        if not prices.has_row_availability and prices.available_at > now.astimezone(UTC):
            # A legacy source without row-level timestamps can only be used
            # as a matured read-time outcome source through its file mtime.
            limitations.append("market_price_source_future")
        if corporate_source_available:
            for row in corporate_rows:
                if str(row.get("stock_code")) != str(stock_code):
                    continue
                event_date = _parse_date(row.get("event_date"), "corporate_action_date")
                if reference_date is not None and reference_date < event_date <= target_date:
                    limitations.append("corporate_action_window_affected")

    unique_limits = tuple(dict.fromkeys(item for item in limitations if item))
    # Source/temporal limitations prevent a mature row from being credited;
    # the row remains visible as pending with its exact reason.  Execution
    # limitations also keep partial/rejected proposals out of counterfactual
    # aggregates while preserving them for audit.
    if unique_limits and maturity_status == "ready":
        maturity_status = "pending"
        outcome_return = None
    post_exit = outcome_return if execution.status == "closed" else None
    counterfactual = outcome_return if execution.status != "closed" else None
    observation = ExitEffectivenessObservation(
        event_id=str(transition["event_id"]),
        reason_code=reason_code,
        maturity_status=maturity_status,
        action_stage=stage,
        realized_return_bp=realized_return if execution.status == "closed" else None,
        post_exit_return_bp=post_exit,
        counterfactual_post_exit_return_bp=counterfactual,
        horizon_trading_days=horizon_days,
        policy_id=POLICY_ID,
        position_id=(None if parts is None else str(transition["position_id"])),
        stock_code=stock_code,
        decision_date=decision_date.isoformat(),
        exit_date=exit_date,
        outcome_date=(None if target_date is None else target_date.isoformat()),
        execution_status=execution.status,
        limitation_codes=unique_limits,
        transition_hash=str(transition["row_hash"]),
        paper_ledger_rows_hash=ledger_snapshot.rows_hash,
        price_source_hash=prices.source.file_hash,
        calendar_source_hash=calendar_hash,
        transition_reasons=reasons,
        entry_fill_id=entry_fill_id,
        exit_fill_id=exit_fill_id,
        entry_evidence_hash=entry_evidence_hash,
        exit_evidence_hash=exit_evidence_hash,
        realized_return_basis=realized_return_basis,
    )
    body = observation.to_dict()
    body.pop("observation_hash", None)
    object.__setattr__(observation, "observation_hash", _sha256_json(body))
    return observation


def _base_payload(*, now: datetime, as_of_date: date) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "generated_at": now.astimezone(UTC).isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "policy_id": POLICY_ID,
        "policy_hash": POLICY_HASH,
        "transition_policy_hash": TRANSITION_POLICY_HASH,
        "horizon_trading_days": DEFAULT_EXIT_HORIZON_TRADING_DAYS,
        "observations": [],
        "report": ExitEffectivenessReadModel().build(observations=()).to_dict(),
        "research_only": True,
        "formal_credit": False,
        "investment_effectiveness_claim": False,
        "auto_exit_allowed": False,
        "broker_order_allowed": False,
        "historical_backfill": False,
        "warnings": [],
        "blockers": [],
    }


def produce_exit_effectiveness(
    *,
    transition_db: str | Path,
    paper_ledger_db: str | Path,
    market_db: str | Path,
    output: str | Path,
    calendar_cache: str | Path | None = None,
    temporary_closure_cache: str | Path | None = None,
    now: datetime | None = None,
    calendar: Any | None = None,
    horizon_trading_days: int = DEFAULT_EXIT_HORIZON_TRADING_DAYS,
) -> dict[str, Any]:
    """Build and create-only publish one bounded daily exit evidence payload.

    ``now`` and ``calendar`` are injectable solely for isolated tests.  The
    public CLI never exposes a historical as-of switch, so daily execution
    cannot silently backfill natural credit.
    """

    observed_now = now or datetime.now(UTC)
    if observed_now.tzinfo is None or observed_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    observed_now = observed_now.astimezone(UTC)
    as_of_date = observed_now.astimezone(TAIPEI).date()
    if (
        isinstance(horizon_trading_days, bool)
        or not isinstance(horizon_trading_days, int)
        or horizon_trading_days <= 0
    ):
        raise ValueError("horizon_trading_days must be a positive integer")
    payload = _base_payload(now=observed_now, as_of_date=as_of_date)
    try:
        transitions, transition_source = _transition_rows(
            Path(transition_db), as_of_date=as_of_date
        )
        ledger_events, ledger_source, ambiguous = _ledger_rows(
            Path(paper_ledger_db), as_of_date=as_of_date
        )
        if calendar is None:
            calendar = OfficialTradingCalendar(
                Path(market_db),
                calendar_cache_path=calendar_cache,
                temporary_closure_path=temporary_closure_cache,
            )
        if transitions:
            transition_dates = [date.fromisoformat(str(row["decision_date"])) for row in transitions]
            calendar_start = min(transition_dates) - timedelta(days=90)
        else:
            calendar_start = as_of_date - timedelta(days=90)
        calendar_end = as_of_date + timedelta(days=120)
        calendar_reader = _CalendarReader(calendar, start=calendar_start, end=calendar_end)
        symbols = sorted(
            {
                event.fill.stock_code
                for event in ledger_events
            }
            | {
                parts[1]
                for row in transitions
                if (parts := _position_parts(row.get("position_id"))) is not None
            }
        )
        price_source = _price_rows(
            Path(market_db),
            symbols=symbols,
            start_date=calendar_start,
            end_date=as_of_date,
        )
        corporate_data, corporate_source, corporate_available = _corporate_action_rows(
            Path(market_db)
        )
        rows = [
            _make_observation(
                transition=transition,
                execution=_execution_for_transition(
                    transition,
                    events=ledger_events,
                    ambiguous=ambiguous,
                    as_of_date=as_of_date,
                ),
                calendar=calendar_reader,
                prices=price_source,
                corporate_rows=tuple(corporate_data["rows"]),
                corporate_source_available=corporate_available,
                ledger_snapshot=ledger_source,
                calendar_hash=calendar_reader.source_hash,
                as_of_date=as_of_date,
                now=observed_now,
                horizon_days=horizon_trading_days,
            )
            for transition in transitions
        ]
        report = ExitEffectivenessReadModel().build(observations=rows)
        has_pending = any(row.maturity_status == "pending" for row in rows)
        has_limits = any(bool(row.limitation_codes) for row in rows)
        no_transition_rows = not transitions
        payload.update(
            {
                "status": (
                    "degraded"
                    if has_pending or has_limits or no_transition_rows
                    else "passed"
                ),
                "observations": [row.to_dict() for row in rows],
                "report": report.to_dict(),
                "transition_count": len(transitions),
                "actual_closed_count": sum(1 for row in rows if row.is_actual_closed),
                "counterfactual_ready_count": sum(
                    1
                    for row in rows
                    if row.maturity_status == "ready"
                    and row.action_stage in {"proposal", "human_approved"}
                ),
                "source_provenance": {
                    "transitions": transition_source.to_dict(),
                    "paper_ledger": ledger_source.to_dict(),
                    "market_prices": price_source.source.to_dict(),
                    "market_prices_available_at": price_source.available_at.isoformat(),
                    "market_prices_row_level_availability": {
                        "present": price_source.has_row_availability,
                        "row_count": len(price_source.row_available_at),
                        "invalid_row_count": len(price_source.invalid_availability_keys),
                        "anchor_cutoff": "08:30 Asia/Taipei on decision_date",
                        "outcome_without_row_timestamp": (
                            "matured_read_time_file_mtime_only"
                        ),
                    },
                    "corporate_actions": corporate_source.to_dict(),
                    "corporate_actions_source_available": corporate_available,
                    "official_calendar": {
                        "window_start": calendar_start.isoformat(),
                        "window_end": calendar_end.isoformat(),
                        "rows_sha256": calendar_reader.source_hash,
                        "read_only": True,
                        "online_probe_allowed": False,
                    },
                },
                "warnings": sorted(
                    {
                        limit
                        for row in rows
                        for limit in row.limitation_codes
                        if limit
                    }
                ),
            }
        )
        if no_transition_rows:
            payload["warnings"] = sorted(
                set(payload.get("warnings", [])) | {"no_exit_transition_rows"}
            )
    except (ExitEffectivenessProducerError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        payload["status"] = "blocked"
        payload["blockers"] = [f"{type(exc).__name__}:{exc}"]
    body_for_hash = dict(payload)
    body_for_hash.pop("evidence_hash", None)
    payload["evidence_hash"] = _sha256_json(body_for_hash)
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    artifact, write_status = _create_only(Path(output), encoded)
    payload["artifact_path"] = str(artifact)
    payload["artifact_write_status"] = write_status
    payload["artifact_file_sha256"] = _sha256(encoded)
    return payload


class ExitEffectivenessProducer:
    """Small class facade for scheduled callers that prefer dependency injection."""

    def run(self, **kwargs: Any) -> dict[str, Any]:
        return produce_exit_effectiveness(**kwargs)


__all__ = [
    "DEFAULT_EXIT_HORIZON_TRADING_DAYS",
    "ExitEffectivenessProducer",
    "ExitEffectivenessProducerError",
    "POLICY_HASH",
    "POLICY_ID",
    "SCHEMA_VERSION",
    "produce_exit_effectiveness",
]
