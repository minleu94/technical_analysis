from __future__ import annotations

from app_module.evidence_event_dtos import EvidenceEvent
from app_module.forward_performance_read_model import ForwardPerformanceFilter
from app_module.forward_performance_read_model_support import filtered_events, group_outcome_rows


def _event(event_id: str, *, regime: str, profile_id: str) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        event_hash=f"hash-{event_id}",
        event_date="2026-07-01",
        decision_date="2026-07-01",
        symbol="2330",
        event_type="recommendation_included",
        event_family="daily_decision",
        source_type="recommendation",
        source_id=f"source-{event_id}",
        strategy_version_id="v1",
        profile_id=profile_id,
        score_percentile_bp=9000,
        regime=regime,
        sector="半導體",
        liquidity_state="normal",
        data_quality="observed",
        as_of_date="2026-07-01",
        available_date="2026-07-01",
        source_version="test-fixture",
    )


class _Repository:
    def __init__(self, events: list[EvidenceEvent]) -> None:
        self.events = events
        self.calls: list[dict[str, str | None]] = []

    def list_events(self, **kwargs: str | None) -> list[EvidenceEvent]:
        self.calls.append(kwargs)
        return self.events


def test_filtered_events_preserves_repository_filters_and_secondary_filtering() -> None:
    accepted = _event("evt-1", regime="Trend", profile_id="balanced")
    rejected = _event("evt-2", regime="Range", profile_id="aggressive")
    repository = _Repository([accepted, rejected])

    result = filtered_events(
        repository,
        ForwardPerformanceFilter(
            symbol="2330",
            event_type="recommendation_included",
            start_date="2026-07-01",
            end_date="2026-07-31",
            regime="Trend",
            profile_id="balanced",
        ),
    )

    assert result == [accepted]
    assert repository.calls == [
        {
            "symbol": "2330",
            "event_type": "recommendation_included",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        }
    ]


def test_group_outcome_rows_uses_existing_group_key_and_window_boundary() -> None:
    first = _event("evt-1", regime="Trend", profile_id="balanced")
    second = _event("evt-2", regime="Trend", profile_id="balanced")

    class _Outcome:
        def __init__(self, event_id: str, window_days: int) -> None:
            self.event_id = event_id
            self.window_days = window_days

    grouped = group_outcome_rows(
        [first, second],
        [_Outcome("evt-1", 5), _Outcome("evt-2", 5), _Outcome("unknown", 5)],
        group_by="regime",
    )

    assert list(grouped) == [("Trend", 5)]
    assert [(event.event_id, outcome.event_id) for event, outcome in grouped[("Trend", 5)]] == [
        ("evt-1", "evt-1"),
        ("evt-2", "evt-2"),
    ]
