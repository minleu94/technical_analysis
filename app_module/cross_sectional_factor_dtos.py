"""V1.6 橫斷面 factor snapshot DTO。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
import hashlib
from types import MappingProxyType
from typing import Any, Mapping

from app_module.research_run_dtos import canonical_json
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ConceptBasketDefinition:
    basket_id: str
    display_name: str
    basket_version: str
    members: tuple[str, ...]
    available_date: date
    missing_policy: MissingPolicy = MissingPolicy.SKIP
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.basket_id:
            raise ValueError("basket_id must not be empty")
        if not self.basket_version:
            raise ValueError("basket_version must not be empty")
        members = tuple(sorted({str(member) for member in self.members if str(member)}))
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "metadata", _deep_freeze_mapping(self.metadata))

    def to_dict(self) -> JsonObject:
        return {
            "basket_id": self.basket_id,
            "display_name": self.display_name,
            "basket_version": self.basket_version,
            "members": list(self.members),
            "available_date": self.available_date.isoformat(),
            "missing_policy": self.missing_policy.value,
            "metadata": _to_json_safe(self.metadata),
        }


@dataclass(frozen=True)
class CrossSectionalFactorDiagnostic:
    code: str
    message: str
    factor_name: str = ""
    stock_code: str = ""
    severity: str = "warning"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("code must not be empty")
        object.__setattr__(self, "metadata", _deep_freeze_mapping(self.metadata))

    def to_dict(self) -> JsonObject:
        return {
            "code": self.code,
            "message": self.message,
            "factor_name": self.factor_name,
            "stock_code": self.stock_code,
            "severity": self.severity,
            "metadata": _to_json_safe(self.metadata),
        }


@dataclass(frozen=True)
class CrossSectionalFactorRow:
    row_id: str
    stock_code: str
    factor_name: str
    as_of_date: date
    available_date: date
    value: Decimal | int | str | None
    score_bp: int | None
    rank: int | None
    quantile_bp: int | None
    universe_size: int
    quality: FactorQuality
    missing_policy: MissingPolicy
    source_version: str
    sector: str | None = None
    concept_basket: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.row_id:
            raise ValueError("row_id must not be empty")
        if not self.stock_code:
            raise ValueError("stock_code must not be empty")
        if not self.factor_name:
            raise ValueError("factor_name must not be empty")
        _validate_optional_bp("score_bp", self.score_bp)
        _validate_optional_bp("quantile_bp", self.quantile_bp)
        if isinstance(self.rank, bool):
            raise TypeError("rank must be int or None")
        if self.rank is not None and self.rank < 1:
            raise ValueError("rank must be positive")
        if isinstance(self.universe_size, bool):
            raise TypeError("universe_size must be int")
        if self.universe_size < 1:
            raise ValueError("universe_size must be positive")
        if isinstance(self.value, bool) or (
            self.value is not None and not isinstance(self.value, (Decimal, int, str))
        ):
            raise TypeError("value must be Decimal, int, str, or None")
        object.__setattr__(self, "metadata", _deep_freeze_mapping(self.metadata))

    def to_dict(self) -> JsonObject:
        return {
            "row_id": self.row_id,
            "stock_code": self.stock_code,
            "factor_name": self.factor_name,
            "as_of_date": self.as_of_date.isoformat(),
            "available_date": self.available_date.isoformat(),
            "value": _to_json_safe(self.value),
            "score_bp": self.score_bp,
            "rank": self.rank,
            "quantile_bp": self.quantile_bp,
            "universe_size": self.universe_size,
            "quality": self.quality.value,
            "missing_policy": self.missing_policy.value,
            "source_version": self.source_version,
            "sector": self.sector,
            "concept_basket": self.concept_basket,
            "metadata": _to_json_safe(self.metadata),
        }


@dataclass(frozen=True)
class CrossSectionalFactorSnapshot:
    snapshot_id: str
    decision_date: date
    factor_set_version: str
    universe_id: str
    source_version: str
    rows: tuple[CrossSectionalFactorRow, ...] = ()
    diagnostics: tuple[CrossSectionalFactorDiagnostic, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    snapshot_hash: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("snapshot_id must not be empty")
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "metadata", _deep_freeze_mapping(self.metadata))
        if not self.snapshot_hash:
            object.__setattr__(self, "snapshot_hash", self.compute_hash())

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def hash_payload(self) -> JsonObject:
        return {
            "snapshot_id": self.snapshot_id,
            "decision_date": self.decision_date.isoformat(),
            "factor_set_version": self.factor_set_version,
            "universe_id": self.universe_id,
            "source_version": self.source_version,
            "rows": [row.to_dict() for row in self.rows],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metadata": _to_json_safe(self.metadata),
        }

    def compute_hash(self) -> str:
        digest = hashlib.sha256(canonical_json(self.hash_payload()).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def to_dict(self) -> JsonObject:
        payload = self.hash_payload()
        payload.update(
            {
                "snapshot_hash": self.snapshot_hash,
                "row_count": self.row_count,
                "created_at": self.created_at,
            }
        )
        return payload


def parse_factor_quality(value: Any) -> FactorQuality:
    raw = value.value if isinstance(value, Enum) else value
    return FactorQuality(str(raw))


def parse_missing_policy(value: Any) -> MissingPolicy:
    raw = value.value if isinstance(value, Enum) else value
    return MissingPolicy(str(raw))


def _validate_optional_bp(name: str, value: int | None) -> None:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be int or None")
    if value is not None and not 0 <= int(value) <= 10000:
        raise ValueError(f"{name} must be between 0 and 10000")


def _to_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        raise TypeError("metadata value is not json-safe: bool")
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_to_json_safe(item) for item in value), key=repr)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("metadata key is not json-safe: key must be str")
            result[key] = _to_json_safe(item)
        return result
    raise TypeError(f"metadata value is not json-safe: {type(value).__name__}")


def _deep_freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("metadata key must be str")
        frozen[key] = _deep_freeze(item)
    return MappingProxyType(frozen)


def _deep_freeze(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("metadata value type is not supported: bool")
    if isinstance(value, (str, int, Decimal, date, Enum)):
        return value
    if isinstance(value, Mapping):
        return _deep_freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    raise TypeError(f"metadata value type is not supported: {type(value).__name__}")
