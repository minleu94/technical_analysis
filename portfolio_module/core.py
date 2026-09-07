"""Pure portfolio domain logic for the Phase 4.1 MVP.

This module intentionally has no app_module, UI, storage, or framework imports.
Trades are the canonical audit records; positions are derived projections.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional

from financial_module.units import quantize_money, to_decimal


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
            quantity=float(data.get("quantity", 0.0)),  # numeric-boundary: dto
            price=float(data.get("price", 0.0)),  # numeric-boundary: dto
            trade_date=str(data.get("trade_date", "")),
            fees=float(data.get("fees", 0.0)),  # numeric-boundary: dto
            taxes=float(data.get("taxes", 0.0)),  # numeric-boundary: dto
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
        amount = to_decimal(self.quantity) * to_decimal(self.average_cost)
        return float(quantize_money(amount))  # numeric-boundary: dto

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
    quantity_dec = to_decimal(trade.quantity)
    if quantity_dec != quantity_dec.to_integral_value():
        raise PortfolioValidationError("quantity must be whole shares")
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
            trade_quantity = to_decimal(trade.quantity)
            trade_price = quantize_money(to_decimal(trade.price))
            if existing is None or existing.quantity <= 0:
                positions[key] = Position(
                    portfolio_id=trade.portfolio_id,
                    stock_code=trade.stock_code,
                    stock_name=trade.stock_name,
                    quantity=float(trade_quantity),  # numeric-boundary: dto
                    average_cost=float(trade_price),  # numeric-boundary: dto
                    opened_at=trade.trade_date,
                    last_trade_date=trade.trade_date,
                    source_type=trade.source_type,
                    source_id=trade.source_id,
                    source_snapshot_hash=trade.source_snapshot_hash,
                    source_summary=dict(trade.source_summary or {}),
                    trade_ids=[trade.trade_id],
                )
            else:
                existing_quantity = to_decimal(existing.quantity)
                total_cost = existing_quantity * to_decimal(existing.average_cost)
                added_cost = trade_quantity * trade_price
                new_quantity = existing_quantity + trade_quantity
                existing.quantity = float(new_quantity)  # numeric-boundary: dto
                existing.average_cost = float(quantize_money((total_cost + added_cost) / new_quantity))  # numeric-boundary: dto
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

        trade_quantity = to_decimal(trade.quantity)
        realized = (quantize_money(to_decimal(trade.price)) - to_decimal(existing.average_cost)) * trade_quantity
        existing.realized_pnl = float(quantize_money(to_decimal(existing.realized_pnl) + realized))  # numeric-boundary: dto
        existing.quantity = float(to_decimal(existing.quantity) - trade_quantity)  # numeric-boundary: dto
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


@dataclass(frozen=True)
class LedgerPosition:
    """精確帳本投影；金額使用 Decimal，股數使用整數。"""

    portfolio_id: str
    stock_code: str
    stock_name: str
    quantity: int
    average_cost: Decimal
    realized_pnl: Decimal = Decimal("0.00")
    opened_at: str = ""
    last_trade_date: str = ""
    source_type: str = ""
    source_id: str = ""
    source_snapshot_hash: str = ""
    thesis_id: str = ""
    trade_ids: tuple[str, ...] = ()

    @property
    def position_id(self) -> str:
        return f"{self.portfolio_id}:{self.stock_code}"

    @property
    def invested_amount(self) -> Decimal:
        return quantize_money(self.average_cost * self.quantity)


@dataclass(frozen=True)
class LedgerProjection:
    """事件重播後的持倉、現金與補償摘要。"""

    portfolio_id: str
    source_namespace: str
    positions: tuple[LedgerPosition, ...]
    cash: Decimal
    realized_pnl: Decimal
    event_ids: tuple[str, ...]
    compensated_event_ids: tuple[str, ...] = ()

    @property
    def negative_cash(self) -> bool:
        return self.cash < 0


def rebuild_ledger_projection(
    events: Iterable[Mapping[str, Any] | Any],
    *,
    initial_cash: Decimal = Decimal("0.00"),
    reject_negative_cash: bool = False,
) -> LedgerProjection:
    """以不可變事件重建精確持倉與現金。

    ``events`` 可以是 data-layer event dataclass 或同形 mapping。補償事件只
    取消其所引用的原交易，原交易仍保留在事件序列中；不同 namespace 或
    portfolio 的事件會被拒絕，避免手動、paper、backtest 互相混充。
    """

    initial_cash = _ledger_decimal(initial_cash, "initial_cash")
    raw_events = list(events)
    if not raw_events:
        return LedgerProjection("", "", (), quantize_money(initial_cash), Decimal("0.00"), ())

    event_ids: list[str] = []
    by_id: dict[str, Any] = {}
    portfolio_id = str(_event_field(raw_events[0], "portfolio_id", ""))
    source_namespace = str(_event_field(raw_events[0], "source_namespace", ""))
    if not portfolio_id or not source_namespace:
        raise PortfolioValidationError("ledger event scope is required")
    compensation_targets: set[str] = set()
    for event in raw_events:
        event_id = str(_event_field(event, "event_id", ""))
        if not event_id or event_id in by_id:
            raise PortfolioValidationError("ledger event_id must be unique")
        if str(_event_field(event, "portfolio_id", "")) != portfolio_id:
            raise PortfolioValidationError("ledger events must share one portfolio")
        if str(_event_field(event, "source_namespace", "")) != source_namespace:
            raise PortfolioValidationError("ledger namespaces cannot be mixed")
        event_ids.append(event_id)
        by_id[event_id] = event
        if str(_event_field(event, "event_type", "trade")) == "compensation":
            target_id = str(_event_field(event, "reverses_event_id", ""))
            if not target_id or target_id in compensation_targets:
                raise PortfolioValidationError("compensation target must be unique")
            compensation_targets.add(target_id)

    for target_id in compensation_targets:
        if target_id not in by_id:
            raise PortfolioValidationError(f"compensation target is missing: {target_id}")
        if str(_event_field(by_id[target_id], "event_type", "trade")) != "trade":
            raise PortfolioValidationError("compensation cannot target compensation")

    active_events = [
        event
        for event in raw_events
        if str(_event_field(event, "event_type", "trade")) == "trade"
        and str(_event_field(event, "event_id", "")) not in compensation_targets
    ]
    active_events.sort(
        key=lambda event: (
            str(_event_field(event, "occurred_at", "")),
            str(_event_field(event, "created_at", "")),
            str(_event_field(event, "event_id", "")),
        )
    )

    working: dict[str, dict[str, Any]] = {}
    cash = initial_cash
    realized_pnl = Decimal("0.00")
    for event in active_events:
        event_id = str(_event_field(event, "event_id", ""))
        stock_code = str(_event_field(event, "stock_code", ""))
        stock_name = str(_event_field(event, "stock_name", ""))
        side = str(_event_field(event, "side", ""))
        quantity = _ledger_integer(_event_field(event, "quantity", 0), "quantity")
        price = _ledger_money(_event_field(event, "price", Decimal("0.00")), "price", positive=True)
        fees = _ledger_money(_event_field(event, "fees", Decimal("0.00")), "fees")
        taxes = _ledger_money(_event_field(event, "taxes", Decimal("0.00")), "taxes")
        if not stock_code or side not in {"buy", "sell"}:
            raise PortfolioValidationError("ledger trade requires stock_code and side")
        buy_cost = price * quantity + fees + taxes
        current = working.get(stock_code)
        if side == "buy":
            cash -= buy_cost
            if current is None:
                working[stock_code] = {
                    "portfolio_id": portfolio_id,
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "quantity": quantity,
                    "average_cost": quantize_money(buy_cost / quantity),
                    "realized_pnl": Decimal("0.00"),
                    "opened_at": str(_event_field(event, "occurred_at", "")),
                    "last_trade_date": str(_event_field(event, "occurred_at", "")),
                    "source_type": source_namespace,
                    "source_id": str(_event_field(event, "source_id", "")),
                    "source_snapshot_hash": str(_event_field(event, "source_snapshot_hash", "")),
                    "thesis_id": str(_event_field(event, "thesis_id", "")),
                    "trade_ids": [event_id],
                }
            else:
                old_quantity = current["quantity"]
                current["average_cost"] = quantize_money(
                    (current["average_cost"] * old_quantity + buy_cost) / (old_quantity + quantity)
                )
                current["quantity"] = old_quantity + quantity
                current["stock_name"] = stock_name or current["stock_name"]
                current["last_trade_date"] = str(_event_field(event, "occurred_at", ""))
                current["trade_ids"].append(event_id)
            realized = Decimal("0.00")
        else:
            if current is None or current["quantity"] < quantity:
                raise PortfolioValidationError(f"sell quantity exceeds open position for {stock_code}")
            proceeds = price * quantity - fees - taxes
            cash += proceeds
            realized = quantize_money((price - current["average_cost"]) * quantity - fees - taxes)
            current["realized_pnl"] = quantize_money(current["realized_pnl"] + realized)
            current["quantity"] -= quantity
            current["last_trade_date"] = str(_event_field(event, "occurred_at", ""))
            current["trade_ids"].append(event_id)
            if current["quantity"] == 0:
                del working[stock_code]
        realized_pnl = quantize_money(realized_pnl + realized)

    cash = quantize_money(cash)
    if reject_negative_cash and cash < 0:
        raise PortfolioValidationError("ledger projection has negative cash")
    positions = tuple(
        LedgerPosition(
            portfolio_id=item["portfolio_id"],
            stock_code=item["stock_code"],
            stock_name=item["stock_name"],
            quantity=item["quantity"],
            average_cost=item["average_cost"],
            realized_pnl=item["realized_pnl"],
            opened_at=item["opened_at"],
            last_trade_date=item["last_trade_date"],
            source_type=item["source_type"],
            source_id=item["source_id"],
            source_snapshot_hash=item["source_snapshot_hash"],
            thesis_id=item["thesis_id"],
            trade_ids=tuple(item["trade_ids"]),
        )
        for item in sorted(working.values(), key=lambda value: value["stock_code"])
    )
    return LedgerProjection(
        portfolio_id=portfolio_id,
        source_namespace=source_namespace,
        positions=positions,
        cash=cash,
        realized_pnl=realized_pnl,
        event_ids=tuple(sorted(event_ids)),
        compensated_event_ids=tuple(sorted(compensation_targets)),
    )


def ledger_unrealized_pnl(position: LedgerPosition, market_price: Decimal) -> Decimal:
    """以已提交市場價格計算未實現損益；缺價格由 caller 明確處理。"""

    price = _ledger_money(market_price, "market_price", positive=True)
    return quantize_money((price - position.average_cost) * position.quantity)


def _event_field(event: Mapping[str, Any] | Any, name: str, default: Any) -> Any:
    if isinstance(event, Mapping):
        return event.get(name, default)
    return getattr(event, name, default)


def _ledger_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise PortfolioValidationError(f"{field_name} must be Decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PortfolioValidationError(f"{field_name} must be Decimal") from exc
    if not result.is_finite():
        raise PortfolioValidationError(f"{field_name} must be finite")
    return result


def _ledger_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PortfolioValidationError(f"{field_name} must be a positive integer")
    return value


def _ledger_money(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    result = _ledger_decimal(value, field_name)
    if result != result.quantize(Decimal("0.01")):
        raise PortfolioValidationError(f"{field_name} must be expressed in cents")
    if positive and result <= 0:
        raise PortfolioValidationError(f"{field_name} must be positive")
    if not positive and result < 0:
        raise PortfolioValidationError(f"{field_name} must be non-negative")
    return result.quantize(Decimal("0.01"))
