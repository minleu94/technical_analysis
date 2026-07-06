from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class PortfolioConstructionCandidate:
    stock_code: str
    stock_name: str
    score_bp: int
    reference_price: Decimal
    volatility_bp: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioConstructionRequest:
    decision_date: str
    capital_amount: Decimal
    allocation_method: str
    candidates: tuple[PortfolioConstructionCandidate, ...]
    max_position_weight_bp: int | None = None
    lot_size: int | None = None


@dataclass(frozen=True)
class PortfolioAllocationRow:
    stock_code: str
    stock_name: str
    target_weight_bp: int
    constrained_weight_bp: int
    target_amount: Decimal
    constrained_amount: Decimal
    executable_amount: Decimal
    reference_price: Decimal
    executable_shares: int | None = None
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "target_weight_bp": self.target_weight_bp,
            "constrained_weight_bp": self.constrained_weight_bp,
            "target_amount": str(self.target_amount),
            "constrained_amount": str(self.constrained_amount),
            "executable_amount": str(self.executable_amount),
            "reference_price": str(self.reference_price),
            "executable_shares": self.executable_shares,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class PortfolioConstructionResult:
    decision_date: str
    allocation_method: str
    capital_amount: Decimal
    allocations: tuple[PortfolioAllocationRow, ...]
    residual_cash: Decimal
    diagnostics: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ("research_basis_not_trade_advice",)
    research_basis: bool = True
    policy: str = "research_only_portfolio_construction_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date,
            "allocation_method": self.allocation_method,
            "capital_amount": str(self.capital_amount),
            "allocations": [row.to_dict() for row in self.allocations],
            "residual_cash": str(self.residual_cash),
            "diagnostics": list(self.diagnostics),
            "warnings": list(self.warnings),
            "research_basis": self.research_basis,
            "policy": self.policy,
        }

