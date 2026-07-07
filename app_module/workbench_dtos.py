from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


WORKBENCH_LEGACY_DRILLDOWN_TARGETS: dict[str, str] = {
    "daily_decision": "daily_decision",
    "evidence_review": "evidence_review",
    "evidence_mode": "evidence_review",
    "portfolio_review": "portfolio",
}


def _normalize_strings(values: tuple[str, ...] | list[str] | set[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(str(value) for value in values)


def _as_dict(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_as_dict(item) for item in value]
    if isinstance(value, list):
        return [_as_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _as_dict(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True)
class WorkbenchAccessBoundary:
    mode: str = "read_only"
    writes_allowed: bool = False
    production_scheduler_allowed: bool = False
    denied_actions: tuple[str, ...] = (
        "write_database",
        "register_scheduler",
        "place" "_order",
        "adjust_position",
        "apply_lifecycle_action",
        "recalculate_scoring",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "denied_actions", _normalize_strings(self.denied_actions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "writes_allowed": self.writes_allowed,
            "production_scheduler_allowed": self.production_scheduler_allowed,
            "denied_actions": list(self.denied_actions),
        }


@dataclass(frozen=True)
class WorkbenchStatusItem:
    item_id: str
    label: str
    value: str
    status: str
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "value": self.value,
            "status": self.status,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class WorkbenchReviewItem:
    item_id: str
    title: str
    severity: str
    source: str
    summary: str
    drilldown_target: str
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "severity": self.severity,
            "source": self.source,
            "summary": self.summary,
            "drilldown_target": self.drilldown_target,
            "code": self.code,
        }


@dataclass(frozen=True)
class WorkbenchEvidenceFeedItem:
    item_id: str
    label: str
    status: str
    summary: str
    source_trace: str
    degraded_reason: str
    drilldown_target: str
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", _normalize_strings(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "source_trace": self.source_trace,
            "degraded_reason": self.degraded_reason,
            "drilldown_target": self.drilldown_target,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class WorkbenchActionItem:
    item_id: str
    title: str
    source_type: str
    severity: str
    summary: str
    source_trace: str
    degraded_reason: str
    drilldown_target: str
    queue_group: str = "manual_review"
    source_label: str = ""
    sort_rank: int = 9999
    code: str | None = None
    write_intent: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "queue_group", str(self.queue_group or "manual_review"))
        object.__setattr__(self, "source_label", str(self.source_label or self.source_type))
        object.__setattr__(self, "sort_rank", int(self.sort_rank))

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "source_type": self.source_type,
            "severity": self.severity,
            "summary": self.summary,
            "source_trace": self.source_trace,
            "degraded_reason": self.degraded_reason,
            "drilldown_target": self.drilldown_target,
            "queue_group": self.queue_group,
            "source_label": self.source_label,
            "sort_rank": self.sort_rank,
            "code": self.code,
            "write_intent": self.write_intent,
        }


@dataclass(frozen=True)
class WorkbenchEvidenceSummary:
    item_id: str
    label: str
    status: str
    summary: str
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", _normalize_strings(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class WorkbenchChecklistItem:
    item_id: str
    label: str
    status: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class WorkbenchDashboardDTO:
    as_of_date: date
    generated_at: datetime
    source_mode: str
    access_boundary: WorkbenchAccessBoundary
    status_strip: tuple[WorkbenchStatusItem, ...]
    review_items: tuple[WorkbenchReviewItem, ...]
    evidence_summary: tuple[WorkbenchEvidenceSummary, ...]
    market_context: dict[str, Any]
    portfolio_watchlist_summary: dict[str, Any]
    daily_checklist: tuple[WorkbenchChecklistItem, ...]
    warnings: tuple[str, ...] = ()
    background_evidence_feed: tuple[WorkbenchEvidenceFeedItem, ...] = ()
    action_items: tuple[WorkbenchActionItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status_strip", tuple(self.status_strip))
        object.__setattr__(self, "review_items", tuple(self.review_items))
        object.__setattr__(self, "evidence_summary", tuple(self.evidence_summary))
        object.__setattr__(self, "daily_checklist", tuple(self.daily_checklist))
        object.__setattr__(self, "warnings", _normalize_strings(self.warnings))
        object.__setattr__(self, "background_evidence_feed", tuple(self.background_evidence_feed))
        object.__setattr__(self, "action_items", tuple(self.action_items))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "source_mode": self.source_mode,
            "access_boundary": self.access_boundary.to_dict(),
            "status_strip": [item.to_dict() for item in self.status_strip],
            "review_items": [item.to_dict() for item in self.review_items],
            "evidence_summary": [item.to_dict() for item in self.evidence_summary],
            "market_context": _as_dict(self.market_context),
            "portfolio_watchlist_summary": _as_dict(self.portfolio_watchlist_summary),
            "daily_checklist": [item.to_dict() for item in self.daily_checklist],
            "warnings": list(self.warnings),
            "background_evidence_feed": [item.to_dict() for item in self.background_evidence_feed],
            "action_items": [item.to_dict() for item in self.action_items],
        }
