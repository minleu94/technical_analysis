"""TWSE T86 retroactive candidate pilot 的不可變資料契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class T86CandidateRow:
    observation_date: str
    symbol: str
    name: str
    quantities: Mapping[str, int]
    raw_row_sha256: str
    first_observed_at: datetime
    available_at: None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantities", MappingProxyType(dict(self.quantities)))


@dataclass(frozen=True)
class T86NormalizationResult:
    rows: tuple[T86CandidateRow, ...]
    raw_row_count: int
    accepted_count: int
    quarantined_count: int
    ignored_count: int
    duplicate_count: int
    conflict_count: int
    quarantines: tuple[Mapping[str, str], ...]
    ignored: tuple[Mapping[str, str], ...]
    symbols: tuple[str, ...]
    observed_symbols: tuple[str, ...]
    schema_fields: tuple[str, ...]
    schema_sha256: str
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.raw_row_count != self.accepted_count + self.quarantined_count + self.ignored_count:
            raise ValueError("raw row conservation violated")
