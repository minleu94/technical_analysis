from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("history payload must be an object")
    return dict(value)


@dataclass(frozen=True)
class EvidenceOperationsHistoryRecord:
    review_id: str
    review_hash: str
    period_start: str
    period_end: str
    review_status: str
    scheduler_readiness: str
    production_scheduler_allowed: bool = False
    decision_quality_reviews_count: int = 0
    signal_decay_observations_count: int = 0
    manual_lifecycle_candidate_count: int = 0
    warnings_count: int = 0
    generated_by: str = ""
    payload_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "production_scheduler_allowed", bool(self.production_scheduler_allowed))
        object.__setattr__(self, "decision_quality_reviews_count", int(self.decision_quality_reviews_count))
        object.__setattr__(self, "signal_decay_observations_count", int(self.signal_decay_observations_count))
        object.__setattr__(self, "manual_lifecycle_candidate_count", int(self.manual_lifecycle_candidate_count))
        object.__setattr__(self, "warnings_count", int(self.warnings_count))
        object.__setattr__(self, "payload_json", _dict(self.payload_json))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload_json"] = dict(self.payload_json)
        return payload
