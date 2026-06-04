"""Pure portfolio domain logic for the Phase 4.1 MVP.

This module intentionally has no app_module, UI, storage, or framework imports.
Trades are the canonical audit records; positions are derived projections.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


class PortfolioValidationError(ValueError):
    """Raised when a portfolio trade cannot be accepted by the MVP domain."""


@dataclass(frozen=True)
class Trade:
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

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "Trade":
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "portfolio_id": self.portfolio_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "trade_date": self.trade_date,
            "fees": self.fees,
            "taxes": self.taxes,
            "currency": self.currency,
            "notes": self.notes,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_snapshot_hash": self.source_snapshot_hash,
            "source_summary": dict(self.source_summary),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


@dataclass
class Position:
    portfolio_id: str
    stock_code: str
    stock_name: str
    quantity: float
    average_cost: float
    realized_pnl: float = 0.0
    opened_at: str = ""
    last_trade_date: str = ""
    source_type: str = ""
    source_id: str = ""
    source_snapshot_hash: str = ""
    source_summary: Dict[str, Any] = field(default_factory=dict)
    trade_ids: List[str] = field(default_factory=list)

    @property
    def position_id(self) -> str:
        return f"{self.portfolio_id}:{self.stock_code}"

    @property
    def is_holding(self) -> bool:
        return self.quantity > 0

    @property
    def invested_amount(self) -> float:
        return self.quantity * self.average_cost

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "portfolio_id": self.portfolio_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "quantity": self.quantity,
            "average_cost": self.average_cost,
            "invested_amount": self.invested_amount,
            "realized_pnl": self.realized_pnl,
            "is_holding": self.is_holding,
            "opened_at": self.opened_at,
            "last_trade_date": self.last_trade_date,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_snapshot_hash": self.source_snapshot_hash,
            "source_summary": dict(self.source_summary),
            "trade_ids": list(self.trade_ids),
        }


def validate_trade(trade: Trade) -> None:
    if not trade.trade_id:
        raise PortfolioValidationError("trade_id is required")
    if not trade.portfolio_id:
        raise PortfolioValidationError("portfolio_id is required")
    if not trade.stock_code:
        raise PortfolioValidationError("stock_code is required")
    if trade.side not in {"buy", "sell"}:
        raise PortfolioValidationError("side must be 'buy' or 'sell'")
    if trade.quantity <= 0:
        raise PortfolioValidationError("quantity must be greater than zero")
    if trade.price <= 0:
        raise PortfolioValidationError("price must be greater than zero")
    if not trade.trade_date:
        raise PortfolioValidationError("trade_date is required")


def rebuild_positions(trades: Iterable[Trade]) -> List[Position]:
    """Deterministically rebuild current positions from append-only trades."""
    positions: Dict[tuple[str, str], Position] = {}

    sorted_trades = sorted(
        trades,
        key=lambda trade: (trade.trade_date, trade.created_at, trade.trade_id),
    )

    for trade in sorted_trades:
        validate_trade(trade)
        key = (trade.portfolio_id, trade.stock_code)
        existing: Optional[Position] = positions.get(key)

        if trade.side == "buy":
            if existing is None or existing.quantity <= 0:
                positions[key] = Position(
                    portfolio_id=trade.portfolio_id,
                    stock_code=trade.stock_code,
                    stock_name=trade.stock_name,
                    quantity=trade.quantity,
                    average_cost=trade.price,
                    opened_at=trade.trade_date,
                    last_trade_date=trade.trade_date,
                    source_type=trade.source_type,
                    source_id=trade.source_id,
                    source_snapshot_hash=trade.source_snapshot_hash,
                    source_summary=dict(trade.source_summary or {}),
                    trade_ids=[trade.trade_id],
                )
            else:
                total_cost = existing.quantity * existing.average_cost
                added_cost = trade.quantity * trade.price
                new_quantity = existing.quantity + trade.quantity
                existing.quantity = new_quantity
                existing.average_cost = (total_cost + added_cost) / new_quantity
                existing.stock_name = trade.stock_name or existing.stock_name
                existing.last_trade_date = trade.trade_date
                existing.trade_ids.append(trade.trade_id)
            continue

        if existing is None or existing.quantity <= 0:
            raise PortfolioValidationError(
                f"cannot sell {trade.stock_code} without an open position"
            )
        if trade.quantity > existing.quantity:
            raise PortfolioValidationError(
                f"sell quantity exceeds open position for {trade.stock_code}"
            )

        existing.realized_pnl += (trade.price - existing.average_cost) * trade.quantity
        existing.quantity -= trade.quantity
        existing.last_trade_date = trade.trade_date
        existing.trade_ids.append(trade.trade_id)

    return [
        position
        for position in sorted(
            positions.values(),
            key=lambda item: (item.portfolio_id, item.stock_code),
        )
        if position.quantity > 0
    ]
