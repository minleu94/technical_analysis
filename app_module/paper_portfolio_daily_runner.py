"""Causal daily mark-to-market runner for research paper portfolios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
)


MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class PaperPriceObservation:
    stock_code: str
    price_date: str
    available_date: str
    close: Decimal

    def __post_init__(self) -> None:
        if not self.stock_code:
            raise ValueError("stock_code is required")
        if isinstance(self.close, bool) or not isinstance(self.close, Decimal) or self.close <= 0:
            raise ValueError("close must be a positive Decimal")


@dataclass(frozen=True)
class PaperPortfolioDailyResult:
    snapshot: PaperPortfolioSnapshot
    diagnostics: tuple[str, ...]
    source_mode: str = "causal_mark_to_market"
    broker_order_allowed: bool = False
    auto_rebalance_allowed: bool = False


class PaperPortfolioDailyRunner:
    def run(
        self,
        *,
        prior: PaperPortfolioSnapshot,
        decision_date: str,
        prices: Iterable[PaperPriceObservation],
    ) -> PaperPortfolioDailyResult:
        if _date(decision_date) <= _date(prior.decision_date):
            raise ValueError("decision_date must be after prior snapshot")
        observations = tuple(prices)
        marked: list[tuple[PaperPortfolioPositionSnapshot, Decimal, Decimal, str]] = []
        diagnostics: list[str] = []
        for position in prior.positions:
            visible = tuple(
                item
                for item in observations
                if item.stock_code == position.stock_code
                and _date(item.available_date) <= _date(decision_date)
                and _date(item.price_date) <= _date(decision_date)
            )
            if not visible:
                raise ValueError(f"missing causal price for {position.stock_code}")
            selected = max(visible, key=lambda item: (item.price_date, item.available_date))
            if selected.price_date != decision_date:
                diagnostics.append(f"previous_visible_trading_day:{position.stock_code}")
            market_value = (selected.close * position.quantity).quantize(MONEY_QUANTUM)
            marked.append((position, selected.close, market_value, selected.price_date))
        total_value = (prior.cash + sum((item[2] for item in marked), Decimal("0"))).quantize(
            MONEY_QUANTUM
        )
        positions = tuple(
            PaperPortfolioPositionSnapshot(
                stock_code=position.stock_code,
                quantity=position.quantity,
                mark_price=price,
                market_value=market_value,
                weight_bp=int(market_value * 10000 / total_value) if total_value else 0,
            )
            for position, price, market_value, _ in marked
        )
        snapshot = PaperPortfolioSnapshot(
            snapshot_id=f"{prior.portfolio_id}-{decision_date.replace('-', '')}",
            portfolio_id=prior.portfolio_id,
            decision_date=decision_date,
            source_result_id=prior.source_result_id,
            cash=prior.cash,
            total_value=total_value,
            positions=positions,
        )
        return PaperPortfolioDailyResult(snapshot=snapshot, diagnostics=tuple(diagnostics))


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
