"""Research-only paper trade fill ledger.

This module is deliberately separate from ``PortfolioService``.  The manual
Portfolio JSONL store represents user-recorded holdings, while this ledger
represents governed paper execution evidence.  A paper event is append-only
and never authorizes a broker order or mutates the formal Portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Any, Iterable


PAPER_TRADE_LEDGER_SCHEMA_VERSION = "paper-trade-ledger.v1"
PAPER_TRADE_EVENT_STATUSES = frozenset(
    {"filled", "partially_filled", "rejected", "cancelled"}
)
PAPER_TRADE_SIDES = frozenset({"buy", "sell"})
# ``source_event_id`` comes from an importing source and is unique within a
# paper portfolio.  ``fill_id`` remains the ledger-wide primary key.  Keeping
# the domain in the identity check allows two portfolios to import the same
# source-system event namespace without falsely colliding, while the Formal
# single-portfolio consumer still rejects cross-portfolio input explicitly.
PAPER_TRADE_SOURCE_IDENTITY_SCOPE = "portfolio_id:source_event_id"
MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class PaperTradeFill:
    """One immutable paper execution event.

    ``requested_quantity`` and ``filled_quantity`` are integer shares.  All
    monetary values are Decimal so this contract cannot silently introduce a
    binary floating-point amount into the paper cost ledger.
    """

    fill_id: str
    order_id: str
    portfolio_id: str
    event_date: str
    stock_code: str
    side: str
    requested_quantity: int
    filled_quantity: int
    reference_price: Decimal
    fill_price: Decimal | None
    commission: Decimal
    tax: Decimal
    slippage_cost: Decimal
    turnover_bp: int | None
    execution_gap_bp: int | None
    status: str
    source_event_id: str
    override_reason: str | None = None
    source_type: str = "paper_simulation"
    research_only: bool = True
    broker_order_allowed: bool = False
    auto_rebalance_allowed: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "fill_id",
            "order_id",
            "portfolio_id",
            "event_date",
            "stock_code",
            "source_event_id",
            "source_type",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        try:
            date.fromisoformat(str(self.event_date)[:10])
        except ValueError as exc:
            raise ValueError("event_date must be an ISO date") from exc
        if self.side not in PAPER_TRADE_SIDES:
            raise ValueError("side must be buy or sell")
        if self.status not in PAPER_TRADE_EVENT_STATUSES:
            raise ValueError(f"unsupported paper trade status: {self.status}")
        for field_name in ("requested_quantity", "filled_quantity"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")
        if self.filled_quantity > self.requested_quantity:
            raise ValueError("filled_quantity cannot exceed requested_quantity")
        for field_name in (
            "reference_price",
            "commission",
            "tax",
            "slippage_cost",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a finite non-negative Decimal")
        if self.reference_price <= 0:
            raise ValueError("reference_price must be positive")
        if self.fill_price is not None and (
            isinstance(self.fill_price, bool)
            or not isinstance(self.fill_price, Decimal)
            or not self.fill_price.is_finite()
            or self.fill_price <= 0
        ):
            raise ValueError("fill_price must be a positive Decimal or None")
        if self.filled_quantity > 0 and self.fill_price is None:
            raise ValueError("filled event requires fill_price")
        if self.status == "filled" and self.filled_quantity != self.requested_quantity:
            raise ValueError("filled status requires the full requested quantity")
        if self.status == "partially_filled" and not (
            0 < self.filled_quantity < self.requested_quantity
        ):
            raise ValueError("partially_filled status requires a partial quantity")
        if self.status in {"rejected", "cancelled"} and self.filled_quantity != 0:
            raise ValueError(f"{self.status} status cannot have filled quantity")
        if self.filled_quantity > 0 and self.execution_gap_bp is None:
            raise ValueError("filled event requires execution_gap_bp")
        if self.turnover_bp is not None and (
            isinstance(self.turnover_bp, bool)
            or not isinstance(self.turnover_bp, int)
            or self.turnover_bp < 0
        ):
            raise ValueError("turnover_bp must be a non-negative integer or None")
        if self.execution_gap_bp is not None and (
            isinstance(self.execution_gap_bp, bool)
            or not isinstance(self.execution_gap_bp, int)
        ):
            raise ValueError("execution_gap_bp must be an integer or None")
        if self.override_reason is not None and not str(self.override_reason).strip():
            raise ValueError("override_reason must be non-empty when supplied")
        if self.research_only is not True:
            raise ValueError("paper trade events must remain research_only")
        if self.broker_order_allowed is not False:
            raise ValueError("paper trade events cannot authorize broker orders")
        if self.auto_rebalance_allowed is not False:
            raise ValueError("paper trade events cannot authorize auto rebalance")

    @property
    def total_cost(self) -> Decimal:
        return (self.commission + self.tax + self.slippage_cost).quantize(MONEY_QUANTUM)

    @property
    def cash_settlement_cost(self) -> Decimal:
        """回傳會改變本筆成交現金結算的費用。

        ``fill_price`` 已包含模型化 tick 滑價，因此 gross 已反映該價格差異。
        ``slippage_cost`` 保留在 ``total_cost`` 作為歸因指標，投影現金時不能
        再扣一次。本 property 不輸出至 :meth:`to_dict`，讓歷史 ledger payload
        與 hash 維持位元相容。
        """

        return (self.commission + self.tax).quantize(MONEY_QUANTUM)

    @property
    def gross_amount(self) -> Decimal:
        if self.fill_price is None:
            return Decimal("0.00")
        return (self.fill_price * self.filled_quantity).quantize(MONEY_QUANTUM)

    @property
    def cost_record_ready(self) -> bool:
        return self.turnover_bp is not None and (
            self.status in {"filled", "partially_filled"}
            or self.filled_quantity == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAPER_TRADE_LEDGER_SCHEMA_VERSION,
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "portfolio_id": self.portfolio_id,
            "event_date": self.event_date,
            "stock_code": self.stock_code,
            "side": self.side,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "reference_price": str(self.reference_price),
            "fill_price": None if self.fill_price is None else str(self.fill_price),
            "commission": str(self.commission),
            "tax": str(self.tax),
            "slippage_cost": str(self.slippage_cost),
            "total_cost": str(self.total_cost),
            "gross_amount": str(self.gross_amount),
            "turnover_bp": self.turnover_bp,
            "execution_gap_bp": self.execution_gap_bp,
            "status": self.status,
            "source_event_id": self.source_event_id,
            "override_reason": self.override_reason,
            "source_type": self.source_type,
            "research_only": self.research_only,
            "broker_order_allowed": self.broker_order_allowed,
            "auto_rebalance_allowed": self.auto_rebalance_allowed,
        }


class PaperTradeLedgerRepository:
    """Append-only SQLite writer for explicit paper fill events.

    The constructor is intentionally a writer boundary.  UI/readiness code
    must use ``ReadOnlySQLiteManager`` instead and therefore cannot create the
    schema merely by inspecting status.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def append(self, fill: PaperTradeFill) -> None:
        self.append_many((fill,))

    def append_many(self, fills: Iterable[PaperTradeFill]) -> None:
        entries = tuple(fills)
        if not entries:
            raise ValueError("at least one paper trade fill is required")
        fill_ids = tuple(item.fill_id for item in entries)
        source_event_keys = tuple(
            (item.portfolio_id, item.source_event_id) for item in entries
        )
        if len(set(fill_ids)) != len(fill_ids):
            raise ValueError("paper trade fill already exists: duplicate fill_id in batch")
        if len(set(source_event_keys)) != len(source_event_keys):
            raise ValueError(
                "paper trade fill already exists: duplicate portfolio/source_event_id in batch"
            )
        connection = sqlite3.connect(self.db_path)
        try:
            # Serialize the identity check with the insert.  A retry after a
            # process crash can then either observe the complete batch
            # (handled by the producer's exact readback) or fail closed.
            connection.execute("BEGIN IMMEDIATE")
            fill_placeholders = ",".join("?" for _ in fill_ids)
            existing = connection.execute(
                "SELECT fill_id FROM paper_trade_ledger "
                f"WHERE fill_id IN ({fill_placeholders})",
                fill_ids,
            ).fetchall()
            if not existing:
                source_clauses = " OR ".join(
                    "(portfolio_id = ? AND source_event_id = ?)"
                    for _ in source_event_keys
                )
                source_params = tuple(
                    value
                    for portfolio_id, source_event_id in source_event_keys
                    for value in (portfolio_id, source_event_id)
                )
                existing = connection.execute(
                    "SELECT fill_id FROM paper_trade_ledger WHERE "
                    + source_clauses,
                    source_params,
                ).fetchall()
            if existing:
                raise ValueError(
                    "paper trade fill already exists: fill_id or "
                    "portfolio/source_event_id"
                )
            connection.executemany(
                    """
                    INSERT INTO paper_trade_ledger (
                        schema_version, fill_id, order_id, portfolio_id, event_date,
                        stock_code, side, requested_quantity, filled_quantity,
                        reference_price, fill_price, commission, tax, slippage_cost,
                        turnover_bp, execution_gap_bp, status, source_event_id,
                        override_reason, source_type, research_only,
                        broker_order_allowed, auto_rebalance_allowed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            PAPER_TRADE_LEDGER_SCHEMA_VERSION,
                            item.fill_id,
                            item.order_id,
                            item.portfolio_id,
                            item.event_date,
                            item.stock_code,
                            item.side,
                            item.requested_quantity,
                            item.filled_quantity,
                            str(item.reference_price),
                            None if item.fill_price is None else str(item.fill_price),
                            str(item.commission),
                            str(item.tax),
                            str(item.slippage_cost),
                            item.turnover_bp,
                            item.execution_gap_bp,
                            item.status,
                            item.source_event_id,
                            item.override_reason,
                            item.source_type,
                            int(item.research_only),
                            int(item.broker_order_allowed),
                            int(item.auto_rebalance_allowed),
                        )
                        for item in entries
                    ),
                )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ValueError("paper trade fill already exists") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list(
        self,
        *,
        portfolio_id: str = "paper-main",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[PaperTradeFill, ...]:
        clauses = ["portfolio_id = ?"]
        params: list[Any] = [portfolio_id]
        if start_date is not None:
            clauses.append("event_date >= ?")
            params.append(start_date)
        if end_date is not None:
            clauses.append("event_date <= ?")
            params.append(end_date)
        query = (
            "SELECT * FROM paper_trade_ledger WHERE "
            + " AND ".join(clauses)
            + " ORDER BY event_date, fill_id"
        )
        connection = sqlite3.connect(self.db_path)
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, tuple(params)).fetchall()
        finally:
            connection.close()
        return tuple(_row_to_fill(row) for row in rows)

    def _ensure_schema(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_trade_ledger (
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
                );
                CREATE INDEX IF NOT EXISTS idx_paper_trade_ledger_portfolio_date
                    ON paper_trade_ledger (portfolio_id, event_date, fill_id);
                CREATE INDEX IF NOT EXISTS idx_paper_trade_ledger_source_event
                    ON paper_trade_ledger (source_event_id);
                """
            )
        finally:
            connection.close()


