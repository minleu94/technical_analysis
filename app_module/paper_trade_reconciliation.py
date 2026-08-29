"""Query-only reconciliation for externally supplied Paper trade fills.

The Paper Trade CSV importer validates execution fields and has an explicit
append command.  This module adds the missing preflight between those two
steps: it compares the filled share deltas in a supplied CSV with the exact
start/end Paper Portfolio snapshots.  It never infers a fill from snapshots,
market prices, or a missing ledger, and it never creates or mutates a SQLite
database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Any

from app_module.paper_portfolio_time import paper_portfolio_today
from app_module.paper_trade_import_service import (
    PAPER_TRADE_IMPORT_SCHEMA_VERSION,
    PaperTradeImportPreview,
    PaperTradeImportService,
)
from app_module.paper_trade_ledger import PaperTradeFill
from app_module.sqlite_read_only import ReadOnlySQLiteManager


PAPER_TRADE_RECONCILIATION_SCHEMA_VERSION = "paper-trade-reconciliation.v1"
_VALID_STATUSES = frozenset({"ready", "needs_review", "rejected", "not_configured"})


@dataclass(frozen=True)
class PaperTradeQuantityReconciliation:
    """One symbol's observed fill delta versus snapshot delta."""

    stock_code: str
    start_quantity: int
    end_quantity: int
    buy_filled_quantity: int
    sell_filled_quantity: int
    expected_delta: int
    observed_delta: int
    status: str

    def __post_init__(self) -> None:
        if not self.stock_code.strip():
            raise ValueError("stock_code is required")
        for field_name in (
            "start_quantity",
            "end_quantity",
            "buy_filled_quantity",
            "sell_filled_quantity",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in ("expected_delta", "observed_delta"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
        if self.status not in {"matched", "mismatch"}:
            raise ValueError("status must be matched or mismatch")
        if self.status == "matched" and self.expected_delta != self.observed_delta:
            raise ValueError("matched quantity reconciliation must have equal deltas")
        if self.status == "mismatch" and self.expected_delta == self.observed_delta:
            raise ValueError("mismatch quantity reconciliation must have different deltas")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "start_quantity": self.start_quantity,
            "end_quantity": self.end_quantity,
            "buy_filled_quantity": self.buy_filled_quantity,
            "sell_filled_quantity": self.sell_filled_quantity,
            "expected_delta": self.expected_delta,
            "observed_delta": self.observed_delta,
            "status": self.status,
        }


@dataclass(frozen=True)
class PaperTradeReconciliationResult:
    """Candidate-only result of Paper fills preflight."""

    generated_at: str
    status: str
    input_path: str
    source_hash: str | None
    encoding: str | None
    portfolio_id: str
    period_start: str | None
    period_end: str | None
    state_db_path: str
    existing_ledger_db_path: str | None
    snapshot_start_id: str | None
    snapshot_end_id: str | None
    row_count: int
    valid_row_count: int
    invalid_row_count: int
    filled_event_count: int
    partial_fill_event_count: int
    rejected_event_count: int
    override_event_count: int
    total_cost: Decimal
    total_turnover_bp: int
    quantity_reconciliation: tuple[PaperTradeQuantityReconciliation, ...] = ()
    existing_fill_id_collisions: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    candidate_only: bool = True
    write_performed: bool = False
    ledger_append_allowed: bool = False
    research_only: bool = True
    broker_order_allowed: bool = False
    auto_rebalance_allowed: bool = False

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"unsupported reconciliation status: {self.status}")
        for field_name in (
            "row_count",
            "valid_row_count",
            "invalid_row_count",
            "filled_event_count",
            "partial_fill_event_count",
            "rejected_event_count",
            "override_event_count",
            "total_turnover_bp",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if (
            not isinstance(self.total_cost, Decimal)
            or not self.total_cost.is_finite()
            or self.total_cost < 0
        ):
            raise ValueError("total_cost must be a finite non-negative Decimal")
        if (
            self.candidate_only is not True
            or self.write_performed is not False
            or self.research_only is not True
            or self.broker_order_allowed is not False
            or self.auto_rebalance_allowed is not False
        ):
            raise ValueError("paper reconciliation safety boundary must remain fail-closed")
        if self.ledger_append_allowed and self.status != "ready":
            raise ValueError("ledger append is allowed only for a ready reconciliation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAPER_TRADE_RECONCILIATION_SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "status": self.status,
            "input_path": self.input_path,
            "source_hash": self.source_hash,
            "encoding": self.encoding,
            "portfolio_id": self.portfolio_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "state_db_path": self.state_db_path,
            "existing_ledger_db_path": self.existing_ledger_db_path,
            "snapshot_start_id": self.snapshot_start_id,
            "snapshot_end_id": self.snapshot_end_id,
            "row_count": self.row_count,
            "valid_row_count": self.valid_row_count,
            "invalid_row_count": self.invalid_row_count,
            "filled_event_count": self.filled_event_count,
            "partial_fill_event_count": self.partial_fill_event_count,
            "rejected_event_count": self.rejected_event_count,
            "override_event_count": self.override_event_count,
            "total_cost": str(self.total_cost.quantize(Decimal("0.01"))),
            "total_turnover_bp": self.total_turnover_bp,
            "quantity_reconciliation": [item.to_dict() for item in self.quantity_reconciliation],
            "existing_fill_id_collisions": list(self.existing_fill_id_collisions),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "candidate_only": self.candidate_only,
            "write_performed": self.write_performed,
            "ledger_append_allowed": self.ledger_append_allowed,
            "research_only": self.research_only,
            "broker_order_allowed": self.broker_order_allowed,
            "auto_rebalance_allowed": self.auto_rebalance_allowed,
            "input_schema_version": PAPER_TRADE_IMPORT_SCHEMA_VERSION,
        }


class PaperTradeReconciliationService:
    """Validate an external fills CSV against immutable snapshot boundaries."""

    def __init__(
        self,
        *,
        state_db_path: str | Path,
        portfolio_id: str = "paper-main",
        existing_ledger_db_path: str | Path | None = None,
    ) -> None:
        self.state_db_path = Path(state_db_path).expanduser().resolve()
        self.portfolio_id = portfolio_id.strip()
        if not self.portfolio_id:
            raise ValueError("portfolio_id is required")
        self.existing_ledger_db_path = (
            None
            if existing_ledger_db_path is None
            else Path(existing_ledger_db_path).expanduser().resolve()
        )

    def inspect(
        self,
        source_path: str | Path,
        *,
        period_start: str | None = None,
        period_end: str | None = None,
    ) -> PaperTradeReconciliationResult:
        input_path = Path(source_path).expanduser().resolve()
        try:
            preview = PaperTradeImportService().preview_csv(input_path)
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            return self._empty_result(
                input_path=input_path,
                status="rejected",
                blockers=("paper_trade_input_invalid",),
                diagnostics=(f"paper_trade_input_error:{type(exc).__name__}:{exc}",),
            )

        blockers: list[str] = []
        warnings = list(preview.warnings)
        diagnostics: list[str] = []
        fills: tuple[PaperTradeFill, ...] = ()
        if not preview.rows:
            blockers.append("paper_trade_input_empty")
        elif not preview.ready_to_import:
            blockers.append("paper_trade_input_invalid_rows")
        else:
            try:
                fills = PaperTradeImportService().build_fills(preview)
            except (TypeError, ValueError, ArithmeticError) as exc:
                blockers.append("paper_trade_input_invalid_rows")
                diagnostics.append(f"paper_trade_fill_build_error:{type(exc).__name__}:{exc}")

        valid_dates = [item.event_date[:10] for item in fills]
        parsed_period = _resolve_period(period_start, period_end, valid_dates, blockers, warnings)
        resolved_start, resolved_end = parsed_period
        today = paper_portfolio_today()
        if resolved_start is not None and date.fromisoformat(resolved_start) > today:
            blockers.append("paper_trade_period_future")
            diagnostics.append(
                f"paper_trade_period_future:{resolved_start}:today={today.isoformat()}"
            )
        if resolved_end is not None and date.fromisoformat(resolved_end) > today:
            blockers.append("paper_trade_period_future")
            diagnostics.append(
                f"paper_trade_period_future:{resolved_end}:today={today.isoformat()}"
            )

        for fill in fills:
            if fill.portfolio_id != self.portfolio_id:
                blockers.append("paper_trade_portfolio_id_mismatch")
                diagnostics.append(
                    f"paper_trade_portfolio_id:{fill.fill_id}:{fill.portfolio_id}"
                )
            event_date = date.fromisoformat(fill.event_date[:10])
            if event_date > today:
                blockers.append("paper_trade_event_future")
                diagnostics.append(
                    f"paper_trade_event_future:{fill.fill_id}:{event_date.isoformat()}:today={today.isoformat()}"
                )
            if resolved_start is not None and fill.event_date[:10] < resolved_start:
                blockers.append("paper_trade_event_outside_period")
            if resolved_end is not None and fill.event_date[:10] > resolved_end:
                blockers.append("paper_trade_event_outside_period")

        snapshot_start_id: str | None = None
        snapshot_end_id: str | None = None
        quantity_reconciliation: tuple[PaperTradeQuantityReconciliation, ...] = ()
        if resolved_start is not None and resolved_end is not None and not _has_input_error(blockers):
            (
                snapshot_start_id,
                snapshot_end_id,
                start_quantities,
                end_quantities,
                snapshot_blockers,
                snapshot_diagnostics,
            ) = self._read_snapshot_boundaries(resolved_start, resolved_end)
            blockers.extend(snapshot_blockers)
            diagnostics.extend(snapshot_diagnostics)
            if not snapshot_blockers:
                quantity_reconciliation = _reconcile_quantities(
                    start_quantities=start_quantities,
                    end_quantities=end_quantities,
                    fills=fills,
                )
                if any(item.status == "mismatch" for item in quantity_reconciliation):
                    blockers.append("paper_trade_quantity_reconciliation_mismatch")

        existing_collisions = self._read_existing_fill_collisions(
            fills,
            blockers=blockers,
            diagnostics=diagnostics,
        )
        if existing_collisions:
            blockers.append("paper_trade_fill_id_collision")

        status = _status_for(
            blockers=blockers,
            preview=preview,
            fills=fills,
            state_db_exists=self.state_db_path.is_file(),
        )
        if status == "ready" and warnings:
            status = "needs_review"
            warnings.append("paper_trade_reconciliation_has_warnings")
        return PaperTradeReconciliationResult(
            generated_at=_utc_now_text(),
            status=status,
            input_path=str(input_path),
            source_hash=f"sha256:{preview.source_hash}",
            encoding=preview.encoding,
            portfolio_id=self.portfolio_id,
            period_start=resolved_start,
            period_end=resolved_end,
            state_db_path=str(self.state_db_path),
            existing_ledger_db_path=(
                str(self.existing_ledger_db_path)
                if self.existing_ledger_db_path is not None
                else None
            ),
            snapshot_start_id=snapshot_start_id,
            snapshot_end_id=snapshot_end_id,
            row_count=len(preview.rows),
            valid_row_count=len(preview.valid_rows),
            invalid_row_count=len(preview.invalid_rows),
            filled_event_count=sum(1 for item in fills if item.status == "filled"),
            partial_fill_event_count=sum(
                1 for item in fills if item.status == "partially_filled"
            ),
            rejected_event_count=sum(
                1 for item in fills if item.status in {"rejected", "cancelled"}
            ),
            override_event_count=sum(1 for item in fills if item.override_reason),
            total_cost=sum((item.total_cost for item in fills), Decimal("0")),
            total_turnover_bp=sum(item.turnover_bp or 0 for item in fills),
            quantity_reconciliation=quantity_reconciliation,
            existing_fill_id_collisions=existing_collisions,
            blockers=tuple(sorted(set(blockers))),
            warnings=tuple(dict.fromkeys(warnings)),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            ledger_append_allowed=status == "ready",
        )

    def _read_snapshot_boundaries(
        self,
        period_start: str,
        period_end: str,
    ) -> tuple[
        str | None,
        str | None,
        dict[str, int],
        dict[str, int],
        list[str],
        list[str],
    ]:
        blockers: list[str] = []
        diagnostics: list[str] = []
        if not self.state_db_path.is_file():
            blockers.append("paper_snapshot_db_missing")
            return None, None, {}, {}, blockers, diagnostics
        manager = ReadOnlySQLiteManager(self.state_db_path)
        try:
            with manager.connect() as connection:
                if not _table_exists(connection, "paper_portfolio_snapshots"):
                    blockers.append("paper_snapshot_table_missing")
                    return None, None, {}, {}, blockers, diagnostics
                if not _table_exists(connection, "paper_portfolio_positions"):
                    blockers.append("paper_snapshot_positions_table_missing")
                    return None, None, {}, {}, blockers, diagnostics
                rows = connection.execute(
                    """
                    SELECT snapshot_id, decision_date
                    FROM paper_portfolio_snapshots
                    WHERE portfolio_id = ? AND decision_date IN (?, ?)
                    ORDER BY decision_date, snapshot_id
                    """,
                    (self.portfolio_id, period_start, period_end),
                ).fetchall()
                by_date: dict[str, list[sqlite3.Row]] = {period_start: [], period_end: []}
                for row in rows:
                    by_date.setdefault(str(row["decision_date"]), []).append(row)
                if len(by_date.get(period_start, [])) != 1:
                    blockers.append("paper_snapshot_start_boundary_missing_or_ambiguous")
                if len(by_date.get(period_end, [])) != 1:
                    blockers.append("paper_snapshot_end_boundary_missing_or_ambiguous")
                if blockers:
                    return None, None, {}, {}, blockers, diagnostics
                start_row = by_date[period_start][0]
                end_row = by_date[period_end][0]
                start_id = str(start_row["snapshot_id"])
                end_id = str(end_row["snapshot_id"])
                start_quantities = self._read_snapshot_quantities(connection, start_id, diagnostics)
                end_quantities = self._read_snapshot_quantities(connection, end_id, diagnostics)
                if any(item.startswith("paper_snapshot_position") for item in diagnostics):
                    blockers.append("paper_snapshot_position_invalid")
                return start_id, end_id, start_quantities, end_quantities, blockers, diagnostics
        except (FileNotFoundError, OSError, sqlite3.Error) as exc:
            blockers.append("paper_snapshot_db_unavailable")
            diagnostics.append(f"paper_snapshot_db_error:{type(exc).__name__}")
            return None, None, {}, {}, blockers, diagnostics

    @staticmethod
    def _read_snapshot_quantities(
        connection: sqlite3.Connection,
        snapshot_id: str,
        diagnostics: list[str],
    ) -> dict[str, int]:
        quantities: dict[str, int] = {}
        rows = connection.execute(
            """
            SELECT stock_code, quantity
            FROM paper_portfolio_positions
            WHERE snapshot_id = ?
            ORDER BY stock_code
            """,
            (snapshot_id,),
        ).fetchall()
        for row in rows:
            stock_code = str(row["stock_code"] or "").strip()
            try:
                quantity = _non_negative_int(row["quantity"], "quantity")
            except (TypeError, ValueError) as exc:
                diagnostics.append(
                    f"paper_snapshot_position_invalid:{snapshot_id}:{stock_code}:{type(exc).__name__}"
                )
                continue
            if not stock_code or stock_code in quantities:
                diagnostics.append(f"paper_snapshot_position_invalid:{snapshot_id}:{stock_code}")
                continue
            quantities[stock_code] = quantity
        return quantities

    def _read_existing_fill_collisions(
        self,
        fills: tuple[PaperTradeFill, ...],
        *,
        blockers: list[str],
        diagnostics: list[str],
    ) -> tuple[str, ...]:
        if self.existing_ledger_db_path is None or not self.existing_ledger_db_path.is_file():
            return ()
        manager = ReadOnlySQLiteManager(self.existing_ledger_db_path)
        try:
            with manager.connect() as connection:
                if not _table_exists(connection, "paper_trade_ledger"):
                    blockers.append("paper_trade_ledger_schema_mismatch")
                    diagnostics.append("paper_trade_ledger_table_missing")
                    return ()
                existing = {
                    str(row[0])
                    for row in connection.execute("SELECT fill_id FROM paper_trade_ledger").fetchall()
                }
        except (FileNotFoundError, OSError, sqlite3.Error) as exc:
            blockers.append("paper_trade_ledger_db_unavailable")
            diagnostics.append(f"paper_trade_ledger_db_error:{type(exc).__name__}")
            return ()
        return tuple(sorted(item.fill_id for item in fills if item.fill_id in existing))

    def _empty_result(
        self,
        *,
        input_path: Path,
        status: str,
        blockers: tuple[str, ...],
        diagnostics: tuple[str, ...],
    ) -> PaperTradeReconciliationResult:
        return PaperTradeReconciliationResult(
            generated_at=_utc_now_text(),
            status=status,
            input_path=str(input_path),
            source_hash=None,
            encoding=None,
            portfolio_id=self.portfolio_id,
            period_start=None,
            period_end=None,
            state_db_path=str(self.state_db_path),
            existing_ledger_db_path=(
                str(self.existing_ledger_db_path)
                if self.existing_ledger_db_path is not None
                else None
            ),
            snapshot_start_id=None,
            snapshot_end_id=None,
            row_count=0,
            valid_row_count=0,
            invalid_row_count=0,
            filled_event_count=0,
            partial_fill_event_count=0,
            rejected_event_count=0,
            override_event_count=0,
            total_cost=Decimal("0"),
            total_turnover_bp=0,
            blockers=blockers,
            diagnostics=diagnostics,
        )


def _resolve_period(
    period_start: str | None,
    period_end: str | None,
    valid_dates: list[str],
    blockers: list[str],
    warnings: list[str],
) -> tuple[str | None, str | None]:
    start = _parse_optional_date(period_start, "period_start", blockers)
    end = _parse_optional_date(period_end, "period_end", blockers)
    if start is None and valid_dates:
        start = min(valid_dates)
        warnings.append("period_start_derived_from_input")
    if end is None and valid_dates:
        end = max(valid_dates)
        warnings.append("period_end_derived_from_input")
    if start is not None and end is not None and start > end:
        blockers.append("paper_trade_period_invalid")
    elif start is not None and end is not None and start == end:
        blockers.append("paper_trade_period_requires_distinct_boundaries")
    if not valid_dates:
        blockers.append("paper_trade_period_unavailable")
    return start, end


def _parse_optional_date(value: str | None, field_name: str, blockers: list[str]) -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().replace("/", "-").replace(".", "-")
    if len(normalized) == 8 and normalized.isdigit():
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError:
        blockers.append(f"paper_trade_{field_name}_invalid")
        return None


def _reconcile_quantities(
    *,
    start_quantities: dict[str, int],
    end_quantities: dict[str, int],
    fills: tuple[PaperTradeFill, ...],
) -> tuple[PaperTradeQuantityReconciliation, ...]:
    changes: dict[str, dict[str, int]] = {}
    for fill in fills:
        entry = changes.setdefault(fill.stock_code, {"buy": 0, "sell": 0})
        entry[fill.side] += fill.filled_quantity
    symbols = sorted(set(start_quantities) | set(end_quantities) | set(changes))
    result: list[PaperTradeQuantityReconciliation] = []
    for stock_code in symbols:
        start_quantity = start_quantities.get(stock_code, 0)
        end_quantity = end_quantities.get(stock_code, 0)
        buy_quantity = changes.get(stock_code, {}).get("buy", 0)
        sell_quantity = changes.get(stock_code, {}).get("sell", 0)
        expected_delta = end_quantity - start_quantity
        observed_delta = buy_quantity - sell_quantity
        result.append(
            PaperTradeQuantityReconciliation(
                stock_code=stock_code,
                start_quantity=start_quantity,
                end_quantity=end_quantity,
                buy_filled_quantity=buy_quantity,
                sell_filled_quantity=sell_quantity,
                expected_delta=expected_delta,
                observed_delta=observed_delta,
                status="matched" if expected_delta == observed_delta else "mismatch",
            )
        )
    return tuple(result)


def _status_for(
    *,
    blockers: list[str],
    preview: PaperTradeImportPreview,
    fills: tuple[PaperTradeFill, ...],
    state_db_exists: bool,
) -> str:
    if not state_db_exists and "paper_snapshot_db_missing" in blockers:
        return "not_configured"
    if not preview.rows or not fills or preview.invalid_rows:
        return "rejected"
    if "paper_trade_quantity_reconciliation_mismatch" in blockers:
        return "needs_review"
    hard_tokens = (
        "invalid",
        "future",
        "collision",
        "schema_mismatch",
        "unavailable",
        "outside_period",
        "portfolio_id_mismatch",
    )
    if any(any(token in item for token in hard_tokens) for item in blockers):
        return "rejected"
    if blockers:
        return "needs_review"
    return "ready"


def _has_input_error(blockers: list[str]) -> bool:
    return any(
        item.startswith("paper_trade_input_")
        or item.startswith("paper_trade_period_")
        or item == "paper_trade_period_unavailable"
        for item in blockers
    )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field_name} must be a non-negative integer")
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return parsed


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def render_markdown(result: PaperTradeReconciliationResult) -> str:
    lines = [
        "# Paper Trade Reconciliation (Candidate)",
        "",
        f"- status: `{result.status}`",
        f"- input: `{result.input_path}`",
        f"- source hash: `{result.source_hash or 'unavailable'}`",
        f"- portfolio / period: `{result.portfolio_id}` / `{result.period_start or 'N/A'}` → `{result.period_end or 'N/A'}`",
        f"- rows valid / invalid: `{result.valid_row_count}` / `{result.invalid_row_count}`",
        f"- fills: filled=`{result.filled_event_count}`, partial=`{result.partial_fill_event_count}`, rejected/cancelled=`{result.rejected_event_count}`",
        f"- total cost / turnover (bp): `{result.total_cost.quantize(Decimal('0.01'))}` / `{result.total_turnover_bp}`",
        f"- snapshot boundaries: `{result.snapshot_start_id or 'missing'}` → `{result.snapshot_end_id or 'missing'}`",
        f"- ledger append allowed: `{str(result.ledger_append_allowed).lower()}`",
        "- candidate only: `true`",
        "- write performed: `false`",
        "",
        "## Quantity reconciliation",
        "",
        "| Stock | Start | End | Buy filled | Sell filled | Expected Δ | Observed Δ | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in result.quantity_reconciliation:
        lines.append(
            f"| `{item.stock_code}` | {item.start_quantity} | {item.end_quantity} | "
            f"{item.buy_filled_quantity} | {item.sell_filled_quantity} | {item.expected_delta} | "
            f"{item.observed_delta} | `{item.status}` |"
        )
    for title, values in (
        ("Blockers", result.blockers),
        ("Warnings", result.warnings),
        ("Diagnostics", result.diagnostics),
    ):
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {item}" for item in values or ("none",))
    lines.extend(
        [
            "",
            "## Safety boundary",
            "",
            "- 外部 CSV 是唯一成交來源；snapshot 只用於對帳，不會反推成交。",
            "- 此檢查不建立 ledger、不寫 Portfolio／Evidence／正式 SQLite，也不送 broker order。",
            "- `ready` 只代表候選 fills 通過輸入與 snapshot 邊界對帳；真正 append 仍需既有 CLI 的明確 confirm 與 source hash recheck。",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "PAPER_TRADE_RECONCILIATION_SCHEMA_VERSION",
    "PaperTradeQuantityReconciliation",
    "PaperTradeReconciliationResult",
    "PaperTradeReconciliationService",
    "render_markdown",
]
