"""配置型 ML rank 的可版本化整數 bp 契約。

rank 會進入 expert vector 與 Meta Allocator，不能由 daily consumer 私自
改變。這個小模組讓 trainer、OOC builder、derived replay 與 inference 共用
同一個排序實作；既有 artifact 缺少 ``rank_contract`` 時仍使用 v1 相容政策。
"""

from __future__ import annotations

from typing import Sequence


RANK_CONTRACT_V1 = "allocation-rank-v1:ordinal_symbol_tiebreak"
RANK_CONTRACT_V2 = "allocation-rank-v2:dense_value_tiebreak"
DEFAULT_RANK_CONTRACT = RANK_CONTRACT_V1
SUPPORTED_RANK_CONTRACTS = frozenset({RANK_CONTRACT_V1, RANK_CONTRACT_V2})


def validate_rank_contract(value: object, *, field_name: str = "rank_contract") -> str:
    """驗證 artifact/run 選用的 rank 政策，拒絕未版本化字串。"""

    if not isinstance(value, str) or value not in SUPPORTED_RANK_CONTRACTS:
        raise ValueError(f"{field_name} is unsupported")
    return value


def rank_values_bp(
    predicted_values: Sequence[int],
    tie_keys: Sequence[str],
    *,
    rank_contract: str = DEFAULT_RANK_CONTRACT,
) -> tuple[int, ...]:
    """依已量化預測回傳原始位置順序對應的 rank bp。

    v1 延續 frozen artifact 的 deterministic ``(value, symbol)`` ordinal
    tie-break；相同值因此刻意得到不同 rank，但該行為已被契約化。v2 將
    相同值視為同一 dense group，group 依預測值升序均勻映射到 0..10000，
    避免股票代碼替相同預測製造差異。兩者都只用整數運算。
    """

    contract = validate_rank_contract(rank_contract)
    if len(predicted_values) != len(tie_keys):
        raise ValueError("rank values and tie keys must have equal length")
    if not predicted_values:
        return ()
    if any(isinstance(value, bool) or not isinstance(value, int) for value in predicted_values):
        raise TypeError("rank predicted values must be integers")
    if any(not isinstance(key, str) or not key for key in tie_keys):
        raise TypeError("rank tie keys must be non-empty strings")
    if len(set(tie_keys)) != len(tie_keys):
        raise ValueError("rank tie keys must be unique within a decision date")

    ordered = sorted(
        ((value, key, index) for index, (value, key) in enumerate(zip(predicted_values, tie_keys))),
        key=lambda item: (item[0], item[1]),
    )
    if len(ordered) == 1:
        return (5_000,)

    denominator = len(ordered) - 1
    result = [0] * len(ordered)
    if contract == RANK_CONTRACT_V1:
        for ordinal, (_value, _key, original_index) in enumerate(ordered):
            result[original_index] = (ordinal * 10_000) // denominator
        return tuple(result)

    # v2 dense groups: ties receive the same rank. The highest distinct value
    # remains 10000 even when the last group contains multiple rows.
    groups: list[tuple[int, list[int]]] = []
    for value, _key, original_index in ordered:
        if not groups or groups[-1][0] != value:
            groups.append((value, [original_index]))
        else:
            groups[-1][1].append(original_index)
    group_denominator = len(groups) - 1
    if group_denominator == 0:
        return (5_000,) * len(ordered)
    for group_index, (_value, original_indices) in enumerate(groups):
        rank = (group_index * 10_000) // group_denominator
        for original_index in original_indices:
            result[original_index] = rank
    return tuple(result)


__all__ = [
    "DEFAULT_RANK_CONTRACT",
    "RANK_CONTRACT_V1",
    "RANK_CONTRACT_V2",
    "SUPPORTED_RANK_CONTRACTS",
    "rank_values_bp",
    "validate_rank_contract",
]
