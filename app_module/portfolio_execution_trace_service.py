from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from app_module.portfolio_construction_dtos import (
    PortfolioAllocationRow,
    PortfolioConstructionResult,
)
from app_module.execution_slippage_model import (
    ExecutionSlippageModel, 
    TaiwanStockTickSlippageModel,
)


@dataclass(frozen=True)
class VirtualOrderEvent:
    event_id: str
    parent_order_id: str
    event_type: str
    event_time: str
    stock_code: str
    stock_name: str
    side: str
    quantity: int
    filled_quantity: int
    reference_price: Decimal
    reason_code: str
    fill_price: Decimal | None = None
    source_type: str = "portfolio_sandbox"
    source_id: str = ""
    research_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "parent_order_id": self.parent_order_id,
            "event_type": self.event_type,
            "event_time": self.event_time,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "side": self.side,
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "reference_price": str(self.reference_price),
            "fill_price": str(self.fill_price) if self.fill_price is not None else None,
            "reason_code": self.reason_code,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "research_only": self.research_only,
        }


class PortfolioExecutionTraceService:
    def build_trace(
        self,
        construction_result: PortfolioConstructionResult,
        *,
        partial_fill_bp_by_symbol: Mapping[str, int] | None = None,
        rejected_symbols: Mapping[str, str] | None = None,
        slippage_model: ExecutionSlippageModel | None = None,
    ) -> tuple[VirtualOrderEvent, ...]:
        partial_fill_bp_by_symbol = partial_fill_bp_by_symbol or {}
        rejected_symbols = rejected_symbols or {}
        slippage_model = slippage_model or TaiwanStockTickSlippageModel()
        events: list[VirtualOrderEvent] = []

        for allocation in construction_result.allocations:
            quantity = int(allocation.executable_shares or 0)
            if quantity <= 0:
                continue
            parent_order_id = self._parent_order_id(construction_result, allocation)
            events.append(
                self._event(
                    allocation=allocation,
                    construction_result=construction_result,
                    parent_order_id=parent_order_id,
                    event_type="created",
                    quantity=quantity,
                    filled_quantity=0,
                    reason_code="research_order_created",
                    sequence=len(events) + 1,
                    slippage_model=slippage_model,
                )
            )
            events.append(
                self._event(
                    allocation=allocation,
                    construction_result=construction_result,
                    parent_order_id=parent_order_id,
                    event_type="submitted",
                    quantity=quantity,
                    filled_quantity=0,
                    reason_code="research_order_submitted",
                    sequence=len(events) + 1,
                    slippage_model=slippage_model,
                )
            )
            rejection_reason = rejected_symbols.get(allocation.stock_code)
            if rejection_reason:
                events.append(
                    self._event(
                        allocation=allocation,
                        construction_result=construction_result,
                        parent_order_id=parent_order_id,
                        event_type="rejected",
                        quantity=quantity,
                        filled_quantity=0,
                        reason_code=str(rejection_reason),
                        sequence=len(events) + 1,
                        slippage_model=slippage_model,
                    )
                )
                continue

            partial_bp = int(partial_fill_bp_by_symbol.get(allocation.stock_code, 0))
            if 0 < partial_bp < 10000:
                partial_quantity = quantity * partial_bp // 10000
                events.append(
                    self._event(
                        allocation=allocation,
                        construction_result=construction_result,
                        parent_order_id=parent_order_id,
                        event_type="partially_filled",
                        quantity=quantity,
                        filled_quantity=partial_quantity,
                        reason_code="research_partial_fill",
                        sequence=len(events) + 1,
                        slippage_model=slippage_model,
                    )
                )

            events.append(
                self._event(
                    allocation=allocation,
                    construction_result=construction_result,
                    parent_order_id=parent_order_id,
                    event_type="filled",
                    quantity=quantity,
                    filled_quantity=quantity,
                    reason_code="research_full_fill",
                    sequence=len(events) + 1,
                    slippage_model=slippage_model,
                )
            )

        return tuple(events)

    def _event(
        self,
        *,
        allocation: PortfolioAllocationRow,
        construction_result: PortfolioConstructionResult,
        parent_order_id: str,
        event_type: str,
        quantity: int,
        filled_quantity: int,
        reason_code: str,
        sequence: int,
        slippage_model: ExecutionSlippageModel,
    ) -> VirtualOrderEvent:
        
        fill_price = None
        if event_type in ("partially_filled", "filled"):
            fill_price = slippage_model.calculate_fill_price(
                allocation.reference_price, 
                side="buy"  # 目前 Sandbox 只做買入組合
            )

        return VirtualOrderEvent(
            event_id=f"{parent_order_id}:{sequence:04d}",
            parent_order_id=parent_order_id,
            event_type=event_type,
            event_time=construction_result.decision_date,
            stock_code=allocation.stock_code,
            stock_name=allocation.stock_name,
            side="buy",
            quantity=quantity,
            filled_quantity=filled_quantity,
            reference_price=allocation.reference_price,
            fill_price=fill_price,
            reason_code=reason_code,
            source_id=f"{construction_result.decision_date}:{construction_result.allocation_method}",
        )

    def _parent_order_id(
        self,
        construction_result: PortfolioConstructionResult,
        allocation: PortfolioAllocationRow,
    ) -> str:
        return f"vord:{construction_result.decision_date}:{allocation.stock_code}"

