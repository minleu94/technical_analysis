from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("JSON payload must be an object")
    return dict(value)


@dataclass(frozen=True)
class EvidenceOperationsManualApproval:
    readiness: str
    production_scheduler_allowed: bool = False
    blocking_gaps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    required_manual_checks: tuple[str, ...] = ()
    latest_smoke_status: str = ""
    working_copy_confirm_passed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "production_scheduler_allowed", bool(self.production_scheduler_allowed))
        object.__setattr__(self, "blocking_gaps", tuple(str(item) for item in _tuple(self.blocking_gaps)))
        object.__setattr__(self, "warnings", tuple(str(item) for item in _tuple(self.warnings)))
        object.__setattr__(
            self,
            "required_manual_checks",
            tuple(str(item) for item in _tuple(self.required_manual_checks)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocking_gaps"] = list(self.blocking_gaps)
        payload["warnings"] = list(self.warnings)
        payload["required_manual_checks"] = list(self.required_manual_checks)
        return payload


@dataclass(frozen=True)
class EvidenceOperationsDecisionQuality:
    reviews_count: int = 0
    open_item_count: int = 0
    action_item_count: int = 0
    review_status_counts: dict[str, int] = field(default_factory=dict)
    item_type_counts: dict[str, int] = field(default_factory=dict)
    warnings_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "reviews_count", int(self.reviews_count))
        object.__setattr__(self, "open_item_count", int(self.open_item_count))
        object.__setattr__(self, "action_item_count", int(self.action_item_count))
        object.__setattr__(self, "review_status_counts", _dict(self.review_status_counts))
        object.__setattr__(self, "item_type_counts", _dict(self.item_type_counts))
        object.__setattr__(self, "warnings_count", int(self.warnings_count))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceOperationsSignalDecay:
    observations_count: int = 0
    demote_candidate_count: int = 0
    retire_candidate_count: int = 0
    watch_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    confidence_counts: dict[str, int] = field(default_factory=dict)
    warnings_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations_count", int(self.observations_count))
        object.__setattr__(self, "demote_candidate_count", int(self.demote_candidate_count))
        object.__setattr__(self, "retire_candidate_count", int(self.retire_candidate_count))
        object.__setattr__(self, "watch_count", int(self.watch_count))
        object.__setattr__(self, "status_counts", _dict(self.status_counts))
        object.__setattr__(self, "confidence_counts", _dict(self.confidence_counts))
        object.__setattr__(self, "warnings_count", int(self.warnings_count))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceOperationsWeeklyReview:
    start_date: str
    end_date: str
    status: str
    manual_approval: EvidenceOperationsManualApproval
    decision_quality: EvidenceOperationsDecisionQuality
    signal_decay: EvidenceOperationsSignalDecay
    manual_lifecycle_candidates: tuple[dict[str, Any], ...] = ()
    next_actions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    write_performed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "manual_lifecycle_candidates",
            tuple(_dict(item) for item in _tuple(self.manual_lifecycle_candidates)),
        )
        object.__setattr__(self, "next_actions", tuple(str(item) for item in _tuple(self.next_actions)))
        object.__setattr__(self, "warnings", tuple(str(item) for item in _tuple(self.warnings)))
        object.__setattr__(self, "write_performed", bool(self.write_performed))

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "status": self.status,
            "manual_approval": self.manual_approval.to_dict(),
            "decision_quality": self.decision_quality.to_dict(),
            "signal_decay": self.signal_decay.to_dict(),
            "manual_lifecycle_candidates": [dict(item) for item in self.manual_lifecycle_candidates],
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
            "write_performed": self.write_performed,
        }


@dataclass(frozen=True)
class EvidenceOperationsActionItemPlan:
    start_date: str
    end_date: str
    dry_run: bool = True
    open_items_seen: int = 0
    action_items_planned: int = 0
    action_items_created: int = 0
    action_items_skipped_existing: int = 0
    planned_action_items: tuple[dict[str, Any], ...] = ()
    write_performed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "dry_run", bool(self.dry_run))
        object.__setattr__(self, "open_items_seen", int(self.open_items_seen))
        object.__setattr__(self, "action_items_planned", int(self.action_items_planned))
        object.__setattr__(self, "action_items_created", int(self.action_items_created))
        object.__setattr__(self, "action_items_skipped_existing", int(self.action_items_skipped_existing))
        object.__setattr__(self, "planned_action_items", tuple(_dict(item) for item in _tuple(self.planned_action_items)))
        object.__setattr__(self, "write_performed", bool(self.write_performed))

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "dry_run": self.dry_run,
            "open_items_seen": self.open_items_seen,
            "action_items_planned": self.action_items_planned,
            "action_items_created": self.action_items_created,
            "action_items_skipped_existing": self.action_items_skipped_existing,
            "planned_action_items": [dict(item) for item in self.planned_action_items],
            "write_performed": self.write_performed,
        }
