"""配置型 ML shadow 特徵版本契約。

這裡的 contract 是 raw／frozen registry 之上的明確 projection。舊 frozen
model 的 registry hash 與 feature pack 不會被改寫；需要不同特徵語意的輸入
必須取得新的 release。contract hash 會綁定父 registry、完整納入的 feature
id、排除欄位與 market 變化值的推導方法。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable


MARKET_REPAIR_CONTRACT_VERSION = "allocation-feature-contract-market-repair-v2"
MARKET_CHANGE_DERIVATION_METHOD = (
    "official-consecutive-trade-close-decimal.v1"
)
DERIVED_MARKET_SOURCE_ID = (
    "derived:market_indices.official_consecutive_trade_close.v1"
)
EXCLUDED_TECHNICAL_CLASSIFICATION_FEATURE_IDS = (
    "technical_indicators.涨跌",
    "technical_indicators.漲跌(+/-)",
)
DERIVED_MARKET_FEATURE_IDS = (
    "market_indices.漲跌百分比",
    "market_indices.漲跌點數",
)


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_sha256(value: str, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != len("sha256:") + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")


@dataclass(frozen=True)
class AllocationFeatureContract:
    """一個可重播的 feature projection 與其 release 邊界。"""

    contract_version: str
    parent_feature_registry_hash: str
    included_feature_ids: tuple[str, ...]
    excluded_feature_ids: tuple[str, ...]
    derived_feature_ids: tuple[str, ...]
    derivation_method: str
    derived_source_id: str
    requires_new_release: bool = True

    def __post_init__(self) -> None:
        _require_sha256(
            self.parent_feature_registry_hash,
            field_name="parent_feature_registry_hash",
        )
        for field_name, values in (
            ("included_feature_ids", self.included_feature_ids),
            ("excluded_feature_ids", self.excluded_feature_ids),
            ("derived_feature_ids", self.derived_feature_ids),
        ):
            if (
                tuple(values) != tuple(sorted(values))
                or len(values) != len(set(values))
                or any(not value or not value.strip() for value in values)
            ):
                raise ValueError(f"{field_name} must be sorted and unique")
        if set(self.included_feature_ids).intersection(
            self.excluded_feature_ids
        ):
            raise ValueError("excluded features cannot remain included")
        if not self.derived_feature_ids:
            raise ValueError("derived features are required")
        if not self.derivation_method.strip():
            raise ValueError("derivation_method is required")
        if not self.derived_source_id.strip():
            raise ValueError("derived_source_id is required")
        if not isinstance(self.requires_new_release, bool):
            raise TypeError("requires_new_release must be bool")

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": "allocation-feature-contract.v1",
            "contract_version": self.contract_version,
            "parent_feature_registry_hash": self.parent_feature_registry_hash,
            "included_feature_ids": list(self.included_feature_ids),
            "excluded_feature_ids": list(self.excluded_feature_ids),
            "excluded_feature_semantics": {
                feature_id: {
                    "logical_type": "categorical_or_legacy_untyped",
                    "numeric_feature_allowed": False,
                    "reason": (
                        "source schema exposes a sign/classification field; "
                        "numeric coercion is not a value mapping"
                    ),
                }
                for feature_id in self.excluded_feature_ids
            },
            "derived_feature_ids": list(self.derived_feature_ids),
            "derivation_method": self.derivation_method,
            "derived_source_id": self.derived_source_id,
            "requires_new_release": self.requires_new_release,
        }

    @property
    def contract_hash(self) -> str:
        return _sha256_json(self.payload())


def build_market_repair_contract(
    *,
    parent_feature_registry_hash: str,
    feature_ids: Iterable[str],
) -> AllocationFeatureContract:
    """由父輸入實際 feature set 建立 market repair contract。

    父輸入的 feature set 會被完整綁定，避免只靠固定欄名清單產生另一個
    不相容 schema。排除欄位若缺失也不會被偷偷補成 numeric；呼叫端仍需
    驗證父輸入本身的 frozen schema。
    """

    normalized = tuple(sorted(set(feature_ids)))
    excluded = tuple(sorted(EXCLUDED_TECHNICAL_CLASSIFICATION_FEATURE_IDS))
    if not normalized:
        raise ValueError("feature_ids must not be empty")
    if not set(excluded).issubset(normalized):
        missing = sorted(set(excluded).difference(normalized))
        raise ValueError(
            "parent feature set is missing excluded classification fields: "
            + ",".join(missing)
        )
    included = tuple(
        feature_id for feature_id in normalized if feature_id not in set(excluded)
    )
    return AllocationFeatureContract(
        contract_version=MARKET_REPAIR_CONTRACT_VERSION,
        parent_feature_registry_hash=parent_feature_registry_hash,
        included_feature_ids=included,
        excluded_feature_ids=excluded,
        derived_feature_ids=tuple(sorted(DERIVED_MARKET_FEATURE_IDS)),
        derivation_method=MARKET_CHANGE_DERIVATION_METHOD,
        derived_source_id=DERIVED_MARKET_SOURCE_ID,
    )


def derived_source_manifest_hash(
    *,
    contract: AllocationFeatureContract,
    input_source_manifest_hash: str,
) -> str:
    """產生綁定父 source manifest 的 derived producer manifest hash。"""

    _require_sha256(input_source_manifest_hash, field_name="input_source_manifest_hash")
    return _sha256_json(
        {
            "schema_version": "allocation-derived-source-manifest.v1",
            "source_id": contract.derived_source_id,
            "input_source_id": "sqlite.market_indices",
            "input_source_manifest_hash": input_source_manifest_hash,
            "contract_version": contract.contract_version,
            "derivation_method": contract.derivation_method,
            "derived_feature_ids": list(contract.derived_feature_ids),
        }
    )
