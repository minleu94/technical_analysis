from abc import ABC, abstractmethod
from decimal import Decimal

from financial_module.units import quantize_money


class ExecutionSlippageModel(ABC):
    """
    執行模型擬真的滑價計算介面。
    """
    @abstractmethod
    def calculate_fill_price(self, reference_price: Decimal, side: str) -> Decimal:
        """
        根據參考價格與買賣方向計算包含滑價的實際成交價。
        side: "buy" or "sell"
        """
        pass


class NoSlippageModel(ExecutionSlippageModel):
    """
    無滑價模型 (維持原價)
    """
    def calculate_fill_price(self, reference_price: Decimal, side: str) -> Decimal:
        return quantize_money(reference_price)


class FixedBPSlippageModel(ExecutionSlippageModel):
    """
    固定基點 (bp) 滑價模型
    買入時價格往上加 bp%，賣出時價格往下減 bp%
    """
    def __init__(self, slippage_bp: int):
        self.slippage_bp = slippage_bp

    def calculate_fill_price(self, reference_price: Decimal, side: str) -> Decimal:
        if side == "buy":
            multiplier = Decimal("1") + (Decimal(self.slippage_bp) / Decimal("10000"))
        elif side == "sell":
            multiplier = Decimal("1") - (Decimal(self.slippage_bp) / Decimal("10000"))
        else:
            multiplier = Decimal("1")
        
        fill_price = reference_price * multiplier
        if fill_price <= Decimal("0.00"):
            fill_price = Decimal("0.01")
            
        return quantize_money(fill_price)


class TaiwanStockTickSlippageModel(ExecutionSlippageModel):
    """
    台股 Tick 單位滑價模型
    買入時往上加 N 個 tick，賣出時往下減 N 個 tick。
    """
    def __init__(self, ticks: int = 1):
        self.ticks = ticks

    def calculate_fill_price(self, reference_price: Decimal, side: str) -> Decimal:
        tick_size = self._get_tick_size(reference_price)
        slippage_amount = tick_size * Decimal(self.ticks)
        
        if side == "buy":
            fill_price = reference_price + slippage_amount
        elif side == "sell":
            fill_price = reference_price - slippage_amount
        else:
            fill_price = reference_price
            
        # 確保價格不會因為滑價變為負數或0
        if fill_price <= Decimal("0.00"):
            fill_price = Decimal("0.01")
            
        return quantize_money(fill_price)

    def _get_tick_size(self, price: Decimal) -> Decimal:
        if price < Decimal("10"):
            return Decimal("0.01")
        elif price < Decimal("50"):
            return Decimal("0.05")
        elif price < Decimal("100"):
            return Decimal("0.10")
        elif price < Decimal("500"):
            return Decimal("0.50")
        elif price < Decimal("1000"):
            return Decimal("1.00")
        else:
            return Decimal("5.00")
