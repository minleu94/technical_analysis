"""投組權重週轉率的單一整數 bp 契約。"""

from __future__ import annotations

from collections.abc import Sequence


TOTAL_WEIGHT_BP = 10_000


def canonical_turnover_bp(
    *,
    current_position_weights_bp: Sequence[int],
    current_cash_bp: int,
    target_position_weights_bp: Sequence[int],
    target_cash_bp: int,
) -> int:
    """回傳含現金的一向週轉率：完整權重 L1 距離除以二。

    例如從 A 的 1,000 bp 輪動到 B 的 1,000 bp，週轉為 1,000 bp；
    從現金買入 A 的 1,000 bp 也同為 1,000 bp。輸入必須是同一個
    canonical symbol order，且持倉加現金各自嚴格等於 10,000 bp。
    """

    current = _weights(current_position_weights_bp, field_name="current")
    target = _weights(target_position_weights_bp, field_name="target")
    if len(current) != len(target):
        raise ValueError("current and target position vectors must align")
    current_cash = _weight(current_cash_bp, field_name="current_cash_bp")
    target_cash = _weight(target_cash_bp, field_name="target_cash_bp")
    if sum(current) + current_cash != TOTAL_WEIGHT_BP:
        raise ValueError("current positions plus cash must equal 10000 bp")
    if sum(target) + target_cash != TOTAL_WEIGHT_BP:
        raise ValueError("target positions plus cash must equal 10000 bp")

    gross_l1 = sum(
        abs(target_weight - current_weight)
        for current_weight, target_weight in zip(current, target, strict=True)
    ) + abs(target_cash - current_cash)
    if gross_l1 % 2:
        raise ValueError("complete portfolio weight L1 distance must be even")
    return gross_l1 // 2


def _weights(value: Sequence[int], *, field_name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} position weights must be a sequence")
    return tuple(
        _weight(item, field_name=f"{field_name}_position_weights_bp")
        for item in value
    )


def _weight(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must contain integer bp")
    if value < 0 or value > TOTAL_WEIGHT_BP:
        raise ValueError(f"{field_name} must be within 0..10000 bp")
    return value
