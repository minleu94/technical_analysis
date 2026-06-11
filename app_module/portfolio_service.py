"""Thin orchestration service for the Phase 4.1 Portfolio MVP."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4
import pandas as pd

from app_module.dtos.portfolio_dtos import PortfolioDTO, PositionDTO, TradeDTO
from app_module.portfolio_store import PortfolioJsonlStore
from data_module.config import TWStockConfig
from financial_module.units import quantize_money, to_decimal
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
        source_summary: Optional[Dict[str, Any]] = None,
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
            quantity=float(quantity),  # numeric-boundary: dto
            price=float(price),  # numeric-boundary: dto
            trade_date=trade_date,
            fees=float(fees),  # numeric-boundary: dto
            taxes=float(taxes),  # numeric-boundary: dto
            currency=currency,
            notes=notes,
            source_type=source_type,
            source_id=source_id,
            source_snapshot_hash=source_snapshot_hash,
            source_summary=dict(source_summary or {}),
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
            total_invested_amount=self._sum_money(position.invested_amount for position in positions),
            total_realized_pnl=self._sum_money(position.realized_pnl for position in positions),
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

    def delete_trade(self, trade_id: str) -> bool:
        """刪除單筆交易紀錄，並重新驗證與重寫儲存"""
        trades = self.store.load_trades()
        new_trades = [t for t in trades if t.get('trade_id') != trade_id]
        if len(new_trades) == len(trades):
            return False
            
        # 領域安全性校驗：重新計算持倉，防止出現超賣或非法狀態
        try:
            domain_trades = [Trade.from_mapping(item) for item in new_trades]
            rebuild_positions(domain_trades)
        except Exception as e:
            raise PortfolioValidationError(f"刪除此交易將導致持倉數據不合法: {str(e)}")
            
        self.store.overwrite_trades(new_trades)
        logger.info("[PortfolioService] deleted trade %s and successfully rebuilt positions", trade_id)
        return True

    def clear_all_data(self) -> None:
        """重設/清空所有交易紀錄"""
        self.store.overwrite_trades([])
        logger.info("[PortfolioService] cleared all trades data")

    def _load_domain_trades(self, portfolio_id: Optional[str] = None) -> List[Trade]:
        trades = [Trade.from_mapping(item) for item in self.store.load_trades()]
        if portfolio_id is not None:
            trades = [trade for trade in trades if trade.portfolio_id == portfolio_id]
        return trades

    def _sum_money(self, values) -> float:
        total = sum((to_decimal(value) for value in values), to_decimal("0"))
        return float(quantize_money(total))  # numeric-boundary: dto

    def get_current_price(self, stock_code: str) -> Optional[float]:
        """獲取指定個股的最新收盤價。"""
        if getattr(self.config, 'use_sqlite', False):
            try:
                from data_module.db_manager import DBManager
                db = DBManager(self.config)
                df = db.execute_query(
                    "SELECT 收盤價 FROM daily_prices WHERE 證券代號 = ? ORDER BY 日期 DESC LIMIT 1;",
                    (stock_code,)
                )
                if not df.empty:
                    return float(df.iloc[0]['收盤價'])
            except Exception as e:
                logger.warning("從 SQLite 獲取 %s 最新收盤價失敗: %s", stock_code, e)
        
        # 降級讀取 CSV
        try:
            daily_price_dir = self.config.daily_price_dir
            if daily_price_dir.exists():
                csv_files = sorted(list(daily_price_dir.glob("*.csv")), reverse=True)
                for file in csv_files[:3]:  # 檢查最近3天以防假日無交易
                    df = pd.read_csv(file)
                    if '證券代號' in df.columns:
                        df['證券代號'] = df['證券代號'].astype(str).str.zfill(4)
                        stock_row = df[df['證券代號'] == stock_code.zfill(4)]
                        if not stock_row.empty and '收盤價' in stock_row.columns:
                            return float(stock_row.iloc[0]['收盤價'])
        except Exception as e:
            logger.warning("從 CSV 獲取 %s 最新收盤價失敗: %s", stock_code, e)
        return None

    def _position_to_dto(self, position) -> PositionDTO:
        data = position.to_dict()
        current_price = self.get_current_price(position.stock_code)
        unrealized_pnl = None
        unrealized_pnl_pct = None
        
        if current_price is not None:
            qty_dec = to_decimal(position.quantity)
            cost_dec = to_decimal(position.average_cost)
            price_dec = to_decimal(current_price)
            
            pnl_dec = quantize_money((price_dec - cost_dec) * qty_dec)
            unrealized_pnl = float(pnl_dec)  # numeric-boundary: dto
            
            invested_dec = cost_dec * qty_dec
            if invested_dec > 0:
                pct_dec = (pnl_dec / invested_dec).quantize(Decimal("0.0001"))
                unrealized_pnl_pct = float(pct_dec)  # numeric-boundary: dto
            else:
                unrealized_pnl_pct = 0.0  # numeric-boundary: dto
                
        return PositionDTO.from_dict({
            **data,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "schema_version": "4.1"
        })
