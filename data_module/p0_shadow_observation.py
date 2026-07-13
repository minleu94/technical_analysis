"""Common read-only observation emitted by P0 shadow adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class P0ShadowObservation:
    source_id: str
    symbol: str
    decision_date: str
    available_date: str | None
    source_version: str
    status: str
    diagnostics: tuple[str, ...]
    raw_payload: Mapping[str, Any]
    effective_from: str | None = None
    effective_to: str | None = None
    downstream_eligibility: str = "none"
    writes_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "symbol": self.symbol,
            "decision_date": self.decision_date,
            "available_date": self.available_date,
            "source_version": self.source_version,
            "status": self.status,
            "diagnostics": list(self.diagnostics),
            "raw_payload": dict(self.raw_payload),
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "downstream_eligibility": self.downstream_eligibility,
            "writes_allowed": self.writes_allowed,
        }
