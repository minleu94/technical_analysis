from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from app_module.evidence_event_dtos import EvidenceEvent, normalize_data_quality, normalize_event_type


def filtered_events(repository: Any, filters: Any) -> list[EvidenceEvent]:
    events = repository.list_events(
        symbol=filters.symbol,
        event_type=filters.event_type,
        start_date=filters.start_date,
        end_date=filters.end_date,
    )
    return [
        event
        for event in events
        if matches(event.event_family, filters.event_family)
        and matches(event.source_type, filters.source_type)
        and matches(event.regime, filters.regime)
        and matches(event.sector, filters.sector)
        and matches(event.profile_id, filters.profile_id)
        and matches(event.strategy_version_id, filters.strategy_version_id)
    ]


def group_outcome_rows(
    events: Iterable[EvidenceEvent],
    outcomes: Iterable[Any],
    *,
    group_by: str,
) -> dict[tuple[str, int], list[tuple[EvidenceEvent, Any]]]:
    event_by_id = {event.event_id: event for event in events}
    grouped: dict[tuple[str, int], list[tuple[EvidenceEvent, Any]]] = defaultdict(list)
    for outcome in outcomes:
        event = event_by_id.get(outcome.event_id)
        if event is not None:
            grouped[(group_key(event, group_by), outcome.window_days)].append((event, outcome))
    return grouped


def group_key(event: EvidenceEvent, group_by: str) -> str:
    if group_by == "event_type":
        return normalize_event_type(event.event_type).value
    if group_by == "data_quality":
        return normalize_data_quality(event.data_quality).value
    if group_by == "score_percentile_bucket":
        return score_percentile_bucket(event.score_percentile_bp)
    value = getattr(event, group_by)
    return str(value) if value not in (None, "") else "missing"


def matches(actual: Any, expected: str | None) -> bool:
    return expected is None or str(actual) == expected


def score_percentile_bucket(value: int | None) -> str:
    if value is None:
        return "missing"
    parsed = int(value)
    if parsed <= 2000:
        return "0-2000"
    if parsed <= 4000:
        return "2001-4000"
    if parsed <= 6000:
        return "4001-6000"
    if parsed <= 8000:
        return "6001-8000"
    return "8001-10000"
