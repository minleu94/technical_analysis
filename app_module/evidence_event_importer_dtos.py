from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any


def _date_text(value: date | str | None) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class EvidenceImportSource:
    name: str
    supported: bool = True
    reason: str = ""


@dataclass(frozen=True)
class EvidenceImportDiagnostic:
    code: str
    message: str = ""
    source_name: str = ""
    symbol: str | None = None
    severity: str = "warning"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "source_name": self.source_name,
            "symbol": self.symbol,
            "severity": self.severity,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceCaptureRequest:
    source: str
    decision_date: date | str | None = None
    start_date: date | str | None = None
    end_date: date | str | None = None
    result_id: str | None = None
    symbol: str | None = None
    limit: int | None = None
    dry_run: bool = True
    confirm: bool = False

    @property
    def decision_date_text(self) -> str | None:
        return _date_text(self.decision_date)

    @property
    def start_date_text(self) -> str | None:
        return _date_text(self.start_date)

    @property
    def end_date_text(self) -> str | None:
        return _date_text(self.end_date)


@dataclass(frozen=True)
class EvidenceImportResult:
    source_name: str
    decision_date: date | str | None
    event_payloads: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[EvidenceImportDiagnostic, ...] = ()

    @property
    def events_seen(self) -> int:
        return len(self.event_payloads)

    @property
    def events_valid(self) -> int:
        return len(self.event_payloads)

    @property
    def diagnostics_by_code(self) -> dict[str, int]:
        return dict(Counter(item.code for item in self.diagnostics))


@dataclass(frozen=True)
class EvidenceCaptureSummary:
    source_name: str
    decision_date: str | None
    dry_run: bool
    events_seen: int = 0
    events_valid: int = 0
    events_inserted: int = 0
    events_skipped_duplicate: int = 0
    events_failed: int = 0
    warnings_count: int = 0
    diagnostics_by_code: dict[str, int] = field(default_factory=dict)
    event_type_counts: dict[str, int] = field(default_factory=dict)
    quality_counts: dict[str, int] = field(default_factory=dict)
    diagnostics: tuple[EvidenceImportDiagnostic, ...] = ()
    sample_events: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "decision_date": self.decision_date,
            "dry_run": self.dry_run,
            "events_seen": self.events_seen,
            "events_valid": self.events_valid,
            "events_inserted": self.events_inserted,
            "events_skipped_duplicate": self.events_skipped_duplicate,
            "events_failed": self.events_failed,
            "warnings_count": self.warnings_count,
            "diagnostics_by_code": dict(self.diagnostics_by_code),
            "event_type_counts": dict(self.event_type_counts),
            "quality_counts": dict(self.quality_counts),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "sample_events": [dict(item) for item in self.sample_events],
        }

