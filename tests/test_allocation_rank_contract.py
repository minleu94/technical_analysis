from __future__ import annotations

import pytest

from ml_module.allocation_family_weight_contract import (
    FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
    FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN,
    FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL,
    FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN,
    validate_family_weight_binding,
)
from ml_module.allocation_rank_contract import (
    RANK_CONTRACT_V1,
    RANK_CONTRACT_V2,
    rank_values_bp,
)


def test_v1_makes_symbol_tiebreak_explicit_for_legacy_meta_inputs() -> None:
    # 舊版 frozen Meta 已看過 ordinal rank；這個契約保留其 deterministic 行為。
    assert rank_values_bp(
        (100, 100, 100),
        ("2330", "1101", "6505"),
        rank_contract=RANK_CONTRACT_V1,
    ) == (5_000, 0, 10_000)


def test_v2_assigns_equal_rank_to_equal_values_and_is_permutation_invariant() -> None:
    values = (100, 100, 200, 300, 300)
    symbols = ("2330", "1101", "1301", "6505", "2454")
    first = rank_values_bp(values, symbols, rank_contract=RANK_CONTRACT_V2)
    assert first == (0, 0, 5_000, 10_000, 10_000)

    permutation = (4, 2, 0, 3, 1)
    permuted = rank_values_bp(
        tuple(values[index] for index in permutation),
        tuple(symbols[index] for index in permutation),
        rank_contract=RANK_CONTRACT_V2,
    )
    restored = [0] * len(permutation)
    for position, original_index in enumerate(permutation):
        restored[original_index] = permuted[position]
    assert tuple(restored) == first


def test_rank_contract_rejects_unversioned_or_duplicate_tie_keys() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        rank_values_bp((1,), ("2330",), rank_contract="symbol_order")
    with pytest.raises(ValueError, match="unique"):
        rank_values_bp((1, 1), ("2330", "2330"), rank_contract=RANK_CONTRACT_V1)


def test_family_weight_binding_rejects_unknown_or_mismatched_policy() -> None:
    assert validate_family_weight_binding(
        FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
        FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL,
    ) == (
        FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
        FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL,
    )
    assert validate_family_weight_binding(
        FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN,
        FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN,
    ) == (
        FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN,
        FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN,
    )
    with pytest.raises(ValueError, match="policy/status mismatch"):
        validate_family_weight_binding(
            FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
            "coefficient_signal",
        )
    with pytest.raises(ValueError, match="unsupported"):
        validate_family_weight_binding("family-v9", FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN)
