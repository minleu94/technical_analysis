from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

FactorValue = Decimal | int | str | None


class FactorQuality(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    MISSING = "missing"
    NEUTRAL = "neutral"
    STALE = "stale"


class MissingPolicy(str, Enum):
    FAIL_CLOSED = "fail_closed"
    NEUTRAL = "neutral"
    SKIP = "skip"


@dataclass(frozen=True)
class FactorRecord:
    factor_name: str
    stock_code: str
    as_of_date: date
    available_date: date
    value: FactorValue
    score_bp: int | None
    quality: FactorQuality
    missing_policy: MissingPolicy
    source_version: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.factor_name:
            raise ValueError("factor_name must not be empty")
        if not self.stock_code:
            raise ValueError("stock_code must not be empty")
        if isinstance(self.value, bool) or (
            self.value is not None and not isinstance(self.value, (Decimal, int, str))
        ):
            raise TypeError("value must be Decimal, int, str, or None")
        if isinstance(self.score_bp, bool):
            raise TypeError("score_bp must be int or None")
        if self.score_bp is not None and not 0 <= self.score_bp <= 10000:
            raise ValueError("score_bp must be between 0 and 10000")
        object.__setattr__(
            self,
            "metadata",
            _deep_freeze_mapping(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        value: str | int | None
        if isinstance(self.value, Decimal):
            value = str(self.value)
        else:
            value = self.value

        return {
            "factor_name": self.factor_name,
            "stock_code": self.stock_code,
            "as_of_date": self.as_of_date.isoformat(),
            "available_date": self.available_date.isoformat(),
            "value": value,
            "score_bp": self.score_bp,
            "quality": self.quality.value,
            "missing_policy": self.missing_policy.value,
            "source_version": self.source_version,
            "metadata": _to_json_safe(self.metadata),
        }


@dataclass(frozen=True)
class FactorDefinition:
    factor_name: str
    display_name: str
    category: str
    source_version: str
    default_missing_policy: MissingPolicy
    neutral_score_bp: int | None = None
    stale_after_days: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.neutral_score_bp, bool):
            raise TypeError("neutral_score_bp must be int or None")
        if self.neutral_score_bp is not None and not 0 <= self.neutral_score_bp <= 10000:
            raise ValueError("neutral_score_bp must be between 0 and 10000")


@dataclass(frozen=True)
class FactorDiagnostic:
    code: str
    factor_name: str
    stock_code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "factor_name": self.factor_name,
            "stock_code": self.stock_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class FactorGateResult:
    accepted: tuple[FactorRecord, ...] = ()
    neutralized: tuple[FactorRecord, ...] = ()
    skipped: tuple[FactorRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", tuple(self.accepted))
        object.__setattr__(self, "neutralized", tuple(self.neutralized))
        object.__setattr__(self, "skipped", tuple(self.skipped))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


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
        items = [_to_json_safe(item) for item in value]
        return sorted(items, key=repr)
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