def _row_to_fill(row: sqlite3.Row) -> PaperTradeFill:
    return PaperTradeFill(
        fill_id=str(row["fill_id"]),
        order_id=str(row["order_id"]),
        portfolio_id=str(row["portfolio_id"]),
        event_date=str(row["event_date"]),
        stock_code=str(row["stock_code"]),
        side=str(row["side"]),
        requested_quantity=int(row["requested_quantity"]),
        filled_quantity=int(row["filled_quantity"]),
        reference_price=Decimal(str(row["reference_price"])),
        fill_price=(None if row["fill_price"] is None else Decimal(str(row["fill_price"]))),
        commission=Decimal(str(row["commission"])),
        tax=Decimal(str(row["tax"])),
        slippage_cost=Decimal(str(row["slippage_cost"])),
        turnover_bp=(None if row["turnover_bp"] is None else int(row["turnover_bp"])),
        execution_gap_bp=(
            None if row["execution_gap_bp"] is None else int(row["execution_gap_bp"])
        ),
        status=str(row["status"]),
        source_event_id=str(row["source_event_id"]),
        override_reason=(None if row["override_reason"] is None else str(row["override_reason"])),
        source_type=str(row["source_type"]),
        research_only=bool(row["research_only"]),
        broker_order_allowed=bool(row["broker_order_allowed"]),
        auto_rebalance_allowed=bool(row["auto_rebalance_allowed"]),
    )


__all__ = [
    "PAPER_TRADE_EVENT_STATUSES",
    "PAPER_TRADE_LEDGER_SCHEMA_VERSION",
    "PAPER_TRADE_SOURCE_IDENTITY_SCOPE",
    "PaperTradeFill",
    "PaperTradeLedgerRepository",
]
