"""Resolve stable Paper position identities from governed entry evidence.

Paper snapshots intentionally keep only the instrument and quantity.  This
adapter bridges that storage shape to the position-health contract without
guessing an identity from a stock code.  A new identity is created in memory
from a verified filled buy event that moves a position from flat to positive;
the resulting value is deterministic because it is derived from the immutable
ledger event.  Existing rows without that evidence remain unknown.

The adapter is read-only.  It verifies the Paper snapshot, the Paper ledger,
and the preopen receipt in short ``mode=ro``/``query_only`` transactions.  It
does not modify the Paper producer, the Formal store, or the configured D data
root.

The v1 ledger stores only ``event_date`` for ordering.  When more than one
material fill for one stock lands on the same date, the provider blocks that
source because ``fill_id`` is not an event sequence; it never invents a buy /
sell order from lexical identifiers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from app_module.paper_trade_ledger import PaperTradeFill
from app_module.sqlite_read_only import ReadOnlySQLiteManager


SCHEMA_VERSION = "paper-position-identity-source.v1"
TAIPEI = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
PAPER_SOURCE_TYPES = frozenset(
    {
        "paper_daily_execution_delayed_eod_replay_v1",
        "paper_daily_execution_v1",
    }
)
_REQUIRED_STATE_COLUMNS = {
    "snapshot_id",
    "portfolio_id",
    "decision_date",
    "source_result_id",
    "cash",
    "total_value",
}
_REQUIRED_POSITION_COLUMNS = {
    "snapshot_id",
    "stock_code",
    "quantity",
    "mark_price",
    "market_value",
    "weight_bp",
}
_REQUIRED_LEDGER_COLUMNS = {
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
}
_VALID_EVENT_STATUSES = frozenset(
    {"filled", "partially_filled", "rejected", "cancelled"}
)
_TRUSTED_LINEAGE_STATUSES = frozenset(
    {"same_snapshot_verified", "ledger_continuous_no_trade", "natural_entry_verified", "carried_verified"}
)


@dataclass(frozen=True)
class PositionIdentitySourceResult:
    """Identity map plus custody diagnostics for one Paper snapshot."""

    identities: Mapping[str, Mapping[str, Any]]
    provenance: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PaperSnapshot:
    snapshot_id: str
    portfolio_id: str
    decision_date: date
    source_result_id: str
    cash: str
    total_value: str
    positions: Mapping[str, int]
    rows_sha256: str


@dataclass(frozen=True)
class _LedgerEvent:
    fill: PaperTradeFill
    canonical_row: Mapping[str, Any]


class PaperPositionIdentityProvider:
    """Derive stable IDs only when Paper entry evidence proves a new entry."""

    def __init__(
        self,
        *,
        state_db_path: str | Path,
        ledger_db_path: str | Path,
        coverage_status_path: str | Path,
        portfolio_id: str = "paper-main",
    ) -> None:
        if not portfolio_id.strip():
            raise ValueError("portfolio_id is required")
        self.state_db_path = Path(state_db_path).expanduser().resolve()
        self.ledger_db_path = Path(ledger_db_path).expanduser().resolve()
        self.coverage_status_path = Path(coverage_status_path).expanduser().resolve()
        self.portfolio_id = portfolio_id.strip()

    def resolve(
        self,
        *,
        snapshot_id: str,
        snapshot_date: str | date,
        observed_at: datetime,
        previous_baseline: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> PositionIdentitySourceResult:
        """Resolve IDs for the requested snapshot using only prior events.

        ``snapshot_date`` is the preopen decision date.  Ledger events on that
        same date are deliberately excluded because they occur after the
        preopen boundary and belong to the next snapshot.
        """

        snapshot_key = _required_text(snapshot_id, "snapshot_id")
        target_date = _parse_date(snapshot_date, "snapshot_date")
        observed = _aware(observed_at, "observed_at")
        warnings: list[str] = []
        blockers: list[str] = []
        provenance: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "provider": type(self).__name__,
            "portfolio_id": self.portfolio_id,
            "requested_snapshot_id": snapshot_key,
            "requested_snapshot_date": target_date.isoformat(),
            "observed_at": observed.isoformat(),
            "policy": "derive_only_flat_to_positive_verified_filled_buy",
            "same_day_events_excluded": True,
        }

        try:
            coverage, coverage_hash, coverage_warnings = self._read_coverage(
                snapshot_id=snapshot_key,
                snapshot_date=target_date,
                observed_at=observed,
            )
            warnings.extend(coverage_warnings)
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return PositionIdentitySourceResult(
                identities={},
                provenance={**provenance, "status": "blocked", "coverage_status": "unavailable"},
                blockers=(f"paper_position_identity_coverage_blocked:{type(exc).__name__}:{exc}",),
            )

        try:
            snapshots, state_provenance = self._read_snapshots(
                snapshot_id=snapshot_key,
                snapshot_date=target_date,
            )
        except (FileNotFoundError, OSError, sqlite3.Error, ValueError) as exc:
            return PositionIdentitySourceResult(
                identities={},
                provenance={**provenance, "status": "blocked", "coverage": coverage},
                blockers=(f"paper_position_identity_state_blocked:{type(exc).__name__}:{exc}",),
            )
        current = snapshots[-1]
        previous_snapshot = snapshots[-2] if len(snapshots) >= 2 else None
        provenance["state"] = state_provenance
        provenance["snapshot_id"] = current.snapshot_id
        provenance["snapshot_date"] = current.decision_date.isoformat()
        if current.snapshot_id != snapshot_key or current.decision_date != target_date:
            return PositionIdentitySourceResult(
                identities={},
                provenance={**provenance, "status": "blocked", "coverage": coverage},
                blockers=("paper_position_identity_snapshot_boundary_mismatch",),
            )

        if previous_snapshot is None:
            warnings.append("paper_position_identity_previous_snapshot_missing")

        events, ledger_provenance, ledger_warnings, ledger_blockers = self._read_events(
            start_date=(
                previous_snapshot.decision_date
                if previous_snapshot is not None
                else current.decision_date
            ),
            end_date=current.decision_date,
        )
        warnings.extend(ledger_warnings)
        blockers.extend(ledger_blockers)
        provenance["ledger"] = ledger_provenance
        provenance["coverage"] = coverage
        provenance["coverage_status_file_sha256"] = coverage_hash
        if blockers:
            return PositionIdentitySourceResult(
                identities={},
                provenance={**provenance, "status": "blocked"},
                warnings=tuple(dict.fromkeys(warnings)),
                blockers=tuple(dict.fromkeys(blockers)),
            )

        previous_records = previous_baseline or {}
        identities: dict[str, Mapping[str, Any]] = {}
        events_by_code: dict[str, list[_LedgerEvent]] = {}
        for event in events:
            events_by_code.setdefault(event.fill.stock_code, []).append(event)

        unknown_codes: list[str] = []
        current_codes = tuple(sorted(code for code, quantity in current.positions.items() if quantity > 0))
        for code in current_codes:
            start_quantity = 0 if previous_snapshot is None else previous_snapshot.positions.get(code, 0)
            quantity = start_quantity
            entry_event: _LedgerEvent | None = None
            code_events = events_by_code.get(code, [])
            for event in code_events:
                fill = event.fill
                if fill.filled_quantity == 0:
                    continue
                if fill.side == "buy":
                    if quantity == 0 and entry_event is None:
                        entry_event = event
                    quantity += fill.filled_quantity
                elif fill.side == "sell":
                    if fill.filled_quantity > quantity:
                        blockers.append(f"paper_position_identity_sell_exceeds_holding:{code}:{fill.fill_id}")
                        continue
                    quantity -= fill.filled_quantity
                    if quantity == 0:
                        # A later buy is a new entry lineage.  Keeping the
                        # earlier event would incorrectly carry identity
                        # across a flat interval.
                        entry_event = None
                else:  # pragma: no cover - PaperTradeFill validates this
                    blockers.append(f"paper_position_identity_side_invalid:{fill.fill_id}")
            if quantity != current.positions.get(code, 0):
                blockers.append(
                    f"paper_position_identity_quantity_mismatch:{code}:{quantity}:{current.positions.get(code, 0)}"
                )
                continue

            if entry_event is not None:
                identities[code] = self._derived_identity(
                    code=code,
                    event=entry_event,
                    snapshot=current,
                    coverage=coverage,
                    ledger_rows_sha256=str(ledger_provenance.get("rows_sha256") or ""),
                )
                continue

            carried = _verified_prior_identity(previous_records.get(code), stock_code=code)
            if carried is not None and start_quantity > 0 and current.positions.get(code, 0) > 0:
                identities[code] = {
                    **carried,
                    "status": "carried_verified",
                    "identity_source": "previous_health_baseline_with_no_flat_transition",
                    "current_snapshot_id": current.snapshot_id,
                    "current_snapshot_date": current.decision_date.isoformat(),
                    "source_ledger_rows_sha256": ledger_provenance.get("rows_sha256"),
                }
                continue

            unknown_codes.append(code)
            warnings.append(f"paper_position_identity_unproven:{code}")

        if blockers:
            return PositionIdentitySourceResult(
                identities={},
                provenance={
                    **provenance,
                    "status": "blocked",
                    "unknown_codes": sorted(unknown_codes),
                },
                warnings=tuple(dict.fromkeys(warnings)),
                blockers=tuple(dict.fromkeys(blockers)),
            )

        provenance.update(
            {
                "status": "verified" if not unknown_codes else "degraded",
                "resolved_codes": sorted(identities),
                "unknown_codes": sorted(unknown_codes),
                "identity_count": len(identities),
            }
        )
        return PositionIdentitySourceResult(
            identities=identities,
            provenance=provenance,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _read_coverage(
        self,
        *,
        snapshot_id: str,
        snapshot_date: date,
        observed_at: datetime,
    ) -> tuple[dict[str, Any], str, list[str]]:
        raw = self.coverage_status_path.read_bytes()
        digest = _sha256(raw)
        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, Mapping):
            raise ValueError("paper_position_identity_coverage_must_be_object")
        if payload.get("schema_version") != "paper-portfolio-daily-status.v1":
            raise ValueError("paper_position_identity_coverage_schema_invalid")
        if payload.get("status") != "passed":
            raise ValueError("paper_position_identity_coverage_not_passed")
        if payload.get("producer") != "scripts.scheduled.run_paper_portfolio_daily_isolated":
            raise ValueError("paper_position_identity_coverage_producer_invalid")
        if payload.get("portfolio_id") != self.portfolio_id:
            raise ValueError("paper_position_identity_coverage_portfolio_invalid")
        if payload.get("snapshot_id") != snapshot_id:
            raise ValueError("paper_position_identity_coverage_snapshot_mismatch")
        receipt_date = _parse_date(payload.get("decision_date"), "coverage decision_date")
        if receipt_date != snapshot_date:
            raise ValueError("paper_position_identity_coverage_date_mismatch")
        if payload.get("snapshot_appended") is not True:
            raise ValueError("paper_position_identity_coverage_snapshot_not_appended")
        state_path = _resolved_text(payload.get("state_db"))
        ledger_path = _resolved_text(payload.get("paper_ledger_db"))
        if state_path != self.state_db_path:
            raise ValueError("paper_position_identity_coverage_state_path_mismatch")
        if ledger_path != self.ledger_db_path:
            raise ValueError("paper_position_identity_coverage_ledger_path_mismatch")
        if payload.get("trading_calendar_validated") is not True:
            raise ValueError("paper_position_identity_coverage_calendar_not_validated")
        for field in ("writes_market_db", "auto_rebalance_allowed", "changes_advice", "broker_execution"):
            if payload.get(field) is not False:
                raise ValueError(f"paper_position_identity_coverage_boundary_violation:{field}")
        decision_at = _aware(payload.get("decision_at"), "coverage decision_at")
        if decision_at > observed_at:
            raise ValueError("paper_position_identity_coverage_decision_at_future")
        if decision_at.astimezone(TAIPEI).date() != snapshot_date:
            raise ValueError("paper_position_identity_coverage_decision_at_date_mismatch")
        transition_count = _non_negative_int(
            payload.get("paper_ledger_transitions_applied"),
            "paper_ledger_transitions_applied",
        )
        after = _sha256(self.coverage_status_path.read_bytes())
        if after != digest:
            raise ValueError("paper_position_identity_coverage_changed_during_read")
        return (
            {
                "status": "ready",
                "path": str(self.coverage_status_path),
                "file_sha256": digest,
                "snapshot_id": snapshot_id,
                "snapshot_date": snapshot_date.isoformat(),
                "decision_at": decision_at.isoformat(),
                "ledger_transitions_applied": transition_count,
            },
            digest,
            [],
        )

    def _read_snapshots(
        self,
        *,
        snapshot_id: str,
        snapshot_date: date,
    ) -> tuple[tuple[_PaperSnapshot, ...], dict[str, Any]]:
        before = _sha256_file(self.state_db_path)
        manager = ReadOnlySQLiteManager(self.state_db_path)
        with manager.connect() as connection:
            connection.execute("BEGIN")
            snapshot_columns = _table_columns(connection, "paper_portfolio_snapshots")
            position_columns = _table_columns(connection, "paper_portfolio_positions")
            if not _REQUIRED_STATE_COLUMNS.issubset(snapshot_columns):
                raise ValueError("paper_position_identity_snapshot_schema_missing")
            if not _REQUIRED_POSITION_COLUMNS.issubset(position_columns):
                raise ValueError("paper_position_identity_position_schema_missing")
            rows = connection.execute(
                """
                SELECT snapshot_id, portfolio_id, decision_date, source_result_id,
                       cash, total_value
                FROM paper_portfolio_snapshots
                WHERE portfolio_id = ? AND decision_date <= ?
                ORDER BY decision_date, snapshot_id
                """,
                (self.portfolio_id, snapshot_date.isoformat()),
            ).fetchall()
            if not rows:
                raise ValueError("paper_position_identity_snapshot_missing")
            ids = [str(row["snapshot_id"] or "").strip() for row in rows]
            if snapshot_id not in ids:
                raise ValueError("paper_position_identity_requested_snapshot_missing")
            all_positions = connection.execute(
                """
                SELECT snapshot_id, stock_code, quantity, mark_price, market_value, weight_bp
                FROM paper_portfolio_positions
                WHERE snapshot_id IN ({})
                ORDER BY snapshot_id, stock_code
                """.format(",".join("?" for _ in ids)),
                tuple(ids),
            ).fetchall()
            positions_by_snapshot: dict[str, dict[str, int]] = {item: {} for item in ids}
            canonical_positions: dict[str, list[dict[str, Any]]] = {item: [] for item in ids}
            for position in all_positions:
                current_id = str(position["snapshot_id"] or "").strip()
                code = _required_text(position["stock_code"], "paper position stock_code")
                quantity = _non_negative_int(position["quantity"], "paper position quantity")
                if current_id not in positions_by_snapshot:
                    raise ValueError("paper_position_identity_position_snapshot_unknown")
                positions_by_snapshot[current_id][code] = quantity
                canonical_positions[current_id].append(
                    {
                        "stock_code": code,
                        "quantity": quantity,
                        "mark_price": str(position["mark_price"]),
                        "market_value": str(position["market_value"]),
                        "weight_bp": _non_negative_int(position["weight_bp"], "paper position weight_bp"),
                    }
                )
            snapshots: list[_PaperSnapshot] = []
            canonical_snapshots: list[dict[str, Any]] = []
            for row in rows:
                current_id = _required_text(row["snapshot_id"], "snapshot_id")
                current_date = _parse_date(row["decision_date"], "paper snapshot decision_date")
                if current_date > snapshot_date:
                    raise ValueError("paper_position_identity_snapshot_future")
                item: dict[str, Any] = {
                    "snapshot_id": current_id,
                    "portfolio_id": _required_text(row["portfolio_id"], "portfolio_id"),
                    "decision_date": current_date.isoformat(),
                    "source_result_id": _required_text(row["source_result_id"], "source_result_id"),
                    "cash": str(row["cash"]),
                    "total_value": str(row["total_value"]),
                    "positions": canonical_positions[current_id],
                }
                canonical_snapshots.append(item)
                snapshots.append(
                    _PaperSnapshot(
                        snapshot_id=current_id,
                        portfolio_id=item["portfolio_id"],
                        decision_date=current_date,
                        source_result_id=item["source_result_id"],
                        cash=item["cash"],
                        total_value=item["total_value"],
                        positions=dict(positions_by_snapshot[current_id]),
                        rows_sha256=_sha256_json(item),
                    )
                )
        after = _sha256_file(self.state_db_path)
        if before != after:
            raise ValueError("paper_position_identity_state_changed_during_read")
        if len(snapshots) < 1 or snapshots[-1].snapshot_id != snapshot_id:
            raise ValueError("paper_position_identity_snapshot_not_latest")
        return tuple(snapshots), {
            "status": "verified",
            "path": str(self.state_db_path),
            "file_sha256": before,
            "snapshot_count": len(snapshots),
            "snapshots_sha256": _sha256_json(canonical_snapshots),
            "selected_snapshot_rows_sha256": snapshots[-1].rows_sha256,
        }

    def _read_events(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> tuple[list[_LedgerEvent], dict[str, Any], list[str], list[str]]:
        warnings: list[str] = []
        blockers: list[str] = []
        if not self.ledger_db_path.is_file():
            return [], {
                "status": "missing",
                "path": str(self.ledger_db_path),
                "rows_sha256": None,
                "row_count": 0,
            }, ["paper_position_identity_ledger_missing"], []

        before = _sha256_file(self.ledger_db_path)
        manager = ReadOnlySQLiteManager(self.ledger_db_path)
        canonical_rows: list[dict[str, Any]] = []
        events: list[_LedgerEvent] = []
        try:
            with manager.connect() as connection:
                connection.execute("BEGIN")
                columns = _table_columns(connection, "paper_trade_ledger")
                if not _REQUIRED_LEDGER_COLUMNS.issubset(columns):
                    raise ValueError("paper_position_identity_ledger_schema_missing")
                rows = connection.execute(
                    """
                    SELECT schema_version, fill_id, order_id, portfolio_id, event_date,
                           stock_code, side, requested_quantity, filled_quantity,
                           reference_price, fill_price, commission, tax, slippage_cost,
                           turnover_bp, execution_gap_bp, status, source_event_id,
                           override_reason, source_type, research_only,
                           broker_order_allowed, auto_rebalance_allowed
                    FROM paper_trade_ledger
                    WHERE portfolio_id = ? AND event_date >= ? AND event_date < ?
                    ORDER BY event_date, stock_code, fill_id
                    """,
                    (self.portfolio_id, start_date.isoformat(), end_date.isoformat()),
                ).fetchall()
                for row in rows:
                    canonical = {
                        column: row[column]
                        for column in (
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
                    }
                    canonical_rows.append(canonical)
                    fill = _row_to_fill(row)
                    if fill.source_type not in PAPER_SOURCE_TYPES:
                        blockers.append(
                            f"paper_position_identity_source_type_invalid:{fill.fill_id}:{fill.source_type}"
                        )
                    if fill.portfolio_id != self.portfolio_id:
                        blockers.append(f"paper_position_identity_portfolio_invalid:{fill.fill_id}")
                    events.append(_LedgerEvent(fill=fill, canonical_row=canonical))
                # The v1 Paper ledger has only a natural date and no event
                # sequence/time.  A same-day group with multiple material
                # fills cannot safely establish which buy opened the lineage
                # (or whether a sell happened before a re-entry).  Reject the
                # source rather than using fill_id as an invented order.
                material_by_day: dict[tuple[str, str], list[_LedgerEvent]] = {}
                for event in events:
                    if event.fill.filled_quantity <= 0:
                        continue
                    key = (event.fill.stock_code, event.fill.event_date)
                    material_by_day.setdefault(key, []).append(event)
                for (stock_code, event_date), same_day in material_by_day.items():
                    if len(same_day) > 1:
                        blockers.append(
                            "paper_position_identity_event_order_ambiguous:"
                            f"{stock_code}:{event_date}:"
                            + ",".join(sorted(event.fill.fill_id for event in same_day))
                        )
        except (FileNotFoundError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
            return [], {
                "status": "blocked",
                "path": str(self.ledger_db_path),
                "file_sha256": _safe_hash_file(self.ledger_db_path),
            }, warnings, [f"paper_position_identity_ledger_blocked:{type(exc).__name__}:{exc}"]
        after = _sha256_file(self.ledger_db_path)
        if before != after:
            blockers.append("paper_position_identity_ledger_changed_during_read")
        return events, {
            "status": "verified" if not blockers else "blocked",
            "path": str(self.ledger_db_path),
            "file_sha256": before,
            "rows_sha256": _sha256_json(canonical_rows),
            "row_count": len(canonical_rows),
            "window_start_inclusive": start_date.isoformat(),
            "window_end_exclusive": end_date.isoformat(),
        }, warnings, blockers

    @staticmethod
    def _derived_identity(
        *,
        code: str,
        event: _LedgerEvent,
        snapshot: _PaperSnapshot,
        coverage: Mapping[str, Any],
        ledger_rows_sha256: str,
    ) -> dict[str, Any]:
        entry_hash = _sha256_json(event.canonical_row)
        suffix = entry_hash.split(":", 1)[-1][:24]
        position_id = f"paper:{snapshot.portfolio_id}:{code}:entry-{suffix}"
        return {
            "position_id": position_id,
            "entry_lineage_id": position_id,
            "stock_code": code,
            "status": "natural_entry_verified",
            "entry_date": event.fill.event_date,
            "entry_fill_id": event.fill.fill_id,
            "entry_source_event_id": event.fill.source_event_id,
            "entry_evidence_hash": entry_hash,
            "source_ledger_rows_sha256": ledger_rows_sha256,
            "coverage_status_file_sha256": coverage.get("file_sha256"),
            "available_at": coverage.get("decision_at"),
            "current_snapshot_id": snapshot.snapshot_id,
            "current_snapshot_date": snapshot.decision_date.isoformat(),
            "identity_source": "paper_trade_ledger_verified_flat_to_positive_buy",
        }


def _row_to_fill(row: sqlite3.Row) -> PaperTradeFill:
    return PaperTradeFill(
        fill_id=_required_text(row["fill_id"], "fill_id"),
        order_id=_required_text(row["order_id"], "order_id"),
        portfolio_id=_required_text(row["portfolio_id"], "portfolio_id"),
        event_date=_parse_date(row["event_date"], "event_date").isoformat(),
        stock_code=_required_text(row["stock_code"], "stock_code"),
        side=_required_text(row["side"], "side"),
        requested_quantity=_non_negative_int(row["requested_quantity"], "requested_quantity"),
        filled_quantity=_non_negative_int(row["filled_quantity"], "filled_quantity"),
        reference_price=_decimal(row["reference_price"], "reference_price"),
        fill_price=(None if row["fill_price"] is None else _decimal(row["fill_price"], "fill_price")),
        commission=_decimal(row["commission"], "commission"),
        tax=_decimal(row["tax"], "tax"),
        slippage_cost=_decimal(row["slippage_cost"], "slippage_cost"),
        turnover_bp=(None if row["turnover_bp"] is None else int(row["turnover_bp"])),
        execution_gap_bp=(None if row["execution_gap_bp"] is None else int(row["execution_gap_bp"])),
        status=_required_text(row["status"], "status"),
        source_event_id=_required_text(row["source_event_id"], "source_event_id"),
        override_reason=(None if row["override_reason"] is None else str(row["override_reason"])),
        source_type=_required_text(row["source_type"], "source_type"),
        research_only=bool(row["research_only"]),
        broker_order_allowed=bool(row["broker_order_allowed"]),
        auto_rebalance_allowed=bool(row["auto_rebalance_allowed"]),
    )


def _verified_prior_identity(
    value: Mapping[str, Any] | None,
    *,
    stock_code: str,
) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    position_id = str(value.get("position_id") or "").strip()
    lineage_id = str(value.get("entry_lineage_id") or "").strip()
    status = str(value.get("entry_lineage_status") or "").strip()
    if not position_id or not lineage_id or status not in _TRUSTED_LINEAGE_STATUSES:
        return None
    if str(value.get("stock_code") or stock_code).strip() != stock_code:
        return None
    if str(value.get("state") or "").strip().upper() == "CLOSED":
        return None
    return {
        "position_id": position_id,
        "entry_lineage_id": lineage_id,
        "stock_code": stock_code,
        "entry_date": value.get("entry_date"),
        "entry_fill_id": value.get("entry_fill_id"),
        "entry_source_event_id": value.get("entry_source_event_id"),
        "entry_evidence_hash": value.get("entry_evidence_hash"),
    }


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table_name}")')}


def _parse_date(value: object, field_name: str) -> date:
    text = str(value or "").strip()
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{field_name}_invalid") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{field_name}_must_be_iso_date")
    return parsed


def _aware(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name}_must_be_timezone_aware")
    return parsed.astimezone(UTC)


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{field_name}_must_be_decimal_text")
    try:
        parsed = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - source boundary
        raise ValueError(f"{field_name}_invalid_decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name}_non_finite")
    return parsed


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name}_must_be_non_negative_integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field_name}_must_be_non_negative_integer")
    if parsed < 0:
        raise ValueError(f"{field_name}_must_be_non_negative_integer")
    return parsed


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name}_missing")
    return text


def _resolved_text(value: object) -> Path:
    return Path(_required_text(value, "path")).expanduser().resolve()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256(_canonical(value).encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _safe_hash_file(path: Path) -> str | None:
    try:
        return _sha256_file(path)
    except OSError:
        return None
