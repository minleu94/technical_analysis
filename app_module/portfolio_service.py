"""Thin orchestration service for the Phase 4.1 Portfolio MVP."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app_module.dtos.portfolio_dtos import PortfolioDTO, PositionDTO, TradeDTO
from app_module.portfolio_store import PortfolioJsonlStore
from data_module.config import TWStockConfig
from portfolio_module import PortfolioValidationError, Trade, rebuild_positions, validate_trade

logger = logging.getLogger(__name__)


class PortfolioService:
    """Coordinates trade storage and derived position views.

    Trades are append-only source records. Positions are rebuilt from trades.
    """

    def __init__(self, config: TWStockConfig, position_service: object = None):
        self.config = config
        self.position_service = position_service
        self.store = PortfolioJsonlStore(config.output_root)

    def record_trade(
        self,
        stock_code: str,
        stock_name: str,
        side: str,
        quantity: float,
        price: float,
        trade_date: str,
        portfolio_id: str = "default",
        fees: float = 0.0,
        taxes: float = 0.0,
        currency: str = "TWD",
        notes: str = "",
        source_type: str = "",
        source_id: str = "",
        source_snapshot_hash: str = "",
        trade_id: Optional[str] = None,
    ) -> TradeDTO:
        """Append a manual trade record after domain validation."""
        created_at = datetime.now().isoformat()
        dto = TradeDTO(
            trade_id=trade_id or f"trade_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}",
            portfolio_id=portfolio_id,
            stock_code=stock_code,
            stock_name=stock_name,
            side=side.lower(),
            quantity=float(quantity),
            price=float(price),
            trade_date=trade_date,
            fees=float(fees),
            taxes=float(taxes),
            currency=currency,
            notes=notes,
            source_type=source_type,
            source_id=source_id,
            source_snapshot_hash=source_snapshot_hash,
            created_at=created_at,
        )

        existing_ids = {trade.trade_id for trade in self._load_domain_trades()}
        if dto.trade_id in existing_ids:
            raise PortfolioValidationError(f"trade_id already exists: {dto.trade_id}")

        trade = Trade.from_mapping(dto.to_dict())
        validate_trade(trade)

        # Validate the full rebuilt portfolio before appending the trade.
        rebuild_positions([*self._load_domain_trades(), trade])
        self.store.append_trade(dto.to_dict())
        logger.info("[PortfolioService] recorded trade %s", dto.trade_id)
        return dto

    def list_trades(self, portfolio_id: str = "default") -> List[TradeDTO]:
        trades = [TradeDTO.from_dict(item) for item in self.store.load_trades()]
        return [trade for trade in trades if trade.portfolio_id == portfolio_id]

    def list_positions(self, portfolio_id: str = "default") -> List[PositionDTO]:
        positions = rebuild_positions(self._load_domain_trades(portfolio_id=portfolio_id))
        return [self._position_to_dto(position) for position in positions]

    def get_position_detail(
        self,
        stock_code: str,
        portfolio_id: str = "default",
    ) -> Optional[PositionDTO]:
        for position in self.list_positions(portfolio_id=portfolio_id):
            if position.stock_code == stock_code:
                return position
        return None

    def get_portfolio(self, portfolio_id: str = "default") -> PortfolioDTO:
        positions = self.list_positions(portfolio_id=portfolio_id)
        return PortfolioDTO(
            portfolio_id=portfolio_id,
            portfolio_name="Default Portfolio",
            total_positions=len(positions),
            active_positions=sum(1 for position in positions if position.is_holding),
            positions=positions,
            total_invested_amount=sum(position.invested_amount for position in positions),
            total_realized_pnl=sum(position.realized_pnl for position in positions),
            updated_at=datetime.now().isoformat(),
        )

    def update_portfolio(self) -> PortfolioDTO:
        """Compatibility wrapper for the previous skeleton API."""
        return self.get_portfolio()

    def get_benchmark_comparison(self, benchmark_type: str = "buy_hold") -> Dict[str, Any]:
        return {
            "benchmark_type": benchmark_type,
            "portfolio_return": 0.0,
            "benchmark_return": 0.0,
            "excess_return": 0.0,
            "note": "Deferred in Phase 4.1 MVP",
        }

    def _load_domain_trades(self, portfolio_id: Optional[str] = None) -> List[Trade]:
        trades = [Trade.from_mapping(item) for item in self.store.load_trades()]
        if portfolio_id is not None:
            trades = [trade for trade in trades if trade.portfolio_id == portfolio_id]
        return trades

    def _position_to_dto(self, position) -> PositionDTO:
        data = position.to_dict()
        return PositionDTO.from_dict({**data, "schema_version": "4.1"})
