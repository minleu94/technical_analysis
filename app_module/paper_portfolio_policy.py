"""V2.4 紙上投資組合政策的唯讀評估器。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class PaperPortfolioAction(str, Enum):
    PAPER_TRADE_CANDIDATE = "PAPER_TRADE_CANDIDATE"
    NO_PAPER_TRADE = "NO_PAPER_TRADE"


def _validate_bp(field_name: str, value: object, *, minimum: int = 0, maximum: int = 10000) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be an integer bp value between {minimum} and {maximum}")


@dataclass(frozen=True)
class PaperPortfolioPolicyConfig:
    initial_capital: Decimal = Decimal("500000")
    minimum_cash_bp: int = 2000
    max_positions: int = 8
    max_single_position_bp: int = 1500
    max_sector_weight_bp: int = 3000
    rebalance_band_bp: int = 300
    minimum_trade_bp: int = 200
    weekly_turnover_cap_bp: int = 2000
    same_symbol_cooldown_trading_days: int = 5
    slippage_bp_per_side: int = 10
    commission_bp_per_side: int = 15
    sell_tax_bp: int = 30

    def __post_init__(self) -> None:
        if isinstance(self.initial_capital, bool) or not isinstance(self.initial_capital, Decimal):
            raise ValueError("initial_capital must be Decimal")
        if self.initial_capital <= Decimal("0"):
            raise ValueError("initial_capital must be positive")
        if isinstance(self.max_positions, bool) or not isinstance(self.max_positions, int) or not 1 <= self.max_positions <= 8:
            raise ValueError("max_positions must be an integer between 1 and 8")
        _validate_bp("minimum_cash_bp", self.minimum_cash_bp)
        _validate_bp("max_single_position_bp", self.max_single_position_bp, maximum=1500)
        _validate_bp("max_sector_weight_bp", self.max_sector_weight_bp)
        _validate_bp("rebalance_band_bp", self.rebalance_band_bp)
        _validate_bp("minimum_trade_bp", self.minimum_trade_bp)
        _validate_bp("weekly_turnover_cap_bp", self.weekly_turnover_cap_bp)
        if (
            isinstance(self.same_symbol_cooldown_trading_days, bool)
            or not isinstance(self.same_symbol_cooldown_trading_days, int)
            or self.same_symbol_cooldown_trading_days < 0
        ):
            raise ValueError("same_symbol_cooldown_trading_days must be a non-negative integer")
        _validate_bp("slippage_bp_per_side", self.slippage_bp_per_side)
        _validate_bp("commission_bp_per_side", self.commission_bp_per_side)
        _validate_bp("sell_tax_bp", self.sell_tax_bp)


@dataclass(frozen=True)
class PaperPortfolioRebalanceInput:
    stock_code: str
    current_weight_bp: int
    target_weight_bp: int
    current_cash_bp: int
    sector_weight_after_bp: int
    weekly_turnover_used_bp: int
    trading_days_since_last_trade: int

    def __post_init__(self) -> None:
        if not self.stock_code:
            raise ValueError("stock_code is required")
        for field_name in (
            "current_weight_bp",
            "target_weight_bp",
            "current_cash_bp",
            "sector_weight_after_bp",
            "weekly_turnover_used_bp",
        ):
            _validate_bp(field_name, getattr(self, field_name))
        if (
            isinstance(self.trading_days_since_last_trade, bool)
            or not isinstance(self.trading_days_since_last_trade, int)
            or self.trading_days_since_last_trade < 0
        ):
            raise ValueError("trading_days_since_last_trade must be a non-negative integer")


@dataclass(frozen=True)
class PaperPortfolioDecision:
    action: PaperPortfolioAction
    weight_gap_bp: int
    estimated_round_trip_cost_bp: int
    reasons: tuple[str, ...] = ()
    research_only: bool = True


class PaperPortfolioPolicy:
    """依核准 baseline 評估紙上再平衡，永遠不產生實際訂單。"""

    def __init__(self, config: PaperPortfolioPolicyConfig | None = None) -> None:
        self._config = config or PaperPortfolioPolicyConfig()

    def evaluate(self, value: PaperPortfolioRebalanceInput) -> PaperPortfolioDecision:
        gap_bp = value.target_weight_bp - value.current_weight_bp
        trade_bp = abs(gap_bp)
        cost_bp = self._estimated_round_trip_cost_bp()
        if value.target_weight_bp > self._config.max_single_position_bp:
            return self._reject(gap_bp, cost_bp, "single_position_cap_exceeded")
        if value.current_cash_bp < self._config.minimum_cash_bp:
            return self._reject(gap_bp, cost_bp, "minimum_cash_reserve_not_met")
        if value.sector_weight_after_bp > self._config.max_sector_weight_bp:
            return self._reject(gap_bp, cost_bp, "sector_cap_exceeded")
        if value.weekly_turnover_used_bp + trade_bp > self._config.weekly_turnover_cap_bp:
            return self._reject(gap_bp, cost_bp, "weekly_turnover_cap_exceeded")
        if value.trading_days_since_last_trade < self._config.same_symbol_cooldown_trading_days:
            return self._reject(gap_bp, cost_bp, "same_symbol_cooldown_active")
        if trade_bp <= self._config.rebalance_band_bp:
            return self._reject(gap_bp, cost_bp, "within_rebalance_band")
        if trade_bp < self._config.minimum_trade_bp:
            return self._reject(gap_bp, cost_bp, "below_minimum_trade")
        return PaperPortfolioDecision(
            action=PaperPortfolioAction.PAPER_TRADE_CANDIDATE,
            weight_gap_bp=gap_bp,
            estimated_round_trip_cost_bp=cost_bp,
        )

    def _estimated_round_trip_cost_bp(self) -> int:
        return (
            self._config.slippage_bp_per_side * 2
            + self._config.commission_bp_per_side * 2
            + self._config.sell_tax_bp
        )

    @staticmethod
    def _reject(gap_bp: int, cost_bp: int, reason: str) -> PaperPortfolioDecision:
        return PaperPortfolioDecision(
            action=PaperPortfolioAction.NO_PAPER_TRADE,
            weight_gap_bp=gap_bp,
            estimated_round_trip_cost_bp=cost_bp,
            reasons=(reason,),
        )
