"""金融核心數值邊界工具。"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Literal


MONEY_QUANT = Decimal("0.01")
BPS_DENOMINATOR = Decimal("10000")


def to_decimal(value: object) -> Decimal:
    """用字串轉 Decimal，避免把 binary float 誤差帶進金融核心。"""
    return Decimal(str(value))


def quantize_money(value: Decimal) -> Decimal:
    """將金額量化到分。"""
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def bps_to_rate(bps: object) -> Decimal:
    """將基點轉換為 Decimal 比率。"""
    return to_decimal(bps) / BPS_DENOMINATOR


def apply_bps_to_price(price: Decimal, bps: object, *, side: Literal["buy", "sell"]) -> Decimal:
    """依買賣方向套用滑價基點並量化成交價。"""
    rate = bps_to_rate(bps)
    if side == "buy":
        return quantize_money(price * (Decimal("1") + rate))
    if side == "sell":
        return quantize_money(price * (Decimal("1") - rate))
    raise ValueError("side 必須是 buy 或 sell")


def calculate_fee(value: Decimal, fee_bps: object, *, minimum_fee: Decimal = Decimal("20.00")) -> Decimal:
    """計算交易手續費，採用基點與最低手續費。"""
    fee = quantize_money(value * bps_to_rate(fee_bps))
    return max(fee, minimum_fee)


def calculate_slippage_cost(shares: int, reference_price: Decimal, slippage_bps: object) -> Decimal:
    """計算滑價成本。"""
    return quantize_money(Decimal(shares) * reference_price * bps_to_rate(slippage_bps))


def round_down_to_lot(shares: int, *, lot_size: int = 1000) -> int:
    """將股數向下取整到整股單位。"""
    if shares <= 0:
        return 0
    lots = (Decimal(shares) / Decimal(lot_size)).to_integral_value(rounding=ROUND_DOWN)
    return int(lots) * lot_size
