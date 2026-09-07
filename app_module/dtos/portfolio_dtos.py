"""DTOs for the Phase 4.1 Portfolio & Journal MVP."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class TradeDTO:
    trade_id: str
    portfolio_id: str
    stock_code: str
    stock_name: str
    side: str
    quantity: float
    price: float
    trade_date: str
    fees: float = 0.0
    taxes: float = 0.0
    currency: str = "TWD"
    notes: str = ""
    source_type: str = ""
    source_id: str = ""
    source_snapshot_hash: str = ""
    source_summary: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    schema_version: str = "4.1"

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradeDTO":
        return cls(
            trade_id=str(data.get("trade_id", "")),
            portfolio_id=str(data.get("portfolio_id", "default")),
            stock_code=str(data.get("stock_code", "")),
            stock_name=str(data.get("stock_name", "")),
            side=str(data.get("side", "")).lower(),
            quantity=float(data.get("quantity", 0.0)),
            price=float(data.get("price", 0.0)),
            trade_date=str(data.get("trade_date", "")),
            fees=float(data.get("fees", 0.0)),
            taxes=float(data.get("taxes", 0.0)),
            currency=str(data.get("currency", "TWD")),
            notes=str(data.get("notes", "")),
            source_type=str(data.get("source_type", "")),
            source_id=str(data.get("source_id", "")),
            source_snapshot_hash=str(data.get("source_snapshot_hash", "")),
            source_summary=dict(data.get("source_summary", {}) or {}),
            created_at=str(data.get("created_at", "")),
            schema_version=str(data.get("schema_version", "4.1")),
        )


@dataclass
class PositionDTO:
    position_id: str
    portfolio_id: str
    stock_code: str
    stock_name: str
    quantity: float
    average_cost: float
    invested_amount: float
    realized_pnl: float = 0.0
    is_holding: bool = True
    opened_at: str = ""
    last_trade_date: str = ""
    source_type: str = ""
    source_id: str = ""
    source_snapshot_hash: str = ""
    source_summary: Dict[str, Any] = field(default_factory=dict)
    trade_ids: List[str] = field(default_factory=list)
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    schema_version: str = "4.1"

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PositionDTO":
        return cls(
            position_id=str(data.get("position_id", "")),
            portfolio_id=str(data.get("portfolio_id", "default")),
            stock_code=str(data.get("stock_code", "")),
            stock_name=str(data.get("stock_name", "")),
            quantity=float(data.get("quantity", 0.0)),
            average_cost=float(data.get("average_cost", 0.0)),
            invested_amount=float(data.get("invested_amount", 0.0)),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
            is_holding=bool(data.get("is_holding", True)),
            opened_at=str(data.get("opened_at", "")),
            last_trade_date=str(data.get("last_trade_date", "")),
            source_type=str(data.get("source_type", "")),
            source_id=str(data.get("source_id", "")),
            source_snapshot_hash=str(data.get("source_snapshot_hash", "")),
            source_summary=dict(data.get("source_summary", {}) or {}),
            trade_ids=list(data.get("trade_ids", [])),
            current_price=data.get("current_price"),
            unrealized_pnl=data.get("unrealized_pnl"),
            unrealized_pnl_pct=data.get("unrealized_pnl_pct"),
            schema_version=str(data.get("schema_version", "4.1")),
        )


@dataclass
class JournalEntryDTO:
    journal_id: str
    portfolio_id: str
    body: str
    title: str = ""
    stock_code: str = ""
    linked_type: str = ""
    linked_id: str = ""
    tags: List[str] = field(default_factory=list)
    source_type: str = ""
    source_id: str = ""
    source_snapshot_hash: str = ""
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = "4.1"

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JournalEntryDTO":
        return cls(
            journal_id=str(data.get("journal_id", "")),
            portfolio_id=str(data.get("portfolio_id", "default")),
            body=str(data.get("body", "")),
            title=str(data.get("title", "")),
            stock_code=str(data.get("stock_code", "")),
            linked_type=str(data.get("linked_type", "")),
            linked_id=str(data.get("linked_id", "")),
            tags=list(data.get("tags", [])),
            source_type=str(data.get("source_type", "")),
            source_id=str(data.get("source_id", "")),
            source_snapshot_hash=str(data.get("source_snapshot_hash", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            schema_version=str(data.get("schema_version", "4.1")),
        )


@dataclass
class PortfolioDTO:
    portfolio_id: str
    portfolio_name: str
    total_positions: int
    active_positions: int
    positions: List[PositionDTO] = field(default_factory=list)
    total_invested_amount: float = 0.0
    total_realized_pnl: float = 0.0
    updated_at: str = ""
    schema_version: str = "4.1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "portfolio_name": self.portfolio_name,
            "total_positions": self.total_positions,
            "active_positions": self.active_positions,
            "positions": [position.to_dict() for position in self.positions],
            "total_invested_amount": self.total_invested_amount,
            "total_realized_pnl": self.total_realized_pnl,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LedgerEventDTO:
    """精確帳本事件的 app boundary；不把 float 帶進 domain。"""

    event_id: str
    portfolio_id: str
    source_namespace: str
    occurred_at: str
    stock_code: str
    stock_name: str
    side: Optional[str]
    quantity: int
    price: Decimal
    fees: Decimal = Decimal("0.00")
    taxes: Decimal = Decimal("0.00")
    currency: str = "TWD"
    source_id: str = ""
    source_snapshot_hash: str = ""
    thesis_id: str = ""
    event_type: str = "trade"
    reverses_event_id: Optional[str] = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "portfolio_id": self.portfolio_id,
            "source_namespace": self.source_namespace,
            "occurred_at": self.occurred_at,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "side": self.side,
            "quantity": self.quantity,
            "price": str(self.price),
            "fees": str(self.fees),
            "taxes": str(self.taxes),
            "currency": self.currency,
            "source_id": self.source_id,
            "source_snapshot_hash": self.source_snapshot_hash,
            "thesis_id": self.thesis_id,
            "event_type": self.event_type,
            "reverses_event_id": self.reverses_event_id,
            "reason": self.reason,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class LedgerPositionDTO:
    """精確持倉 projection，供 UI／跨頁 composer 消費。"""

    position_id: str
    portfolio_id: str
    stock_code: str
    stock_name: str
    quantity: int
    average_cost: Decimal
    invested_amount: Decimal
    realized_pnl: Decimal
    opened_at: str
    last_trade_date: str
    source_type: str
    source_id: str
    source_snapshot_hash: str
    thesis_id: str
    trade_ids: tuple[str, ...] = ()
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "portfolio_id": self.portfolio_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "quantity": self.quantity,
            "average_cost": str(self.average_cost),
            "invested_amount": str(self.invested_amount),
            "realized_pnl": str(self.realized_pnl),
            "opened_at": self.opened_at,
            "last_trade_date": self.last_trade_date,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_snapshot_hash": self.source_snapshot_hash,
            "thesis_id": self.thesis_id,
            "trade_ids": list(self.trade_ids),
            "current_price": None if self.current_price is None else str(self.current_price),
            "unrealized_pnl": None if self.unrealized_pnl is None else str(self.unrealized_pnl),
        }


@dataclass(frozen=True)
class LedgerProjectionDTO:
    portfolio_id: str
    source_namespace: str
    positions: tuple[LedgerPositionDTO, ...]
    cash: Decimal
    realized_pnl: Decimal
    event_ids: tuple[str, ...]
    compensated_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "source_namespace": self.source_namespace,
            "positions": [item.to_dict() for item in self.positions],
            "cash": str(self.cash),
            "realized_pnl": str(self.realized_pnl),
            "event_ids": list(self.event_ids),
            "compensated_event_ids": list(self.compensated_event_ids),
            "negative_cash": self.cash < 0,
        }


@dataclass(frozen=True)
class PortfolioLedgerReadModelDTO:
    """TASK-LOOP-07 可直接消費的日期／品質／來源 ledger read-model。"""

    portfolio_id: str
    source_namespace: str
    as_of_date: str
    quality: str
    source_ledger_id: str
    source_ledger_hash: str
    event_count: int
    missing_inputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    candidate_only: bool = True
    positions: tuple[LedgerPositionDTO, ...] = ()
    cash: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "source_namespace": self.source_namespace,
            "as_of_date": self.as_of_date,
            "quality": self.quality,
            "source_ledger_id": self.source_ledger_id,
            "source_ledger_hash": self.source_ledger_hash,
            "event_count": self.event_count,
            "missing_inputs": list(self.missing_inputs),
            "warnings": list(self.warnings),
            "candidate_only": self.candidate_only,
            "positions": [item.to_dict() for item in self.positions],
            "cash": None if self.cash is None else str(self.cash),
            "realized_pnl": None if self.realized_pnl is None else str(self.realized_pnl),
        }
