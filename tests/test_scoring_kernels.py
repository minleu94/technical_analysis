from decimal import Decimal

from decision_module.scoring_kernels import normalize_weights_to_bp


def test_normalize_weights_to_bp_uses_largest_remainder_and_stable_tie_break() -> None:
    result = normalize_weights_to_bp(
        {"volume": Decimal("1"), "technical": Decimal("1"), "pattern": Decimal("1")}
    )

    assert result == {"volume": 3333, "technical": 3333, "pattern": 3334}
    assert sum(result.values()) == 10_000


def test_normalize_weights_to_bp_preserves_zero_weight_default() -> None:
    assert normalize_weights_to_bp(
        {"pattern": Decimal("0"), "technical": Decimal("0"), "volume": Decimal("0")}
    ) == {"pattern": 3000, "technical": 5000, "volume": 2000}
