from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


def _payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("collection payload must be an object")
    return dict(value)


@dataclass(frozen=True)
class EvidenceWeeklyCollectionRecord:
    collection_id: str
    period_start: str
    period_end: str
    source_path: str
    source_hash: str
    status: str
    payload_json: dict[str, Any] = field(default_factory=dict)
    error_type: str = ""
    error_message: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"observed_automatic", "collection_failed"}:
            raise ValueError(f"unsupported collection status: {self.status}")
        object.__setattr__(self, "payload_json", _payload(self.payload_json))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload_json"] = dict(self.payload_json)
        return payload
