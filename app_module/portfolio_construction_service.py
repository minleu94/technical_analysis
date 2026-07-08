from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from app_module.portfolio_construction_dtos import (
    PortfolioAllocationRow,
    PortfolioConstructionCandidate,
    PortfolioConstructionRequest,
    PortfolioConstructionResult,
)
from financial_module.units import quantize_money, round_down_to_lot


class PortfolioConstructionService:
    def construct(self, request: PortfolioConstructionRequest) -> PortfolioConstructionResult:
        if request.capital_amount <= 0:
            raise ValueError("capital_amount must be positive")
        if request.lot_size is not None and request.lot_size <= 0:
            raise ValueError("lot_size must be positive when provided")

        candidates, diagnostics = self._eligible_candidates(request)
        weight_bp = self._target_weight_bp(request.allocation_method, candidates, diagnostics)
        allocations: list[PortfolioAllocationRow] = []
        cap_applied = False

        for candidate, target_bp in zip(candidates, weight_bp):
            constrained_bp = target_bp
            if request.max_position_weight_bp is not None:
                constrained_bp = min(constrained_bp, request.max_position_weight_bp)
            if constrained_bp < target_bp:
                cap_applied = True

            target_amount = self._amount_from_bp(request.capital_amount, target_bp)
            constrained_amount = self._amount_from_bp(request.capital_amount, constrained_bp)
            executable_amount, executable_shares, row_diagnostics = self._executable_amount(
                candidate=candidate,
                constrained_amount=constrained_amount,
                lot_size=request.lot_size,
            )
            
            if candidate.reference_price > 0 and constrained_bp == 0:
                if request.allocation_method == "inverse_volatility" and (candidate.volatility_bp is None or candidate.volatility_bp <= 0):
                    row_diagnostics.append("rejected_missing_volatility")
                else:
                    row_diagnostics.append("rejected_zero_target")
                    
            allocations.append(
                PortfolioAllocationRow(
                    stock_code=candidate.stock_code,
                    stock_name=candidate.stock_name,
                    target_weight_bp=target_bp,
                    constrained_weight_bp=constrained_bp,
                    target_amount=target_amount,
                    constrained_amount=constrained_amount,
                    executable_amount=executable_amount,
                    reference_price=candidate.reference_price,
                    executable_shares=executable_shares,
                    diagnostics=tuple(row_diagnostics),
                )
            )

        if cap_applied:
            diagnostics.append("max_position_cap_applied")
        executable_total = sum((row.executable_amount for row in allocations), Decimal("0.00"))
        residual_cash = quantize_money(request.capital_amount - executable_total)
        if request.lot_size is not None and residual_cash > 0:
            diagnostics.append("lot_sizing_residual_cash")

        return PortfolioConstructionResult(
            decision_date=request.decision_date,
            allocation_method=request.allocation_method,
            capital_amount=quantize_money(request.capital_amount),
            allocations=tuple(allocations),
            residual_cash=residual_cash,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )

    def _eligible_candidates(
        self,
        request: PortfolioConstructionRequest,
    ) -> tuple[tuple[PortfolioConstructionCandidate, ...], list[str]]:
        diagnostics: list[str] = []
        candidates: list[PortfolioConstructionCandidate] = []
        valid_count = 0
        for candidate in request.candidates:
            candidates.append(candidate)
            if candidate.reference_price <= 0:
                diagnostics.append(f"rejected_invalid_reference_price:{candidate.stock_code}")
                continue
            if request.allocation_method == "inverse_volatility" and (
                candidate.volatility_bp is None or candidate.volatility_bp <= 0
            ):
                diagnostics.append(f"rejected_missing_volatility:{candidate.stock_code}")
                continue
            valid_count += 1
            
        if valid_count == 0:
            raise ValueError("at least one eligible candidate is required")
        return tuple(candidates), diagnostics

    def _target_weight_bp(
        self,
        allocation_method: str,
        candidates: tuple[PortfolioConstructionCandidate, ...],
        diagnostics: list[str],
    ) -> list[int]:
        values = []
        for candidate in candidates:
            if candidate.reference_price <= 0:
                values.append(Decimal("0"))
            elif allocation_method == "equal_weight":
                values.append(Decimal("1"))
            elif allocation_method == "score_weight":
                values.append(Decimal(max(candidate.score_bp, 0)))
            elif allocation_method == "inverse_volatility":
                if candidate.volatility_bp is None or candidate.volatility_bp <= 0:
                    values.append(Decimal("0"))
                else:
                    values.append(Decimal("1") / Decimal(candidate.volatility_bp))
            else:
                raise ValueError(f"unsupported allocation_method: {allocation_method}")

        if sum(values, Decimal("0")) <= 0:
            diagnostics.append(f"{allocation_method}_all_zero_fallback_equal_weight")
            for i, candidate in enumerate(candidates):
                if candidate.reference_price > 0:
                    if allocation_method == "inverse_volatility" and (candidate.volatility_bp is None or candidate.volatility_bp <= 0):
                        continue
                    values[i] = Decimal("1")
                    
        return self._largest_remainder_bp(values)

    def _largest_remainder_bp(self, values: list[Decimal]) -> list[int]:
        total = sum(values, Decimal("0"))
        raw = [(value / total) * Decimal("10000") for value in values]
        floors = [int(item.to_integral_value(rounding=ROUND_DOWN)) for item in raw]
        remaining = 10000 - sum(floors)
        remainders = [
            (index, raw_value - Decimal(floors[index]))
            for index, raw_value in enumerate(raw)
        ]
        for index, _ in sorted(remainders, key=lambda item: (-item[1], item[0]))[:remaining]:
            floors[index] += 1
        return floors

    def _amount_from_bp(self, capital_amount: Decimal, weight_bp: int) -> Decimal:
        return quantize_money(capital_amount * Decimal(weight_bp) / Decimal("10000"))

    def _executable_amount(
        self,
        *,
        candidate: PortfolioConstructionCandidate,
        constrained_amount: Decimal,
        lot_size: int | None,
    ) -> tuple[Decimal, int | None, list[str]]:
        if candidate.reference_price <= 0:
            return Decimal("0.00"), 0 if lot_size is not None else None, ["rejected_invalid_reference_price"]
            
        if lot_size is None:
            return constrained_amount, None, []
            
        raw_shares = int((constrained_amount / candidate.reference_price).to_integral_value(rounding=ROUND_DOWN))
        executable_shares = round_down_to_lot(raw_shares, lot_size=lot_size)
        executable_amount = quantize_money(Decimal(executable_shares) * candidate.reference_price)
        diagnostics: list[str] = []
        if executable_shares == 0 and constrained_amount > 0:
            diagnostics.append("rejected_below_lot_size")
        elif executable_amount < constrained_amount:
            diagnostics.append("lot_sizing_floor_applied")
        return executable_amount, executable_shares, diagnostics

