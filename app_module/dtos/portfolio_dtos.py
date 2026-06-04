"""DTOs for the Phase 4.1 Portfolio & Journal MVP."""

from dataclasses import dataclass, field
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
