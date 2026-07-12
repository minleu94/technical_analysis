"""ScoringEngine 使用的 Decimal／整數 bp 純 kernel。"""

import math
from decimal import Decimal
from typing import Dict


def normalize_weights_to_bp(raw_weights: Dict[str, Decimal]) -> Dict[str, int]:
    """以最大餘額法正規化為 10,000 bp，同餘額依 key 升序。"""
    total_raw = sum(raw_weights.values())
    if total_raw == Decimal("0"):
        return {"pattern": 3000, "technical": 5000, "volume": 2000}

    exact_values = {
        key: (value / total_raw) * Decimal("10000")
        for key, value in raw_weights.items()
    }
    floor_values = {key: math.floor(value) for key, value in exact_values.items()}
    remainders = {
        key: exact_values[key] - Decimal(floor_values[key])
        for key in raw_weights
    }
    difference = 10_000 - sum(floor_values.values())
    ordered_keys = sorted(raw_weights, key=lambda key: (-remainders[key], key))
    result = floor_values.copy()
    for index in range(difference):
        result[ordered_keys[index % len(ordered_keys)]] += 1
    return result
