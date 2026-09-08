"""Meta family weight 的可審核政策與狀態契約。

feature family weight 會參與 daily coverage 分母。若所有 Meta target 都是
常數，模型係數沒有可識別訊號；此時只能使用明確的 deterministic equal
weight，不能把數值求解殘差當成 feature importance。
"""

from __future__ import annotations

from typing import Final


FAMILY_WEIGHT_POLICY_COEFFICIENT_V1: Final[str] = "coefficient-v1"
FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1: Final[str] = "degenerate-equal-v1"
FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN: Final[str] = "legacy-unknown"

SUPPORTED_FAMILY_WEIGHT_POLICIES = frozenset(
    {
        FAMILY_WEIGHT_POLICY_COEFFICIENT_V1,
        FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
        FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN,
    }
)


FAMILY_WEIGHT_STATUS_COEFFICIENT_SIGNAL: Final[str] = (
    "coefficient_signal"
)
FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL: Final[str] = (
    "degenerate_unidentified_equal"
)
FAMILY_WEIGHT_STATUS_LEGACY_COEFFICIENT: Final[str] = (
    "legacy_coefficient_weights"
)
FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN: Final[str] = "legacy_unknown"

SUPPORTED_FAMILY_WEIGHT_STATUSES = frozenset(
    {
        FAMILY_WEIGHT_STATUS_COEFFICIENT_SIGNAL,
        FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL,
        FAMILY_WEIGHT_STATUS_LEGACY_COEFFICIENT,
        FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN,
    }
)


def validate_family_weight_status(
    value: object,
    *,
    field_name: str = "feature_family_weights_status",
) -> str:
    """拒絕未定義狀態，避免 coverage 權重語意被靜默猜測。"""

    if not isinstance(value, str) or value not in SUPPORTED_FAMILY_WEIGHT_STATUSES:
        raise ValueError(f"{field_name} is unsupported")
    return value


def validate_family_weight_policy(
    value: object,
    *,
    field_name: str = "family_weight_policy",
) -> str:
    """拒絕未定義 policy，避免 rank 或 caller 預設值偷換權重語意。"""

    if not isinstance(value, str) or value not in SUPPORTED_FAMILY_WEIGHT_POLICIES:
        raise ValueError(f"{field_name} is unsupported")
    return value


def validate_family_weight_binding(
    policy: object,
    status: object,
    *,
    field_prefix: str = "feature_family_weights",
) -> tuple[str, str]:
    """確認 policy 與已觀測的 family weight 狀態彼此一致。"""

    parsed_policy = validate_family_weight_policy(
        policy,
        field_name=f"{field_prefix}_policy",
    )
    parsed_status = validate_family_weight_status(
        status,
        field_name=f"{field_prefix}_status",
    )
    expected_policy_by_status = {
        FAMILY_WEIGHT_STATUS_COEFFICIENT_SIGNAL: (
            FAMILY_WEIGHT_POLICY_COEFFICIENT_V1
        ),
        FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL: (
            FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1
        ),
        FAMILY_WEIGHT_STATUS_LEGACY_COEFFICIENT: (
            FAMILY_WEIGHT_POLICY_COEFFICIENT_V1
        ),
        FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN: FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN,
    }
    if parsed_policy != expected_policy_by_status[parsed_status]:
        raise ValueError(f"{field_prefix} policy/status mismatch")
    return parsed_policy, parsed_status


__all__ = [
    "FAMILY_WEIGHT_POLICY_COEFFICIENT_V1",
    "FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1",
    "FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN",
    "FAMILY_WEIGHT_STATUS_COEFFICIENT_SIGNAL",
    "FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL",
    "FAMILY_WEIGHT_STATUS_LEGACY_COEFFICIENT",
    "FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN",
    "SUPPORTED_FAMILY_WEIGHT_STATUSES",
    "SUPPORTED_FAMILY_WEIGHT_POLICIES",
    "validate_family_weight_binding",
    "validate_family_weight_policy",
    "validate_family_weight_status",
]
